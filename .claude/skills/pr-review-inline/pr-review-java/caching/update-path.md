# Java caching — the update path on write

Apply when the diff changes data that is cached, or changes what evicts a cached key. For a whole-snapshot reload, see [snapshot-reload.md](snapshot-reload.md).

## The update path — invalidation, transactions, and replacement

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
