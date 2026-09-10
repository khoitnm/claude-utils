# Java caching — the Spring cache abstraction

**Applies to kinds:** B and C, wherever the Spring annotations are the mechanism.

Apply only if the repo uses `@EnableCaching` / `spring-context-support`.

## Spring cache abstraction specifics

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
