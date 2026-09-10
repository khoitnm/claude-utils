# Java — caching

Apply when the diff adds a cache, changes what an existing cache stores, changes a
key, a TTL, an eviction rule, an invalidation path, or a warm-up routine. Also
apply when the diff adds a *de facto* cache: a static `Map`, a memoised field, a
`@PostConstruct` that loads reference data into memory, a `List` field populated
once and read forever.

Gate every library-specific point on
[`../pr-review-shared/stack-detection.md`](../pr-review-shared/stack-detection.md).
Caffeine advice on a Guava repo, or Redis advice on a repo with no Redis, is noise.

A cache is a correctness feature pretending to be a performance feature. Nearly
every blocker below is a *wrong answer served to a user*, not a slow answer.

## Before this file: does the repo have its own caching doc?

Check for one — `docs/caching/**`, a `*-cache*.md`, a `@`-import from CLAUDE.md, a
`.claude/rules/**` file whose globs match the changed path. If it exists, **read it
first and treat it as the specification**; it knows the class names, the incidents,
and the constraints that make some rule below wrong here. Use this file only for
what that doc does not cover, and cite the repo's doc in the finding. See
[`../pr-review-shared/project-context.md`](../pr-review-shared/project-context.md).

Two rules below are the ones a house design most often overrides on purpose:

- **§4's "no maximum size is a leak"** does not apply to a deliberate whole-table
  snapshot cache, where evicting entries would break the "we hold every row"
  assumption the read path depends on.
- **§8's "a wrong not-found is a bug"** does not apply where the design has
  answered what a miss means and made the callers safe under it.

## 0. Does this need a cache at all

Ask once, and drop it if the answer is obvious from the diff:

- What is the measured cost being avoided, and what hit rate is expected? A cache
  in front of a 2 ms query, or one whose key space is so wide that nothing is ever
  read twice, is pure risk with no upside.
- Is the data cheap to fetch but expensive to get *wrong* — permissions,
  entitlements, prices, tenant config, feature flags? That combination is where
  caching bugs become incidents.
- Is there a cheaper fix: an index, a batch fetch, one query instead of N+1, a
  `LEFT JOIN FETCH`? Prefer removing the load over hiding it.
- Note that a `LEFT JOIN FETCH` or `@EntityGraph` suggestion is void in a repo
  whose rules forbid mapped associations — check before suggesting it.

### Then, before anything else: what does a miss mean?

Ask this first, because the answer determines whether half the rules below apply
at all. A key that is not in the cache means one of two very different things:

| The cached set is | A miss means | Can the caller trust it? |
| --- | --- | --- |
| A subset of the data (lazily filled, size-bounded, TTL-evicted) | "not loaded" | No — it must fall through to the source |
| Deliberately the *whole* set (a full-table snapshot, a fixed enumeration) | "no such row" | Yes, **but only while a complete snapshot exists** |

- Does any caller **write, skip a write, deny access, or return 404** based on a
  miss? Then a wrong miss is a data or authorisation bug, not a latency bug, and
  every path that can produce an incomplete cache (warm-up §8, failed reload §9,
  eviction §2) becomes a correctness question.
- An authoritative whole-set cache must never be partially populated, never
  size-evicted, and never observable mid-replacement. That is what makes §4's size
  bound and §2's eviction policy inapplicable to it — and it is a deliberate
  trade, not an oversight.
- A subset cache must have a per-key fallback, and then the risk moves to negative
  caching (§7) and stampede (§6) instead.
- Mixing the two — a whole-table cache that also caches per-key fallback hits — is
  fine, but say which keys are authoritative and which are not.

## 1. Keys — what identifies the value

The highest-yield section. Read every key expression in the diff.

- **Key completeness.** Does the key contain *everything* the value varies by:
  tenant/org/facility, user, role or permission scope, locale, currency, timezone,
  feature-flag or A/B variant, API version, `Accept` header, environment? A key
  missing the tenant serves one customer's data to another — **blocker**, always.
- **Implicit inputs.** The method may take `(id)` while the value also depends on
  `SecurityContextHolder`, a request-scoped bean, a `ThreadLocal`, or
  `LocalDate.now()`. Anything the value depends on that is not in the key is a
  correctness bug. Date-dependent values need the date in the key, or a TTL that
  cannot cross the boundary.
- **Spring's default key.** With no `key` attribute, `SimpleKeyGenerator` uses *all*
  method parameters. Adding a parameter silently changes the key (usually fine);
  removing one silently collides (not fine); passing a parameter the value does not
  depend on silently shreds the hit rate.
