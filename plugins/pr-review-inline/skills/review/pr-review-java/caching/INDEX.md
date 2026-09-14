# Java caching — dispatch index

Apply when the diff adds a cache, changes what one stores, or changes a key, TTL,
eviction rule, invalidation path, or warm-up. Also apply when the diff adds a
*de facto* cache: a static `Map`, a memoised field, a `@PostConstruct` that loads
reference data, a `List` field filled once and read forever.

A cache is a correctness feature pretending to be a performance feature. Nearly
every blocker in these files is a *wrong answer served to a user*, not a slow one.

## Before anything: does the repo have its own caching doc?

Check for one — `docs/caching/**`, a `*-cache*.md`, a `@`-import from CLAUDE.md, a
`.claude/rules/**` file whose globs match the changed path. If it exists, **read it
first and treat it as the specification**; it knows the class names, the incidents,
and the constraints that make some rule here wrong. Where the two disagree, the
repo's doc wins — including where it forbids something here or permits something
here calls a blocker. Cite the repo's doc in the finding. See
[`../../pr-review-shared/project-context.md`](../../pr-review-shared/project-context.md).

## The findings that actually recur

Check these on every caching change, before reading any file below. Most caching
PRs contain one of them, and a review that catches one of these has earned its
keep even if it says nothing else.

1. **A key missing a dimension the value varies by** — tenant, user, permission
   scope, locale. Serves one customer's data to another. Blocker.
2. **An unbounded cache whose key space grows with traffic** — the classic OOM.
   (Not the same as a deliberately unbounded full-dataset cache; see
   [kinds.md](kinds.md) first.)
3. **A write path with no matching evict** — including batch jobs, admin tools and
   direct SQL, not just the method in the diff.
4. **An evict that runs before the transaction commits** — a concurrent reader
   repopulates the cache with pre-commit data and it survives a full TTL.
5. **A `put` on a path that can roll back** — the cache then asserts a value the
   database never had.
6. **A cached failure or empty result** — one timeout becomes a TTL of wrong
   answers.
7. **A hand-rolled `get` → `if (null) load` → `put`** — no single-flight, so a cold
   key means N concurrent loads.
8. **A shared mutable value** handed to callers who mutate it.
9. **A swallowed load or reload failure with no metric** — the cache silently stops
   updating and nothing notices.
10. **Warm-up that fails, partially fills, or serves reads before it finishes** —
    see [warm-up.md](warm-up.md).

## Read only what the diff needs

Start with [kinds.md](kinds.md), then obey the **Kinds** column: A = full-dataset
preload, B = lazy per-key, C = distributed, D = request-scoped. The rules for A and
B contradict each other on purpose, so a file read against the wrong kind produces
confident, wrong findings — the `maximumSize` demand on a deliberately unbounded
full-dataset cache being the classic one. Every file repeats its own gate in its
first line.

| Read this | Kinds | When the diff… |
| --- | --- | --- |
| **[kinds.md](kinds.md)** | all | Always. Which of the four kinds this is, which rules that makes N/A, whether a caller can trust a miss, and whether the cache is needed at all. |
| **[keys-and-values.md](keys-and-values.md)** | all | Always. Touches a cache key or what is stored. |
| **[capacity-and-expiry.md](capacity-and-expiry.md)** | **B, C** | Sets or omits a size bound, eviction policy, TTL, or TTI. Skip for a full-dataset cache. |
| **[concurrency-and-stampede.md](concurrency-and-stampede.md)** | A, B, C | Shares a cache across threads, or loads on a miss. |
| **[misses-and-failures.md](misses-and-failures.md)** | B, C | Decides what happens on a miss, a null, an empty result, or a loader exception. |
| **[warm-up.md](warm-up.md)** | **A** | Loads anything at startup, or gates reads on a "loaded" flag. |
| **[update-path.md](update-path.md)** | A, B, C | Changes data that is cached, or changes what evicts a key. Transactions and rollback live here. |
| **[snapshot-reload.md](snapshot-reload.md)** | **A** | Replaces the cache contents wholesale, on a timer or on demand. |
| **[distributed.md](distributed.md)** | **C** | Puts the cache out of process — Redis, Hazelcast, Infinispan. |
| **[operations.md](operations.md)** | A, B, C | Adds a cache at all: security, metrics, kill switch, documented staleness. |
| **[spring-cache.md](spring-cache.md)** | B, C | Uses `@Cacheable`/`@CacheEvict`/`@CachePut`. |
| **[testing.md](testing.md)** | all | Adds caching logic, with or without tests. |

A three-line TTL change needs `kinds.md` and `capacity-and-expiry.md`, not twelve
files. A new snapshot cache with a scheduled reload needs `kinds.md`, `warm-up.md`,
`snapshot-reload.md`, and `operations.md`.
