# Java — Spring

Only apply if `pom.xml` / `build.gradle` shows a Spring dependency. Note Boot 2
(`javax.*`) vs Boot 3 (`jakarta.*`) before commenting on imports or Security config.

## Beans and wiring

- **Constructor injection**, not field `@Autowired`. Field injection hides required
  dependencies, breaks immutability, and makes the class untestable without a
  container. Raise this on new classes; do not demand a refactor of untouched ones.
- A new dependency added to a bean's constructor: check for a cycle. Spring reports
  circular dependencies at startup, but `@Lazy` added to hide one is a design smell
  worth a comment.
- **Bean scope**: the default is singleton. A field added to a `@Service` that
  holds per-request state is shared across all threads — a real concurrency bug and
  one of the most common Spring defects in review.
- `@Value` on a field with no default, for a property that may not be set in every
  environment — fails at startup, in production, on the environment nobody tested.
- New `@Configuration` classes: `@Bean` methods calling each other rely on CGLIB
  proxying; in `@Configuration(proxyBeanMethods = false)` that call creates a second
  instance.
- `@Component` on a class that is also declared as a `@Bean` — two instances.
- New `@Profile` usage: is every environment covered, or does some profile now
  start with a missing bean?

## Transactions

High-yield area; these bugs are silent.

- **`@Transactional` on a non-public method** (private, protected, package-private)
  is a **no-op** under the default proxy mode. The code runs with no transaction.
- **Self-invocation**: calling an annotated method from another method of the same
  bean bypasses the proxy — no transaction. Look for `this.doTransactional()`.
- `@Transactional` on a method that also does slow non-DB work — an HTTP call, file
  I/O, a message publish — holds the DB connection and locks for the whole
  duration. Move the I/O out.
- **`rollbackFor`**: by default Spring rolls back on unchecked exceptions only. A
  method that catches an exception, or throws a checked one, commits partial work.
- `readOnly = true` on a method that writes — silently fails or throws depending on
  the dialect.
- Propagation: `REQUIRES_NEW` inside an existing transaction takes a second
  connection from the pool; under load this deadlocks the pool.
- Work that must happen only after commit (publishing an event, sending an email,
  enqueueing a job) done inside the transaction — it fires even if the transaction
  later rolls back. `TransactionSynchronization`/`@TransactionalEventListener` with
  `AFTER_COMMIT` is the fix.
- A `@Transactional` method with `@Async` or `@Scheduled`: the transaction does not
  propagate across the thread boundary the way people assume.

## Web layer (Spring MVC — `spring-boot-starter-web`)

- **Validation**: `@RequestBody` DTOs need `@Valid`/`@Validated` on the parameter,
  or the constraint annotations on the DTO do nothing. Very commonly missed.
- `@Validated` on the class is required for constraints on `@RequestParam`/
  `@PathVariable` to be enforced.
- Path variables and request params: `required = false` without a default produces
  `null`; primitives then throw on unboxing.
- Returning entities directly from a controller instead of a DTO — leaks the schema,
  triggers lazy-loading during serialization, and couples the API to the DB.
- New exception types: is there an `@ExceptionHandler`/`@ControllerAdvice` mapping
  them to a sensible status, or do they all become 500?
- HTTP semantics: correct status codes (201 + Location for creation, 204 for empty,
  404 vs 403 — leaking existence through the status is an information disclosure),
  idempotency for PUT/DELETE.
- New endpoint added: is it covered by the existing security config, or does the
  matcher pattern miss it? Check the URL against the `SecurityFilterChain` matchers
  literally — a new prefix often falls outside them.
- `@RestController` methods returning `void` where the client expects a body.
- Pagination: a new list endpoint with no limit will eventually return the whole
  table.

## Reactive (only if WebFlux / Reactor is a dependency)

- **Blocking calls inside a reactive chain** — JDBC, `RestTemplate`, `Thread.sleep`,
  `.block()` — on an event-loop thread. This stalls all requests, not just one.
  Treat as a blocker.
- A `Mono`/`Flux` that is never subscribed does nothing. A method that builds a
  publisher and ignores it is dead code that looks alive.
- Missing `subscribeOn`/`publishOn` for genuinely blocking work
  (`Schedulers.boundedElastic()`).
- `ThreadLocal`-based context (MDC, SecurityContext, tenant) does not propagate
  across reactive operators — use the Reactor context.
- Error handling: `onErrorResume` returning an empty publisher silently converts a
  failure into "no data".

## Async and scheduling

- `@Async` on a method called from within the same bean — same proxy problem as
  `@Transactional`, silently synchronous.
- `@Async` returning `void` discards exceptions entirely unless an
  `AsyncUncaughtExceptionHandler` is configured. Return `CompletableFuture`.
- `@Async` with no explicit executor uses a default that may be unbounded — check
  the configured `TaskExecutor` and its queue/rejection policy.
- `@Scheduled` in a multi-instance deployment runs on every instance. Is that
  intended, or is a lock (ShedLock, DB lease) needed?
- `@Scheduled` method throwing: the scheduler logs and continues, but the failure is
  invisible without a metric.

## Configuration and properties

- New property added: is it documented, does it have a sane default, and is it
  present in every environment's config?
- Secrets in `application.yml` committed to the repo.
- `@ConfigurationProperties` classes need the binding to actually be enabled
  (`@EnableConfigurationProperties` or `@ConfigurationPropertiesScan`) and setters
  or a constructor binding — otherwise fields stay null.
- Changing a property's default value changes behaviour for every existing
  deployment. Call it out explicitly.

## Spring Security (only if a Spring Security dependency exists)

- New endpoints and the matcher order: `authorizeHttpRequests` rules are evaluated
  in order; a broad `permitAll` earlier shadows a later restriction.
- `@PreAuthorize`/`@Secured` require method security to be enabled, and they suffer
  the same self-invocation proxy limitation.
- CSRF disabled — acceptable for a stateless token API, a hole for a cookie-session
  app. Ask which this is.
- CORS widened to `*` with credentials.
- `SecurityContextHolder` read on a different thread (async, reactive, executor) —
  it is thread-local and will be empty.

## Observability and lifecycle

- New failure mode with no metric or log at a level anyone watches.
- Beans holding resources should release them: `@PreDestroy`, or `destroyMethod` on
  `@Bean`.
- Blocking work in `@PostConstruct` or an `ApplicationRunner` delays or fails
  startup — including a remote call that may be down.