- **Key type contract.** Keys need a correct, stable `equals`/`hashCode`. Watch for
  entities as keys (identity semantics, or `hashCode` derived from a mutable
  field), arrays as keys (identity `equals` — never hits), and a mutable key
  mutated after insertion (the entry becomes unreachable *and* unevictable).
- **Key cardinality.** Is the key space bounded? Keys derived from free-text
  search terms, timestamps, per-request UUIDs, or whole request bodies produce
  unbounded distinct keys: a memory leak locally, a Redis memory blowout remotely,
  and a near-zero hit rate either way.
- **Namespacing and collisions.** String-concatenated keys need a separator that
  cannot occur in the parts (`"a:bc"` vs `"ab:c"`). A shared Redis/Hazelcast
  instance needs an application prefix, plus a version segment so a value-shape
  change cannot read old-shaped data after deploy.
- **`null` in the key.** `"quote:" + orgId` with a null `orgId` collapses every
  anonymous caller into one shared `"quote:null"` entry. Reject earlier, or use a
  separate keyspace.

## 2. Eviction policy — behaviour at capacity

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

## 3. Expiration — TTL, TTI, and refresh

- **TTL (expire-after-write)** bounds staleness — the guarantee an operator cares
  about. **TTI (expire-after-access)** bounds only idle memory: a hot key with TTI
  alone never expires and can serve stale data indefinitely. Anything that can
  change needs a TTL, with or without TTI. TTI alone on mutable data is a finding.
- Is the TTL derived from a stated business tolerance for staleness, or is it a
  magic `60`? The review question is "how stale may this be, and who decided?"
- **A periodic full reload is the TTL.** A cache refreshed by a scheduler every
  five minutes bounds staleness at five minutes (plus the reload duration) without
  any per-entry TTL, so do not ask for `expireAfterWrite` on top of it. Review the
  *interval* instead — §9 covers the scheduling traps, and the staleness bound to
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

## 4. Size and memory

- **A cache with no maximum size is a memory leak** — *unless the set it holds is
  bounded by something other than traffic*. `maximumSize` or `maximumWeight` is
  mandatory when the key space grows with requests; an unbounded static `Map` keyed
  by anything user-supplied is the classic production `OutOfMemoryError` and a
  **blocker**.
- The exception is a deliberate whole-set cache (a full-table snapshot, a fixed
  enumeration): its size follows **table size, not traffic**, and a size limit
  would break the "we hold every row" guarantee the callers depend on (§0). Do not
  ask for `maximumSize` there. Ask instead: how many rows today, how many after the
  biggest plausible tenant onboards, how many copies exist at once during a reload
  (source list + new map + old snapshot), and does the load time still fit inside
  the reload interval as the table grows?
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

## 5. Concurrency and thread safety

- The cache must be thread-safe: Caffeine, Guava `Cache`, `ConcurrentHashMap`,
  Ehcache, Hazelcast. A plain `HashMap`/`LinkedHashMap`/`ArrayList` as a shared
  cache is a data race — lost entries or a spinning resize under load, invisible in
  single-threaded tests. **Blocker.**
- `Collections.synchronizedMap` is safe per operation but serialises all access and
  does not make check-then-act atomic. `containsKey` then `put` is still a race;
  use `computeIfAbsent` / `putIfAbsent` / `merge`.
- `ConcurrentHashMap.computeIfAbsent` holds a bin lock for the whole mapping
  function: expensive I/O inside it blocks unrelated keys, recursive access to the
  same map deadlocks or throws, and an exception propagates to the caller with
  nothing cached. Caffeine degrades more gracefully but still computes under a
  per-key lock.
- Lock scope: never hold a global lock across the load itself (a DB or network
  call). That converts a cache miss into an application-wide stall on the slowest
  dependency.
- Visibility: a lazily-initialised cache field needs `volatile`, a static holder,
  or `final` assignment in the constructor. Double-checked locking without
  `volatile` is broken.
- `ThreadLocal` "caches" on pooled threads leak the previous request's value into
  the next one unless removed in a `finally` — a leak *and* a cross-user data
  exposure.
- A local cache in a multi-instance deployment is N independent caches: per-JVM
  locking protects nothing, and two nodes can answer the same key differently. Say
  so when the diff assumes one JVM.

## 6. Stampede / thundering herd

