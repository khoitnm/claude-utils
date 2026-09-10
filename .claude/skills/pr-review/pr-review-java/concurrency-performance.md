# Java — concurrency and performance

Apply when the diff touches threads, executors, async work, caching, shared state,
batch processing, or a code path that runs per-request or per-record.

## Shared mutable state

The default Spring bean is a singleton serving every request on many threads. Any
field added to a `@Service`/`@Component` that is written after construction is
shared mutable state.

- A new non-final field on a singleton bean holding request-scoped data — this is a
  data-corruption bug across users, and it is invisible in single-threaded tests.
  Treat as a blocker.
- Non-thread-safe objects as shared fields: `SimpleDateFormat`, `Calendar`,
  `HashMap`, `ArrayList`, most Jackson `ObjectReader` builders mid-configuration,
  Apache `Validator`s. (`ObjectMapper` itself *is* thread-safe once configured.)
- Static mutable collections used as an ad-hoc cache — unbounded growth plus a race.
- `volatile` used where atomicity is needed: `volatile int count; count++` is still
  a lost-update race. Use `AtomicInteger`/`LongAdder`.
- Double-checked locking without `volatile` on the field.
- Assuming a `ConcurrentHashMap` makes a compound operation atomic — `if
  (!map.containsKey(k)) map.put(k, v)` is still a race. Use `computeIfAbsent`,
  `putIfAbsent`, or `merge`. Note `computeIfAbsent`'s mapping function must not
  modify the same map.

## Locking

- Lock scope: is the critical section as small as it can be, and does it exclude
  I/O? Holding a lock across a network call serialises the whole application on the
  slowest dependency.
- Consistent lock ordering across code paths — the classic deadlock.
- `synchronized` on a mutable field reference, or on a `String`/boxed literal
  (interned, so shared application-wide).
- A `Lock` acquired outside try/finally, so an exception leaks it forever.
- Locking in a single JVM when the deployment runs multiple instances — it does not
  protect anything. Needs a DB lock, an optimistic version, or a distributed lease.

## Executors and async

- A new `ExecutorService`: bounded queue? Sensible rejection policy? Named threads
  (unnamed pool threads make production stack traces useless)? Shut down on
  application stop?
- `Executors.newCachedThreadPool()` under load creates unbounded threads;
  `newFixedThreadPool` with an unbounded queue turns overload into an OOM instead of
  backpressure. Neither default is safe for request-driven work.
- Submitting blocking work to `ForkJoinPool.commonPool()` (which is what
  `parallelStream` and a bare `CompletableFuture.supplyAsync` use) starves everything
  else in the JVM.
- `CompletableFuture` with no exception handling — `exceptionally`/`handle` or the
  failure vanishes.
- `future.get()` with no timeout can hang a request thread forever.
- Context that does not cross the thread boundary: `SecurityContextHolder`, MDC
  logging context, tenant/request `ThreadLocal`s, the transaction. This is why
  async handlers silently lose the current user.
- Virtual threads (Java 21+): `synchronized` around blocking work pins the carrier
  thread; thread-pool-per-task patterns become pointless.

## Caching

Caching has its own checklist — read **[caching.md](caching.md)** whenever the diff
adds or changes a cache. The four findings worth remembering without it:

- A key missing the tenant/user/locale leaks one customer's data to another. Blocker.
- An unbounded cache with no eviction or TTL is a memory leak with extra steps.
- A write path with no matching evict is a stale-data bug.
- Caching a failure or an empty result makes a transient outage sticky.

## Hot-path performance

Only raise these where the code actually runs often — per request, per record in a
large batch. Micro-optimising a startup path is noise.

- Work inside a loop that could be hoisted: compiling a regex, building a
  formatter, reading configuration, opening a connection.
- Repeated collection scans: `list.contains` inside a loop over another list.
- Logging inside a hot loop, or string concatenation built for a log statement that
  will not be emitted (use parameterised `log.debug("x={}", x)`).
- Loading an entire result set into memory when streaming would do.
- Copying large collections defensively in a hot path — correct, but say the cost is
  known.
- Regex catastrophic backtracking on user input (nested quantifiers) — this is both
  a performance and a DoS finding.

## Resilience (only if the repo has a resilience library, or makes remote calls)

- Every outbound call needs a **timeout** — connect and read. A missing read
  timeout is how one slow dependency takes down the whole service. Blocker in
  request-handling code.
- Retries: only on idempotent operations; with backoff and jitter; with a cap.
  Naive retry loops amplify an outage.
- A circuit breaker or bulkhead where the repo already uses that pattern for
  similar calls — consistency matters more than the specific choice.
- Connection pool sizing when a new dependency or a `REQUIRES_NEW` transaction is
  introduced.

## Memory

- Unbounded accumulation: a list built from an unbounded query, a growing static
  map, an ever-appending `StringBuilder`.
- Streaming vs materialising large files or result sets.
- `ThreadLocal` set but never removed on a pooled thread — leaks the value into the
  next request that reuses the thread, which is both a leak and a data-exposure bug.
