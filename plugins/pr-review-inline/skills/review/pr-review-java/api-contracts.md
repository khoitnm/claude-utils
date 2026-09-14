# Java — API contracts, DTOs, serialization

Apply when the diff adds or changes an HTTP endpoint, a request/response type, a
serialized payload, a published event/message, or a public method on a library
other code depends on.

## The compatibility question

For every changed field, method signature, or payload, ask: **who else reads
this, and do they deploy at the same time?** They usually do not.

Breaking changes, in rough order of how often they slip through:

- Removing or renaming a JSON field that a client reads.
- Changing a field's type (`String` → `Long`, scalar → object, single → array).
- Making an optional request field required.
- Making a response field that was always present now optional/absent.
- Changing an enum's serialized values, or adding a value the consumer's parser
  rejects.
- Changing the meaning of a field while keeping its name and type. The worst kind —
  nothing fails, the data is just wrong downstream.
- Tightening validation on an existing endpoint: requests that used to succeed now
  400.
- Changing a status code, or an error response's shape.
- Reordering parameters of the same type in a public method — compiles fine at
  every call site, does the wrong thing.

The safe pattern is additive: new optional field, both fields served during a
deprecation window, remove later.

## Request DTOs

- Validation annotations present **and** actually enforced (`@Valid` on the
  parameter — see [spring.md](spring.md)).
- Constraints on strings that reach a database column: `@Size` matching the column
  length, or the insert fails at the DB layer with an ugly 500.
- Numeric bounds — a page size with no maximum is a denial-of-service handed to any
  caller.
- Fields the client must not be able to set (id, ownerId, tenantId, role, price,
  audit fields). Binding those from the request body is mass-assignment; it is a
  security finding, not a style one.
- Unknown-field handling: does the deserializer fail or ignore? Failing is safer
  for internal APIs, ignoring is friendlier for public ones — but it should be
  deliberate.

## Response DTOs

- No entity returned directly. Beyond coupling, it leaks columns nobody meant to
  publish and triggers lazy loading during serialization.
- No sensitive field on the response: password hash, internal IDs, other tenants'
  data, PHI/PII the caller is not entitled to. Check what the DTO's mapper actually
  copies, not what its name suggests.
- Nulls vs absent fields: is the serialization inclusion setting deliberate? A
  client distinguishing "field absent" from "field null" will break when this
  changes.
- Collections: empty list rather than null.

## Jackson / serialization specifics (if Jackson is a dependency)

- A new field with no getter (or no matching accessor naming) silently does not
  serialize.
- Deserialization requires a no-arg constructor or `@JsonCreator`; a class with
  only an all-args constructor fails at runtime unless the parameter-names module
  is active.
- `@JsonProperty` needed when the Java name and the wire name differ; renaming the
  Java field without it silently renames the wire field.
- `java.time` types need the JSR-310 module registered, or they serialize as
  objects/arrays instead of ISO strings.
- Date/time serialized without a zone or with a machine-local zone.
- `BigDecimal` serialized as a float loses precision in some clients — string is
  safer for money.
- Polymorphic deserialization (`@JsonTypeInfo`) driven by a type field from
  untrusted input is a deserialization-gadget risk.
- Bidirectional object graphs recursing infinitely — needs `@JsonManagedReference`/
  `@JsonBackReference` or a DTO.

## OpenAPI / documented contract

- If the repo publishes a spec (`openapi.yaml`, springdoc annotations), the change
  must be reflected there in the same PR. A spec that has drifted from the code is
  worse than no spec.
- Example values and descriptions updated, not left describing the old behaviour.

## Events and messages

- Consumers deploy independently: the same compatibility rules apply, harder,
  because in-flight messages in the queue were serialized by the *old* code.
- A schema change must be readable by consumers that have not yet deployed.
- Is the consumer idempotent? At-least-once delivery means the new handler will see
  duplicates.
- Poison-message handling: what happens on a message that always fails — retry
  forever, or DLQ?
- Ordering assumptions that the broker does not actually guarantee.

## Versioning and deprecation

- If the change is breaking and cannot be made additive, is there a version bump, a
  new path, or a documented coordination plan? "The client team knows" is not a
  plan; ask for it in writing in the PR description.
- `@Deprecated` on the old method/field with a pointer to the replacement, and a
  removal target.