- On a cold key or right after expiry, do 500 concurrent requests all hit the
  database? Use single-flight: a `LoadingCache` (Caffeine/Guava load once per key),
  `@Cacheable(sync = true)`, `computeIfAbsent`, or an explicit per-key mutex. A
  hand-rolled `get` → `if (null) load` → `put` has no single-flight, and after key
  incompleteness it is the most common caching bug to reach review.
- Per-key locks, not one global lock — and bound the lock map, or it becomes its
  own unbounded cache.
- Probabilistic early expiration (XFetch-style: refresh early with a probability
  that rises as expiry approaches) or `refreshAfterWrite` spreads reloads instead
  of cliff-edging them.
- Distributed stampede: N instances miss the same Redis key at the same moment.
  Single-flight *within* a JVM does not fix that — it needs a short-TTL
  distributed lock/lease, or an explicit decision to accept N loads.
- Negative-lookup stampede: a key that never resolves is a permanent miss and a
  permanent load. See §7.
- Stampede on failure: if the loader throws, does every next request retry
  immediately? An outage plus retry-per-request is an amplification loop. Cache the
  failure briefly, or put a circuit breaker in front.

## 7. Null, empty, and exception handling

- Decide and state the policy: is "not found" a cached value? If not, a
  nonexistent id costs one query per request forever — a trivial DoS vector when
  the id comes from user input.
- If nulls are cached, give them a *shorter* TTL than hits (a row that appears
  should become visible soon) and use a sentinel or `Optional`, because most caches
  cannot store `null`: Caffeine/Guava treat a `null` load as "absent" and never
  cache it, and Spring `@Cacheable` with `cacheNullValues = false` (the Redis
  default) silently skips every null — so the "negative cache" the code appears to
  implement does not exist.
- `Optional` as a value is fine locally; through a distributed cache it must
  serialise (Jackson `Jdk8Module` or equivalent).
- Empty collections: distinguish "no results" from "not loaded". Caching an empty
  list because the loader failed is a silent wrong answer.
- Do not cache exceptions or fallback values as if they were data. One timeout
  turning into a TTL's worth of "this customer has no entitlements" is a
  **blocker**. Use `unless` / `condition`, or catch and skip the put.
- Partial results: a loader that swallows an inner failure and caches a
  half-built value is worse than an error. Fail the load instead.
- If a resilience fallback returns degraded data, make sure the cache-put happens
  on the success path only.

## 8. Warm-up (first load at startup)

Each of these is an edge case warm-up PRs routinely miss. Check them all.

- **Where does it run?** A `@PostConstruct` or `CommandLineRunner` blocking on a
  remote call delays startup and can trip container start probes; an
  `ApplicationReadyEvent` / async warm-up starts serving traffic before the cache is
  populated. Both are defensible — the PR must pick one on purpose and match the
  readiness probe to it.
- **Failure.** If warm-up throws, what happens? Realistically either fail startup
  (safe for a hard dependency, but now a dependency outage blocks every deploy and
  every autoscale event) or log and continue empty (usually right, *provided* a lazy
  load path exists). What is not acceptable: the exception swallowed with no metric,
  no WARN-or-above log, and no retry, leaving a permanently empty cache that nobody
  notices because the hit-rate alarm does not exist. **Blocker.**
- **Partial failure.** Warm-up loads 8 000 of 10 000 entries, then fails. Is the
  cache now a trap — present, so lookups "hit", but silently answering "not found"
  for 2 000 keys? A partially warmed cache must either fall through to the source
  on miss or be discarded entirely. Any cache used as an authoritative complete set
  ("if it is not in the cache it does not exist") must be swapped in atomically,
  all-or-nothing.
- **Concurrent access while warming.** A request arriving mid-warm-up gets one of:
  block until ready (needs a timeout, or requests queue until the thread pool is
  exhausted), miss through to the source (correct, but warm-up now competes with
  live traffic for the same dependency), or an answer derived from an empty cache.
  That last one is a bug *only if a caller can trust a miss* (§0) — a design that
  deliberately reports "not loaded yet" to a caller that then queries the source,
  or that fails the request loudly, is fine. Whichever it is must be deliberate,
  and the `CountDownLatch` / `volatile boolean ready` gate has to be checked on
  *every* read path, not just the one the PR touches.
- **The queue behind a failed first load.** If N readers block on one load lock and
  the load fails, does each queued reader then re-run it? Sixteen readers become
  sixteen full-table queries, each holding a DB connection, and a cheap read turns
  into a connection-pool outage. The fix is to tell readers already queued behind a
  failed attempt "still empty" while letting a reader that *arrives after* it retry
  — trading a stampede for a stall is not a fix either, so check which one the code
  actually does.
