# Java caching — warm-up at startup

Apply when the diff adds or changes a load at startup: `@PostConstruct`, `CommandLineRunner`, an `ApplicationReadyEvent` listener, or a first-read-loads guard.

## Warm-up (first load at startup)

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
  That last one is a bug *only if a caller can trust a miss* (see [kinds.md](kinds.md)) — a design that
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
