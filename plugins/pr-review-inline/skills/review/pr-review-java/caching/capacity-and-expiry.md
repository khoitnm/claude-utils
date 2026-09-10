# Java caching — eviction, expiry, size and memory

**Applies to kinds:** B and C only. **Not A** — a full-dataset cache has no capacity to reach and its reload interval is its TTL, so a `maximumSize`/TTL finding here is wrong on it. **Not D** — a request-scoped cache dies with the request.

Apply to a size-bounded cache. Mostly N/A for a full-dataset cache — see [kinds.md](kinds.md) before raising anything here.

## Eviction policy — behaviour at capacity

Skip this section for a full-dataset cache (kind A): it has no capacity limit to
reach, and eviction there would be a bug rather than a policy.

- Is a policy chosen deliberately, and does it match the access pattern? **LRU**
  (recency) is the safe default. **LFU / W-TinyLFU** (Caffeine's `maximumSize`
  policy) survives one-off scans that would flush an LRU. **FIFO** ignores usage
  entirely and is usually wrong for a read cache. Random eviction is acceptable
  only under uniform access.
- A scan-heavy path — a report, a nightly job, an export — hitting a shared LRU
  evicts the working set for every online user. Give it its own region or exclude
  it from the cache.
- Eviction listeners: is anything relying on them for cleanup (closing a resource,
  releasing a lock)? Caffeine removal listeners run asynchronously and are **not**
  guaranteed at JVM shutdown; Guava's run during later map operations. Cleanup that
  must happen cannot live only in a listener.
- Distributed caches evict on their own terms. Redis `maxmemory-policy noeviction`
  turns a full instance into write errors; `allkeys-lru` will evict keys the code
  assumed were durable (sessions, locks, idempotency records). Confirm which policy
  the deployment actually runs.

## Expiration — TTL, TTI, and refresh

- **TTL (expire-after-write)** bounds staleness — the guarantee an operator cares
  about. **TTI (expire-after-access)** bounds only idle memory: a hot key with TTI
  alone never expires and can serve stale data indefinitely. Anything that can
  change needs a TTL, with or without TTI. TTI alone on mutable data is a finding.
- Is the TTL derived from a stated business tolerance for staleness, or is it a
  magic `60`? The review question is "how stale may this be, and who decided?"
- **A periodic full reload is the TTL.** A cache refreshed by a scheduler every
  five minutes bounds staleness at five minutes (plus the reload duration) without
  any per-entry TTL, so do not ask for `expireAfterWrite` on top of it. Review the
  *interval* instead — [snapshot-reload.md](snapshot-reload.md) covers the scheduling traps, and the staleness bound to
  state is "interval + reload time", measured from the last **success**, not the
  last attempt.
- TTL versus the invalidation story: reliable evictions permit a long TTL; no
  invalidation path demands a short one. Long TTL *and* no invalidation is a
  stale-data bug waiting for a support ticket.
- Uniform TTLs created at the same instant (warm-up, deploy, a batch fill) expire
  at the same instant. Add jitter, or accept a synchronised stampede.
- `refreshAfterWrite` (Caffeine) serves the stale value while one thread reloads —
  usually right in a request path — but it only triggers *on access*, and a failed
  refresh keeps serving stale silently. Pair it with a metric.
- Clock source: durations driven by `System.currentTimeMillis()` are vulnerable to
  NTP steps; use a monotonic ticker. A cache keyed on "today" needs an explicit
  timezone.
- Expiry is lazy in most local caches — entries linger until touched or until
  maintenance runs. Do not assume memory is reclaimed the moment a TTL passes
  (`cleanUp()` exists for a reason), and do not write a test that assumes it.

## Size and memory

- **A cache with no maximum size is a memory leak** — *unless the set it holds is
  bounded by something other than traffic*. `maximumSize` or `maximumWeight` is
  mandatory when the key space grows with requests; an unbounded static `Map` keyed
  by anything user-supplied is the classic production `OutOfMemoryError` and a
  **blocker**.
- **A full-dataset cache (kind A) is the exception, and asking it for a
  `maximumSize` is a wrong finding.** Its size follows **dataset size, not
  traffic**; a limit would silently break the completeness guarantee its callers
  depend on, turning a memory question into a correctness one. The design is valid
  precisely because the team knows the data is small and bounded. What to review
  instead is whether that premise is written down and still true:
  - How many rows today, and how many after the largest plausible growth event
    (a big tenant onboarding, a backfill, a new market)? A cache that is fine at
    5 000 rows and fatal at 5 000 000 needs the number stated, not implied.
  - How many copies exist at once during a reload — the source list, the new map,
    and the old snapshot still serving reads? Peak is a multiple of the steady
    state.
  - Does the load still fit inside the reload interval as the dataset grows, and
    what happens when it does not ([snapshot-reload.md](snapshot-reload.md))?
  - Is there anything that would *notice* the growth before the OOM — a logged
    entry count, a size gauge, an alert threshold?
  - If the premise cannot hold indefinitely, the honest finding is "this design
    has a documented ceiling; record it and alert before it", not "add
    `maximumSize`".
- Is the bound in the right unit? `maximumSize(10_000)` of 2 MB values is 20 GB.
  Values whose size varies by orders of magnitude (documents, result lists, images)
  need `maximumWeight` with a real weigher.
- Do the capacity math in the review: entries × average retained size vs heap. If
  the author cannot state it, ask. Count what the value *retains* — a cached entity
  can drag its whole Hibernate graph; a `subList` view retains the parent list.
- Cache DTOs or ids, not JPA entities: entities keep detached graphs alive and
  interact badly with the persistence context.
- Weak/soft references are a last resort, not a memory strategy: soft references
  make GC pauses worse and turn the cache into an unpredictable oracle, and weak
  *keys* use identity `equals`, so string or boxed keys evaporate immediately.
- Off-heap or disk tiers (Ehcache 3, Hazelcast, Chronicle) buy heap headroom at the
  cost of serialisation on every access — reasonable only when the diff shows that
  cost is acceptable.
- Multiple caches sized independently, each "small", summing past the heap. Look at
  the total across the config file, not the one line in the diff.
- GC effects: a large long-lived cache is a permanent old-gen tenant and changes
  pause behaviour. A cache added in the same release as an OOM is the first suspect.