- **Deadlock and ordering.** Warm-up that touches beans still initialising,
  triggers another cache's warm-up, or waits on a pool created later in the
  lifecycle. Circular warm-up between two caches hangs startup with no error.
- **Timeout and budget.** Warm-up needs its own timeout and a bounded query — not
  `findAll()` on a table that grew 100× since the code was written. Loading a table
  that no longer fits in heap turns a deploy into an OOM crash loop.
- **Retry.** With backoff, jitter, and a cap, and only against an idempotent
  source. Unbounded startup retry across a rolling deploy is a self-inflicted DDoS
  on the database.
- **Fleet effects.** Every instance warms the same data at the same time during a
  rolling deploy or scale-out: N× the load spike, precisely when the fleet is
  already degraded. Stagger it, throttle it, or size the source for N.
- **Observability.** Log warm-up start, duration, entry count, and outcome, and
  expose a "cache ready" flag/metric. Without those, "the cache is empty in prod"
  is unfalsifiable.
- **Repeatability.** Warm-up must be idempotent and safe to run twice — context
  refresh, an actuator-triggered reload, tests reusing a context.
- **Tests.** Does the test context run warm-up? Either it does (slow, and the
  source must be stubbed) or it does not (and the warm-up path is untested and will
  break unnoticed). Profile-gate it explicitly rather than by accident.

## 9. The update path — invalidation, transactions, and replacement

The core question of any caching PR: **when the underlying data changes, does the
cache change with it — and does it change only if the data change actually
survived?** Trace one concrete write end to end before writing a finding:

1. Who writes the row? (Every writer, not just the one in the diff.)
2. What evicts or overwrites the cached key, and does that key match the read key
   exactly?
3. When does that happen relative to the **commit**?
4. What does a concurrent reader see in the window between the write and the
   eviction — and what is left in the cache if the transaction **rolls back**?

A PR that cannot answer all four has a stale-data bug in it somewhere. Steps 3 and
4 are where reviews usually stop too early, so they get their own subsection below.

### Does an update reach the cache at all?

- **Invalidation completeness.** Find *every* write path that changes the
  underlying data: the service method in the diff, batch jobs, admin tools, other
  services writing the same table, direct SQL, data migrations, replication,
  restores. A write path with no evict is a stale-data bug, and it is the most
  commonly missed finding in a caching PR. The read side being correct proves
  nothing — grep for writers of the table/aggregate, not just callers of the
  changed method.
- **Key match between write and read.** A mismatch between the `@Cacheable` key and
  the `@CacheEvict` key evicts nothing, and it looks correct in review. Compare the
  two expressions character by character, including the cache *name*. Same for a
  hand-rolled `cache.invalidate(...)`: if the read builds `"quote:" + orgId + ":" +
  userId` and the write invalidates `"quote:" + orgId`, nothing is ever evicted.
- **Derived and dependent entries.** One row change may invalidate more than one
  key: a list/search cache, a count, an aggregate, a parent object embedding the
  child, a "latest N" cache. Updating an address must evict the customer DTO that
  inlines it. Ask which *other* cached values contain a copy of the changed field.
- **Eviction granularity.** `allEntries = true` on a hot cache for a single-row
  change trades a stale-data bug for a stampede. Prefer a keyed evict — but only
  where the write path can compute the key exactly. If it cannot, `allEntries` plus
  a comment is the honest choice.
- **Bulk operations.** `saveAll`, `deleteAll`, JPQL bulk `update`/`delete`, and
  native queries bypass entity lifecycle callbacks and Hibernate's second-level
  cache; their evictions must be explicit. A bulk `UPDATE ... WHERE` that touches
  10 000 rows usually means `allEntries = true`, not 10 000 keyed evicts.
- **Read-your-own-writes.** After a write, does the same user's next read see the
  change? Behind a load balancer with a per-node local cache, usually not — evict
  everywhere, route the immediate read to the source, or state the guarantee. "I
  saved it and the screen still shows the old value" is the bug report this
  produces.
- **Cross-instance invalidation.** With a local cache on N nodes, an evict on node
  1 leaves nodes 2..N stale until their TTL. If a pub/sub or topic broadcast is
  used, handle its failure modes: a node that was down or partitioned misses the
  message and stays stale until TTL — so the TTL is still the safety net. A
  long-TTL local cache over mutable shared data with no broadcast is a finding.
