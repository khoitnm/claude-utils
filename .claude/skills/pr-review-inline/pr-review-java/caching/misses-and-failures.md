# Java caching — nulls, empties, and failed loads

**Applies to kinds:** B and C mainly. For A, what a miss means is settled by completeness — see [kinds.md](kinds.md).

Apply when the diff decides what happens on a miss, a null, an empty result, or a loader failure.

## Null, empty, and exception handling

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
