# Java caching — distributed and persistent caches

Apply only when the cache is out of process: Redis, Hazelcast, Infinispan, or anything serialized to disk.

## Serialization (distributed or persistent caches)

- Moving from a local cache to Redis/Hazelcast/Infinispan: keys *and* values must
  be serialisable by the configured serialiser. Java serialisation requires
  `Serializable` on the value and everything it references; JSON requires a usable
  constructor/getters; both need `serialVersionUID` or an equivalent version
  discipline.
- **Schema evolution across a rolling deploy** is the edge case that bites: old and
  new instances share one cache. Adding a field is usually survivable; removing or
  renaming one, or changing a type, means one version reads what it cannot
  deserialise. Handle it with a version-prefixed key namespace (new code simply
  misses), a tolerant deserialiser (`FAIL_ON_UNKNOWN_PROPERTIES = false`), or a
  flush at deploy — and treat a deserialisation failure as a *miss*. **Blocker** if
  it propagates to the caller as a 500.
- **Never enable Jackson polymorphic default typing** (`enableDefaultTyping`,
  `activateDefaultTyping(LaissezFaireSubTypeValidator)`) on a cache serialiser, and
  never Java-deserialise cache content you do not fully control: anyone who can
  write to the cache then has remote code execution. **Blocker.**
- Types that serialise badly: `LocalDate`/`Instant` without `JavaTimeModule`,
  `Optional` without `Jdk8Module`, Hibernate lazy proxies (a
  `LazyInitializationException` on write, or interceptor guts in the payload),
  `BigDecimal` scale loss through JSON, `Map`s with non-`String` keys, cyclic
  references.
- Cost and size: serialisation now happens on every access. Large values
  (multi-MB documents, whole result sets) can make the "cache" slower than the
  query, and a very large Redis value blocks the server for every other client.
- Instance-level differences in default timezone, locale, or charset change
  serialised output — and therefore keys, if a key is derived from a serialised form.

## The distributed cache as a dependency

- Every Redis/Hazelcast call needs connect *and* read timeouts. An unbounded cache
  read hangs the request thread and the cache becomes the outage.
- Fail open, not closed: when the cache is unreachable, does the request fall
  through to the source (degraded but working) or fail? Falling through has to be
  paired with a judgement about whether the source survives 100 % miss traffic.
- Check connection pool sizing and the client's own thread usage under load.
- Hot keys concentrate on one shard; a cluster needs a keyslot/hash-tag story for
  multi-key operations.
- Always set a TTL on distributed entries. Without one the keyspace grows until the
  server's `maxmemory` policy starts evicting things assumed to be durable.
- `KEYS`/`SCAN`-driven invalidation over a large keyspace on a busy instance is a
  latency incident; keep an index set of keys, or bump a namespace version instead.
- On a Redis instance shared with other applications, confirm the prefix, the
  memory limit, and the eviction policy are yours and not someone else's.