- **Two-layer caches** (local L1 + Redis L2) need both invalidated, in the right
  order (evict L2, then broadcast L1), and the L1 TTL must be short enough to bound
  the inconsistency a lost broadcast leaves behind.
- **Write-through / write-behind.** Write-behind can lose buffered writes on crash
  and can reorder writes to one key. If the diff introduces it, that trade has to be
  explicit.

### Transactions: commit, rollback, and the window in between

The cache is not part of the database transaction. Every mismatch below comes from
that one fact, and each is a **blocker** because the cache ends up asserting
something the database does not.

- **Evict before commit — stale value resurrects.** `@CacheEvict` (and a manual
  `evict`/`put`) fires when the method returns, which is *before* the surrounding
  transaction commits unless the cache manager is transaction-aware. Interleaving:
  thread A updates the row and evicts → thread B misses, reads the **old**
  uncommitted-elsewhere value from the database, and caches it → thread A commits.
  The cache now holds the pre-update value and keeps serving it for a full TTL, long
  after the write is committed and visible in the database. Evict *after* commit:
  `TransactionAwareCacheManagerProxy`, a `TransactionSynchronization.afterCommit`,
  or `@TransactionalEventListener(phase = AFTER_COMMIT)`.
- **Rollback after a cache put — the cache holds data that never existed.** A
  `@CachePut`, or any manual `put` inside a transaction that later rolls back,
  leaves the cache asserting a value the database never had. Every reader gets it
  until the TTL expires; no error is logged; the database is correct and the
  application is wrong. This is the exact question to ask on any write path that
  *populates* rather than *evicts*. Ways it happens quietly:
  - the exception is thrown *after* the annotated method returns — a later step in
    the same transaction, a validation in an outer service, a constraint violation
    surfacing only at flush/commit;
  - the transaction is marked rollback-only by an inner `@Transactional` method
    whose exception was caught and swallowed by the caller (`UnexpectedRollback`
    at commit, cache already written);
  - `@Transactional` rolls back on unchecked exceptions only, so a checked
    exception commits a partial write that the cache then reflects — or does not;
  - an optimistic-lock retry: attempt 1 puts its value, fails on
    `OptimisticLockException`, attempt 2 writes different data, and whichever put
    landed last wins in the cache regardless of which transaction committed;
  - a savepoint/nested rollback undoes part of the write while the cache keeps the
    whole of it.
- **The safe default: on a write path, evict — do not put.** A wrong evict costs
  one reload; a wrong put costs correctness. `@CachePut` is only safe when it runs
  after commit, and populating a cache from the object you just wrote is exactly
  what breaks under rollback. Note `@CacheEvict(beforeInvocation = true)` is
  rollback-safe in the useful direction: the entry is gone, so the next read
  reloads whatever the database actually has.
- **Evict-after-commit is not free either.** If the process dies, the broadcast is
  lost, or the post-commit hook throws, the write is committed but the cache is
  never invalidated — stale until TTL, with no error on the request path. That is
  why a mutable cache still needs a bounded TTL as the backstop, and why an evict
  failure after commit deserves a WARN plus a metric, not a swallowed exception.
- **Uncommitted data must never enter a shared cache.** A read inside the writing
  transaction sees its own uncommitted changes; caching that value publishes
  uncommitted (possibly rolled-back) state to every other user. Watch for a
  `@Cacheable` read called from inside a `@Transactional` write method.
- **State the mismatch window.** For every cached value that can be updated, the PR
  should be able to say how long the cache may disagree with the database
  (milliseconds until an after-commit evict, seconds until a broadcast lands, up to
  the full TTL if a broadcast is lost) and whether that is acceptable for this
  data. Money, entitlements, and clinical data usually are not.
- **Hibernate's second-level cache already solves this** — `READ_WRITE` soft-locks
  an entry for the duration of the transaction and only publishes after commit, and
  `TRANSACTIONAL` is fully JTA-coordinated. `NONSTRICT_READ_WRITE` explicitly does
  not: it has a documented window where the cache and the row disagree, so it is
  only for rarely-updated data. If the diff hand-rolls a cache over entities that
  the second-level cache would handle correctly, say so.

### Refresh and replacement of a whole snapshot

