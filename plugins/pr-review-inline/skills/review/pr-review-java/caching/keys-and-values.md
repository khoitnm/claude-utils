# Java caching — keys and cached values

**Applies to kinds:** A, B, C, D (all of them).

Apply to every caching change. A wrong key or a shared mutable value is a correctness bug, not a performance one.

## Keys — what identifies the value

The highest-yield section. Read every key expression in the diff.

- **Key completeness.** Does the key contain *everything* the value varies by:
  tenant/org/facility, user, role or permission scope, locale, currency, timezone,
  feature-flag or A/B variant, API version, `Accept` header, environment? A key
  missing the tenant serves one customer's data to another — **blocker**, always.
- **Implicit inputs.** The method may take `(id)` while the value also depends on
  `SecurityContextHolder`, a request-scoped bean, a `ThreadLocal`, or
  `LocalDate.now()`. Anything the value depends on that is not in the key is a
  correctness bug. Date-dependent values need the date in the key, or a TTL that
  cannot cross the boundary.
- **Spring's default key.** With no `key` attribute, `SimpleKeyGenerator` uses *all*
  method parameters. Adding a parameter silently changes the key (usually fine);
  removing one silently collides (not fine); passing a parameter the value does not
  depend on silently shreds the hit rate.
- **Key type contract.** Keys need a correct, stable `equals`/`hashCode`. Watch for
  entities as keys (identity semantics, or `hashCode` derived from a mutable
  field), arrays as keys (identity `equals` — never hits), and a mutable key
  mutated after insertion (the entry becomes unreachable *and* unevictable).
- **Key cardinality.** Is the key space bounded? Keys derived from free-text
  search terms, timestamps, per-request UUIDs, or whole request bodies produce
  unbounded distinct keys: a memory leak locally, a Redis memory blowout remotely,
  and a near-zero hit rate either way.
- **Namespacing and collisions.** String-concatenated keys need a separator that
  cannot occur in the parts (`"a:bc"` vs `"ab:c"`). A shared Redis/Hazelcast
  instance needs an application prefix, plus a version segment so a value-shape
  change cannot read old-shaped data after deploy.
- **`null` in the key.** `"quote:" + orgId` with a null `orgId` collapses every
  anonymous caller into one shared `"quote:null"` entry. Reject earlier, or use a
  separate keyspace.

## Value integrity

- **Mutability.** A cache handing out a shared mutable object lets any caller
  corrupt the entry for everyone, often by accident via a setter deep in the call
  graph. Cache immutable values — records, `List.copyOf`, defensive copies on put
  *and* get. **Blocker** where a caller demonstrably mutates it.
- The same applies to nested state: an immutable wrapper around a mutable
  `ArrayList` field is not immutable.
- Never cache values holding live resources — an open stream, a connection, a
  `MessageDigest`, a `SimpleDateFormat`. The entry outlives the scope that owns
  the resource, so the second caller gets a closed stream, a leaked connection, or
  corrupted output from concurrent use.
- A cached value that embeds a permission decision must be keyed by the principal,
  or it is an authorisation bypass — the classic "user B sees user A's dashboard".
