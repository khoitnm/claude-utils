# Java caching — which kind of cache is this

Read this first. It decides which of the other files apply, and half the rules in them are wrong for the wrong kind.

## Which kind of cache is this?

There is no single correct set of caching rules, because "cache" covers designs
with opposite constraints. **A rule that is mandatory for one kind is a defect for
another.** Decide the kind first, from the code — then apply only the rules that
belong to it. Getting this wrong in either direction is a bad review: demanding a
size limit on a full-dataset cache is as wrong as accepting an unbounded
per-request one.

| Kind | Shape in code | Bounded by | What a miss means |
| --- | --- | --- | --- |
| **A. Full-dataset preload** | Load the entire table/list once at startup, reload periodically, serve every read from memory | Dataset size — chosen because the team knows the data is small and stays small | "No such row" — the cache is authoritative *while complete* |
| **B. Lazy per-key** | `@Cacheable`, `LoadingCache`, `computeIfAbsent` — fill on first request, evict under pressure | An explicit `maximumSize`/`maximumWeight` and a TTL | "Not loaded" — must fall through to the source |
| **C. Distributed shared** | Redis/Hazelcast/Infinispan behind the same API | Server memory policy plus a per-entry TTL | "Not loaded", plus "the cache is down" as a third case |
| **D. Request- or session-scoped** | A map on a request-scoped bean, a `ThreadLocal`, Hibernate's first-level cache | The lifetime of the request | "Not loaded in this request" |

Most real systems mix them: a full-dataset cache with a per-key fallback for rows
created since the last reload, or an in-process L1 in front of a distributed L2.
Say which parts are which, because the rules follow the part, not the class.

### Which rules apply to which kind

| Rules | A. Full-dataset | B. Lazy per-key | C. Distributed | D. Request-scoped |
| --- | --- | --- | --- | --- |
| [Eviction policy](capacity-and-expiry.md) | **N/A** — evicting breaks completeness | Required | Server-side policy | N/A |
| [Per-entry TTL / TTI](capacity-and-expiry.md) | **N/A** — the reload interval *is* the staleness bound | Required | Required, or the keyspace grows forever | N/A |
| [`maximumSize`](capacity-and-expiry.md) | **N/A** — size follows the dataset; project its growth instead | **Required** | Required | N/A |
| [Stampede](concurrency-and-stampede.md) | One bulk load, so it is the cold-start queue instead | Per-key single-flight | Cross-instance single-flight | N/A |
| [Negative caching](misses-and-failures.md) | Decided by completeness, not by TTL | Central question | Central question | Rarely matters |
| [Warm-up](warm-up.md) | **The critical section** | Usually nothing to warm | Usually nothing to warm | N/A |
| [Reload / replacement races](snapshot-reload.md) | **The critical section** | Per-key evict on write | Both layers, plus broadcast | N/A |
| [Serialization](distributed.md) | N/A | N/A | **Required** | N/A |
| [Cache as a dependency](distributed.md) | N/A | N/A | **Required** | N/A |
| [Keys and value integrity](keys-and-values.md), [thread safety](concurrency-and-stampede.md), [security and metrics](operations.md) | Apply to all four | | | |

Kind D has one failure mode of its own worth checking, because it looks safe:
a per-request cache built on a `ThreadLocal` or a static map on a pooled thread
outlives the request unless it is cleared in a `finally`, at which point it is
serving one user's data to the next (see [concurrency-and-stampede.md](concurrency-and-stampede.md)).

**When the kind is not stated anywhere, say so.** "Is this meant to hold the whole
table, or just the hot subset?" is a legitimate QUESTION finding — the answer
determines whether the absence of a size limit is a deliberate design or an
oversight, and no reviewer can tell those apart from the diff alone.

## Does this need a cache at all

Ask once, and drop it if the answer is obvious from the diff:

- What is the measured cost being avoided, and what hit rate is expected? A cache
  in front of a 2 ms query, or one whose key space is so wide that nothing is ever
  read twice, is pure risk with no upside.
- Is the data cheap to fetch but expensive to get *wrong* — permissions,
  entitlements, prices, tenant config, feature flags? That combination is where
  caching bugs become incidents.
- Is there a cheaper fix: an index, a batch fetch, one query instead of N+1, a
  `LEFT JOIN FETCH`? Prefer removing the load over hiding it.
  (Check the repo's data-access rules before proposing a specific query fix — see
  [`../persistence-sql.md`](../persistence-sql.md).)

### Then: can a caller trust a miss?

The kind tells you what a miss *means*; this tells you what it *costs*.

- Does any caller **write, skip a write, deny access, or return 404** based on a
  miss? Then a wrong miss is a data or authorisation bug, not a latency bug, and
  every path that can produce an incomplete cache — warm-up, a failed or
  racing reload, eviction — becomes a correctness question rather than a
  performance one.
- An authoritative cache (kind A) must therefore never be partially populated,
  never size-evicted, and never observable mid-replacement. Those three
  constraints are what buy the right to trust a miss.
- A cache whose miss means "not loaded" (kinds B, C, D) must have a fallback to the
  source on every read path — and then the risk moves to negative caching and
  stampede instead ([misses-and-failures.md](misses-and-failures.md),
  [concurrency-and-stampede.md](concurrency-and-stampede.md)).
- In a mixed design, say which keys are authoritative and which are not. A cache
  that is authoritative for the rows it preloaded and lazy for rows created since
  is two caches wearing one class name, and each half gets its own rules.