- **Clear-then-refill is a correctness hole**, not just a slow path. Between
  `cache.clear()` and the reload, every reader sees an empty cache: a stampede at
  best, wrong "not found" answers if the cache is authoritative. Build the new
  snapshot into a fresh structure and swap an `AtomicReference` / `volatile` field
  in one step. **Blocker** when the cache is authoritative.
- **Failed refresh.** Serve the previous value (stale but plausible) rather than
  replacing it with nothing or an error placeholder. Whichever is chosen, count it
  and alarm on consecutive failures — a cache that quietly stopped refreshing is
  indistinguishable from a working one until the data is badly wrong.
- **In-flight readers during replacement.** A reader that grabbed the reference
  before the swap keeps using the old snapshot, which is fine *provided* it is a
  consistent whole. A reader that fetches several keys across a swap can observe a
  mix of old and new: if the values are mutually consistent (rates and rules, ids
  and names), cache them as one immutable snapshot object rather than as independent
  keys.
- **A reload overwriting a fresher single-entry refresh.** The silent one, and the
  one reviews miss. Reading the table takes time, so a snapshot is already stale
  when it is written: reload reads at `10:00:00` → a user renames the row and the
  write path refreshes that one entry at `10:00:01` → the reload writes its
  `10:00:00` list at `10:00:03` and the rename disappears from the cache. No error,
  no warning, healthy metrics; you hear about it as "my change didn't save", and
  **shortening the interval to reduce staleness makes it more likely**. The fix is
  either prevention (compare row timestamps/versions before overwriting an entry) or
  repair (record keys refreshed while a reload was in flight, then re-read them
  *after* the snapshot is written). If the PR chose repair, check three things:
  only the **last** reload out may settle the queue (an earlier finisher draining it
  lets a later `putAll` re-clobber those keys); the repair re-reads must not
  re-queue themselves; and a *failed* reload wrote nothing, so its queued keys need
  no repair and must be dropped rather than accumulated while the source is sick.
- **Deleting entries during a reload.** A reload that removes "anything not in the
  list I just read" will delete a row created *after* it started reading. It looks
  like correct clean-up, so nobody notices. Restrict deletion to keys that were
  present **before** the load began.
- **Overlapping reloads.** A scheduled tick can overlap a reload triggered by a
  cold read, or by a previous tick that ran long. Two reloads writing snapshots in
  an unknown order, both mutating shared repair state, is where the subtle bugs
  live. Ask what happens when one reload takes longer than the interval.
- **The reload interval itself.** `@Scheduled` resolves its interval **once, at bean
  initialisation** — a `fixedRateString = "#{...}"` SpEL expression is evaluated
  there too, so a config-driven interval still needs a redeploy. To change it at
  runtime you need a short fixed tick that *checks* whether the configured interval
  has elapsed (re-reading the config each tick), or a `SchedulingConfigurer` with a
  `Trigger`. Two traps in the tick approach: an exact `elapsed >= interval`
  comparison never fires on the intended tick (the tick lands a hair late), and if
  that tick re-stamps the schedule, every interval silently becomes one tick longer
  — allow half a tick of slack. And reading configuration every tick is not free:
  use the narrow accessor, not an aggregate that rebuilds everything and logs a
  warning per absent value.

## 10. Value integrity

- **Mutability.** A cache handing out a shared mutable object lets any caller
  corrupt the entry for everyone, often by accident via a setter deep in the call
  graph. Cache immutable values — records, `List.copyOf`, defensive copies on put
  *and* get. **Blocker** where a caller demonstrably mutates it.
- The same applies to nested state: an immutable wrapper around a mutable
  `ArrayList` field is not immutable.
- Never cache values holding live resources: an open stream, a connection, a
  `MessageDigest`, a `SimpleDateFormat`.
- A cached value that embeds a permission decision must be keyed by the principal,
  or it is an authorisation bypass — the classic "user B sees user A's dashboard".

## 11. Serialization (distributed or persistent caches)

- Moving from a local cache to Redis/Hazelcast/Infinispan: keys *and* values must
  be serialisable by the configured serialiser. Java serialisation requires
  `Serializable` on the value and everything it references; JSON requires a usable
  constructor/getters; both need `serialVersionUID` or an equivalent version
  discipline.
- **Schema evolution across a rolling deploy** is the edge case that bites: old and
  new instances share one cache. Adding a field is usually survivable; removing or
  renaming one, or changing a type, means one version reads what it cannot
  deserialise. Handle it with a version-prefixed key namespace (new code simply
  misses), a tolerant deserialiser (`FAIL_ON_UNKNOWN_PROPERTIES = false`), or a
  flush at deploy — and treat a deserialisation failure as a *miss*. **Blocker** if
  it propagates to the caller as a 500.
