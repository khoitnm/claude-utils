# Java caching — security, metrics, and operability

**Applies to kinds:** A, B, C. The metrics section is where silent failures get caught, and the metric that matters differs by kind.

Apply to any new cache. The metrics section is where silent caching failures get caught.

## Security and privacy

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
- Do not log whole cached values on eviction or refresh "for debugging" — that
  copies the payload, PII included, into a log store with different retention and
  broader access than the cache itself.

## Observability

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
  races (a reload clobbering a fresher entry — see
  [snapshot-reload.md](snapshot-reload.md)) cannot be logged without building
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

## Configuration and operability

- TTL, maximum size, and the on/off switch belong in externalised config, not in
  compiled constants, so an incident can be mitigated without a deploy.
- Is there a kill switch (property or feature flag) to bypass the cache, and a way
  to flush it (actuator endpoint, admin call)? Ask for both on any cache in a
  critical path.
- Environment differences: is the cache enabled everywhere the code is tested? A
  cache active only in production is an untested code path.
- Document the consistency contract beside the cache: what it stores, what it is
  keyed by, how stale it may be, who evicts it. One comment, not a design doc.
