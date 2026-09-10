# Java caching — thread safety and stampede

**Applies to kinds:** A, B, C for thread safety; the stampede half is B and C (kind A's equivalent is the cold-start queue in [warm-up.md](warm-up.md)).

Apply when the cache is shared between threads, which is every singleton-scoped cache.

## Concurrency and thread safety

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

## Stampede / thundering herd

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
  permanent load. See [misses-and-failures.md](misses-and-failures.md).
- Stampede on failure: if the loader throws, does every next request retry
  immediately? An outage plus retry-per-request is an amplification loop. Cache the
  failure briefly, or put a circuit breaker in front.