- **Never enable Jackson polymorphic default typing** (`enableDefaultTyping`,
  `activateDefaultTyping(LaissezFaireSubTypeValidator)`) on a cache serialiser, and
  never Java-deserialise cache content you do not fully control: anyone who can
  write to the cache then has remote code execution. **Blocker.**
- Types that serialise badly: `LocalDate`/`Instant` without `JavaTimeModule`,
  `Optional` without `Jdk8Module`, Hibernate lazy proxies (a
  `LazyInitializationException` on write, or interceptor guts in the payload),
  `BigDecimal` scale loss through JSON, `Map`s with non-`String` keys, cyclic
  references.
- Cost and size: serialisation now happens on every access. Large values
  (multi-MB documents, whole result sets) can make the "cache" slower than the
  query, and a very large Redis value blocks the server for every other client.
- Instance-level differences in default timezone, locale, or charset change
  serialised output — and therefore keys, if a key is derived from a serialised form.

## 12. The distributed cache as a dependency

- Every Redis/Hazelcast call needs connect *and* read timeouts. An unbounded cache
  read hangs the request thread and the cache becomes the outage.
- Fail open, not closed: when the cache is unreachable, does the request fall
  through to the source (degraded but working) or fail? Falling through has to be
  paired with a judgement about whether the source survives 100 % miss traffic.
- Check connection pool sizing and the client's own thread usage under load.
- Hot keys concentrate on one shard; a cluster needs a keyslot/hash-tag story for
  multi-key operations.
- Always set a TTL on distributed entries. Without one the keyspace grows until the
  server's `maxmemory` policy starts evicting things assumed to be durable.
- `KEYS`/`SCAN`-driven invalidation over a large keyspace on a busy instance is a
  latency incident; keep an index set of keys, or bump a namespace version instead.
- On a Redis instance shared with other applications, confirm the prefix, the
  memory limit, and the eviction policy are yours and not someone else's.

## 13. Security and privacy

- PII, PHI, tokens, or credentials in a cache: is that within the data
  classification? A distributed cache is a new copy of the data, frequently
  unencrypted at rest and retained far longer than the request.
- Cached authorisation or entitlement decisions need the principal in the key and a
  TTL short enough that revocation takes effect — logout, role change, account
  disable. State the revocation lag.
- Keys derived from user input leak into logs, into metric labels (unbounded
  cardinality), and into error messages.
- Cache-key enumeration on a shared cache: can a caller craft a key that collides
  with another tenant's entry?
- Do not log whole cached values on eviction or refresh "for debugging".

## 14. Observability

- `recordStats()` (Caffeine/Guava) or the equivalent must be enabled and the cache
  registered with the metrics registry. Spring Boot binds `CacheMetricsRegistrar`
  only for caches it manages, so a hand-rolled cache exports nothing by default.
- Minimum useful signals via Micrometer/Prometheus/JMX: hit ratio, miss count, load
  count, load latency (p50/p99), load *failure* count, eviction count, current
  size/weight, and — for a refreshing cache — the age of the newest successful
  refresh.
- **Hit and miss counts cannot detect staleness.** A complete but hours-old
  snapshot reports a beautiful hit ratio; so does a cache whose reloads have been
  failing since midnight. For any periodically refreshed cache the number to alert
  on is **seconds since the last successful reload** (a gauge), plus the reload
  itself timed with a `success|failure` outcome tag. Check that this gauge also
  reads correctly *before* the first load — initialise the "last success" timestamp
  to the epoch, not to `now()`, or a cache that never loaded reports as perfectly
  fresh.
- Ask which failures the design **cannot** detect, and get them written down. Some
  races (a reload clobbering a fresher entry, §9) cannot be logged without building
  the same tracking that fixing them requires — so "we will just log it for now" is
  not the cheaper option it sounds like.
- Do not substitute log noise for a metric. A WARN inside a health indicator fires
  on every Kubernetes probe; a WARN for an absent optional config fires on every
  scheduler tick. Log on state *transitions*; keep steady-state conditions in
  metrics.
- Alarm on the ones that mean "silently wrong": hit-ratio collapse (a key change or
  an accidentally disabled cache), a refresh-failure streak, size pinned at maximum
  (undersized), an eviction-rate spike.
