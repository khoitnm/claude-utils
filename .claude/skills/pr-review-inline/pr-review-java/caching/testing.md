# Java caching — tests to ask for

Apply when the diff adds caching logic, with or without tests.

## Tests to ask for

- Hit and miss: a test proving the source is called once for two identical calls
  (`verify(repo, times(1))`). Without it, nothing proves the cache works at all.
- Key sensitivity: two tenants/users/locales get different values. This is the test
  that catches the key-completeness leak in
  [keys-and-values.md](keys-and-values.md).
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
