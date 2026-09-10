# Java — core language and API

Applies to any `.java` change.

Language-feature and style suggestions are gated twice: by the language level (see
[`INDEX.md`](INDEX.md)) **and** by the repo's own style rules, which may forbid a
construct this file would otherwise recommend. Read those rules before suggesting
one — see
[`../pr-review-shared/project-context.md`](../pr-review-shared/project-context.md).
A style suggestion that contradicts the team's documented rule costs the whole
review its credibility.

## Nullability

- A new method returning a reference type: can it return `null`, and does every
  caller handle that? Trace the callers — this is where real NPEs come from.
- A new parameter added to an existing method: what do existing call sites pass,
  and is `null` among them?
- `Optional` used correctly: as a **return type**, not as a field or a parameter.
  `Optional.get()` without `isPresent()` is a latent crash — prefer `orElseThrow`
  with a meaningful exception, `orElse`, or `map`.
- Unboxing a `Integer`/`Long`/`Boolean` that can be null — `int x = map.get(k)`
  NPEs on a miss. Common in code reading from a `Map` or a JPA projection.
- If the repo uses `@Nullable`/`@NonNull` annotations, new signatures should carry
  them; annotations that lie are worse than none.

## Equality, hashing, comparison

- A class used as a `HashMap` key or in a `HashSet` needs `equals` **and**
  `hashCode`, consistent with each other and based on stable fields.
- Mutable fields in `hashCode` means the object gets lost in the set after mutation.
- `equals` must stay symmetric and transitive — subclass `equals` that adds fields
  breaks this.
- `compareTo` inconsistent with `equals` causes `TreeMap`/`TreeSet` to silently drop
  entries.
- Comparing boxed types with `==` (`Integer` beyond the −128..127 cache) — a
  classic bug that passes in tests with small numbers.
- Comparing `String` with `==`.
- JPA entities: `equals`/`hashCode` on a generated ID is broken before the entity is
  persisted (the ID is null). Prefer a business key, or a constant `hashCode`.

## Collections

- Returning an internal mutable collection from a getter lets callers mutate your
  state. Return a copy or an unmodifiable view.
- Modifying a collection while iterating it — `ConcurrentModificationException`, or
  worse, silent skipping when using an index loop.
- `List.of(...)`, `Map.of(...)`, `Arrays.asList(...)`, and `Collectors.toUnmodifiableList`
  produce immutable (or fixed-size) collections; code that later calls `add`
  throws at runtime, not at compile time.
- `Map.of()` / `Set.of()` reject nulls and duplicate keys at runtime.
- Choosing the wrong structure for the access pattern: `contains` on a `List` in a
  loop is O(n²); a `HashSet` makes it O(n). Worth raising when n is unbounded.
- Iteration order assumed from a `HashMap`/`HashSet`. If order matters, the type is
  wrong.

## Streams

- A stream with a side effect in `map`/`filter`/`peek` — mutation inside a stream
  pipeline is a maintenance trap and breaks under `parallelStream`.
- `parallelStream()` on a small collection, on I/O-bound work, or with shared
  mutable state. It uses the common ForkJoinPool; one blocking task there degrades
  the whole JVM. Almost always the wrong call in request-handling code.
- `Collectors.toMap` throws on duplicate keys — is a duplicate possible in the real
  data? Supply a merge function or explain why not.
- `findFirst` on an unordered stream when the choice actually matters.
- Streams that hide an N+1: a `map` that calls a repository per element.
- Readability: a five-stage pipeline with nested lambdas is often worse than a
  loop. Raise only when it is genuinely hard to follow.

## Exceptions

See also [`../pr-review-shared/cross-cutting.md`](../pr-review-shared/cross-cutting.md) §2.

- Catching `Exception` to convert to a runtime type without preserving the cause:
  `throw new ServiceException("failed")` loses the stack trace. Pass the cause.
- Exceptions used for control flow in a hot path — building a stack trace is
  expensive.
- `InterruptedException` caught and swallowed: either rethrow or restore the flag
  with `Thread.currentThread().interrupt()`. Swallowing it makes shutdown hang.
- New checked exception on an existing public method is a breaking change for
  callers.
- Custom exception types that carry no more information than the message.

## Resource handling