- A new cache with no metrics is an IMPROVEMENT finding at minimum. A cache with a
  swallowed load failure and no metric is a BLOCKER — nobody will find out.
- Name caches consistently: a typo'd cache name in `@Cacheable` creates a second
  cache (or, with `NoOpCacheManager`, nothing at all) and raises no error.

## 15. Configuration and operability

- TTL, maximum size, and the on/off switch belong in externalised config, not in
  compiled constants, so an incident can be mitigated without a deploy.
- Is there a kill switch (property or feature flag) to bypass the cache, and a way
  to flush it (actuator endpoint, admin call)? Ask for both on any cache in a
  critical path.
- Environment differences: is the cache enabled everywhere the code is tested? A
  cache active only in production is an untested code path.
- Document the consistency contract beside the cache: what it stores, what it is
  keyed by, how stale it may be, who evicts it. One comment, not a design doc.

## 16. Spring cache abstraction specifics

Only if the repo uses `@EnableCaching` / `spring-context-support`.

- Is `@EnableCaching` present with a real `CacheManager` bean? Without one, Boot
  may fall back to `ConcurrentMapCacheManager` (unbounded, no TTL — a leak), or a
  `NoOpCacheManager` caches nothing at all while every annotation still reads as
  correct.
- **Self-invocation does not go through the proxy**: an internal call to a
  `@Cacheable` method on the same bean is a plain method call and is never cached.
  Same trap as `@Transactional`.
- `@Cacheable` on a `private`, `final`, or `static` method — silently not proxied.
- `sync = true` gives single-flight; note it is unsupported together with `unless`
  or with multiple cache names.
- `condition` is evaluated before the call, `unless` after — so `unless` can inspect
  `#result`, which is where "do not cache empty or failed results" belongs.
- `@CachePut` always runs the method and writes the result; `@Cacheable` may skip
  it. Confusing the two on a write method yields either no caching or a cached
  pre-commit value.
- `@CacheEvict(beforeInvocation = false)` — the default — does not evict when the
  method throws, so a partially applied write leaves a stale entry. Consider
  `beforeInvocation = true` for deletes.
- One global TTL across caches with very different volatility is worth a comment;
  per-cache configuration usually exists already.
- `@Cacheable` on a method returning `CompletableFuture` / `Mono` / `Flux` without
  reactive-aware support caches the *unsubscribed publisher*, which is essentially
  never intended.

## 17. Tests to ask for

- Hit and miss: a test proving the source is called once for two identical calls
  (`verify(repo, times(1))`). Without it, nothing proves the cache works at all.
- Key sensitivity: two tenants/users/locales get different values. This is the test
  that catches the leak in §1.
- Eviction: after the write path runs, the next read returns the new value.
- Rollback: a write that fails after the cache is touched (throw from a later step,
  or fail a constraint at flush) leaves **no** value in the cache that the database
  does not have — assert the next read returns the pre-write row. This is the test
  that catches a `@CachePut` on a rolled-back transaction.
- Commit ordering: the evict happens after commit, not before. Testable by
  registering a `TransactionSynchronization` in the test, or by asserting the
  post-commit event fired; at minimum assert a transaction-aware cache manager is
  the one wired in.
- Expiry: driven by an injectable `Ticker`/`Clock`, never `Thread.sleep`. A
  sleep-based TTL test is a flaky test.
- Concurrency: for hand-rolled single-flight, a latch-based test with N threads
  asserting exactly one load.
- Serialization round-trip for any distributed value, including the null/empty case
  and the version-skew case.
- Failure: the loader throws → nothing is poisoned, and the next call retries.
- Isolation: a static or context-scoped cache leaking state between test methods
  creates order-dependent tests. Clear it in `@BeforeEach`, or use
  `@DirtiesContext` deliberately.

Four test traps that make a caching test lie rather than fail:

- **An unstubbed mock repository returns an empty list from `findAll()`, and that
  looks like success** — not like "no call happened". A reload in such a test
  concludes the table is empty and evicts everything, and the assertion that should
  have caught it passes.
- **Re-stubbing a mock that is currently set to throw actually throws.**
  `when(repo.findAll())` *calls* the method; use `doReturn(...).when(repo)` when a
  previous stubbing may throw.
- **Starting N tasks in a loop does not create a race** — the first can finish
  before the last starts. Release them together from a latch, and run any new
  multi-threaded test several times before trusting a pass.
- **Do not `sleep` to test timing.** Keep the time decision in a pure function that
  takes the instants as arguments, so a test can pass any values.