- Every `Closeable` in a try-with-resources, including in the failure path.
  `InputStream`, `Connection`, `Statement`, `ResultSet`, `Files.lines`, `Files.walk`,
  `Scanner`, HTTP response bodies.
- Streams returned from `Files.list`/`Files.walk`/`Files.lines` **must** be closed —
  they hold a file handle.
- A `finally` block that throws swallows the original exception.

## Immutability and object design

- New value-carrying classes: prefer final fields set in the constructor. If the
  language level is 16+ and the type is a pure data carrier, a `record` is the
  right shape.
- Setters added to a class that is shared across threads or cached.
- Constructors doing real work — I/O, registration, `this` escaping to another
  object before construction finishes.
- Static mutable state. Almost always a bug in a server application; it is shared
  across every request and every test.
- A class that has grown a second responsibility in this PR — worth one comment,
  not a redesign demand.

## Strings, numbers, time

- Money or precise decimals in `double`/`float`. Must be `BigDecimal` (and compare
  with `compareTo`, not `equals`, since scale differs).
- Integer overflow in arithmetic that can grow — durations in millis, byte counts,
  IDs. `Math.multiplyExact` / a wider type when it matters.
- Integer division truncating where a fraction was intended (`(a / b) * 100`).
- String concatenation in a loop; `String.format` in a hot path or inside a log
  call that may not be emitted (use parameterised logging).
- Locale-sensitive operations without an explicit locale: `toLowerCase()`,
  `String.format`, `DateTimeFormatter`. The Turkish-I bug is real.
- Charset-dependent operations without an explicit charset (`new String(bytes)`,
  `getBytes()`, `FileReader`).
- `Date`/`Calendar`/`SimpleDateFormat` in new code — use `java.time`.
  `SimpleDateFormat` is not thread-safe and is a genuine bug as a shared field.
- Time zones: `LocalDateTime` has no zone, so it is wrong for an instant in time.
  Use `Instant`/`ZonedDateTime` for events, `LocalDate` for calendar dates.
- `System.currentTimeMillis()` for elapsed time — use `System.nanoTime()`; for
  testability, prefer an injected `Clock`.

## Lombok (only if `lombok` is a dependency)

- `@Data` on a JPA entity: generates `equals`/`hashCode`/`toString` over all fields,
  which triggers lazy loading and can recurse infinitely on bidirectional relations.
- `@Builder` without `@Builder.Default` silently drops field initialisers.
- `@AllArgsConstructor` on a class whose fields have the same type — reordering
  fields silently reorders arguments at every call site with no compile error.
- `@SneakyThrows` hiding a checked exception from callers.
- `@EqualsAndHashCode` including a mutable or lazily-loaded field.

## Explicit types, not `var`

**Declare the type. Never suggest `var`, and raise it when the diff introduces
it.** The point is type-safety at a glance: a reader of the diff, or of a stack
trace six months from now, can see what a variable is without inferring it from
the right-hand side or opening the called method. `var` also hides a changed return
type — a refactor that switches a factory from `List<Customer>` to
`List<CustomerSummary>` silently retypes every `var` that consumed it, and the
compiler only complains further downstream, if at all.

- A new `var` declaration: ask for the explicit type. Keep it to **one comment per
  PR** unless the types differ in kind — a list of eleven identical nitpicks is
  padding, and per [`../pr-review-shared/severity-and-output.md`](../pr-review-shared/severity-and-output.md)
  this is a NITPICK unless the inferred type is genuinely unclear at the call site,
  in which case it is an IMPROVEMENT.
- Never rewrite an explicit type *to* `var` as a "simplification", and never cite
  verbosity as a reason to prefer it.
- Long generic types are an argument for a better type, not for `var`: extract a
  named type, a record, or a type alias-style wrapper if the declaration is
  unreadable.
- The exception the language forces: an anonymous class or an intersection type
  that has no denotable name. Those are rare; everything else has a type you can
  write.
- If the repo's own rules explicitly endorse `var`, follow the repo — the
  precedence in [`../pr-review-shared/project-context.md`](../pr-review-shared/project-context.md)
  still applies, and it is the repo's codebase.

## Modern-Java suggestions (gate on the language level)

Only suggest these if `stack-detection.md` confirmed the release supports them, and
only when they meaningfully improve the changed code — not as a blanket
modernisation demand on a PR that had another purpose. `var` is excluded from this
list regardless of the release — see above.
