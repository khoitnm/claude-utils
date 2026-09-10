# Java — testing

Apply when the diff changes `src/test/**`, **or** when it adds production logic and
does not. The absence of a test is itself a finding.

Match the idioms to what is on the test classpath (JUnit 5 vs 4, Mockito vs
EasyMock, AssertJ vs Hamcrest vs plain JUnit) — see
[`../pr-review-shared/stack-detection.md`](../pr-review-shared/stack-detection.md).

## Coverage of the change

- Every new branch — each `if`, each `catch`, each `switch` arm, each early return —
  needs a test that takes it. Ask specifically: which test fails if I delete this
  new condition? If the answer is none, the branch is untested.
- **Would the test fail without the fix?** For a bug-fix PR this is the whole
  question. A regression test that passes against the old code tests nothing.
- Boundaries, not just the middle: 0, 1, n, n+1, empty, null, max length, the
  exact threshold value on both sides.
- The error path. New error handling with no test is the norm and it is wrong —
  error paths that never ran once are usually broken.
- New public API on a shared class: at least one test defining its contract.

## Test quality

- **Tests behaviour, not implementation.** A test that verifies "the service called
  the repository" passes even when the service computes the wrong answer. Assert on
  the returned value or the resulting state.
- **The test's own arithmetic.** Off-by-one in the expected value, a hardcoded
  string length that is wrong, an index that happens to work. Compute it by hand.
- A test with no assertion, or whose only assertion is `assertNotNull`.
- Assertions that restate the mock: `when(repo.find()).thenReturn(x)` then
  `assertEquals(x, service.get())` proves only that Mockito works.
- **Over-mocking**: mocking the class under test, or mocking value objects and
  DTOs. If the setup is longer than the test, the design is being tested rather
  than the behaviour.
- Test names that describe the scenario and the expectation, not `test1` /
  `testGetUser`.
- One logical behaviour per test. A test with four unrelated act-assert blocks
  reports one failure for four problems.
- No conditionals or loops in test bodies — a test with an `if` may assert nothing
  on some runs.

## Mockito specifics

- `verify` on everything (over-specified) makes the test break on every harmless
  refactor. Verify interactions that *matter* — the side effect, the external call.
- Stubbing a method that is never called: Mockito's strict stubs fail on this;
  under lenient settings it silently hides a wrong assumption.
- `any()` everywhere in a verify weakens it to "something was called". Match the
  arguments you care about; use `ArgumentCaptor` when you need to assert on them.
- Mocking a `final` class/method or a static without the corresponding
  mockito-inline / mockStatic support — check what the classpath allows.
- `mockStatic` not closed (must be in try-with-resources or an `@AfterEach`) leaks
  the mock into later tests in the same thread.
- Deep stubs (`RETURNS_DEEP_STUBS`) hiding a Law-of-Demeter problem.
- Mocking a type you do not own (a library class) couples the test to that
  library's internals.

## Assertions

- With AssertJ available, `assertThat(x).isEqualTo(y)` beats `assertEquals` for the
  failure message. Collections: `containsExactly` / `containsExactlyInAnyOrder` —
  be deliberate about whether order is part of the contract.
- Asserting on a whole object with a good `equals` beats field-by-field assertions
  that silently skip the new field.
- Exception tests: `assertThatThrownBy` / `assertThrows` asserting on the **type and
  message/cause**, not just that something threw. A test expecting
  `RuntimeException` passes on an unintended NPE.
- Floating-point compared without a delta; `BigDecimal` compared with `equals`
  (scale-sensitive) instead of `compareTo`.

## JUnit 5 structure

- `@BeforeEach` vs `@BeforeAll`: shared mutable state in a `static` `@BeforeAll`
  fixture couples tests and breaks under parallel execution.
- `@ParameterizedTest` for the cases that are the same shape with different data —
  five copy-pasted tests that differ by one value should be one parameterised test.
- `@Nested` for grouping scenarios around shared setup.
- `@Disabled` with no explanation and no ticket is dead weight; flag it.
- Test execution-order dependence. Tests must pass in any order and in isolation.

## Spring tests (if Spring is a dependency)

- **Slice over full context**: `@WebMvcTest` for a controller, `@DataJpaTest` for a
  repository, plain unit test with constructor injection for a service.
  `@SpringBootTest` for a service test loads the whole application and costs
  minutes across a suite. Raise this on new tests, not existing ones.
- A test using `@SpringBootTest` where a plain JUnit test with a `new` service and
  mock collaborators would do — the constructor-injection payoff.
- `@MockBean` (or `@MockitoBean` on Boot 3.4+) changes the context cache key; each
  distinct combination spins up another application context. A suite with dozens of
  unique mock combinations is slow for this reason.
- `@Transactional` on a test rolls back — which means it does **not** test that the
  transaction actually commits, and it hides constraint violations that only fire
  at flush. If the behaviour under test involves commit semantics, the rollback is
  hiding the bug.
- `@DirtiesContext` used casually destroys the context cache for the whole suite.
- H2 standing in for the production database: dialect differences mean the test can
  pass while the real query fails. If the repo has Testcontainers, a schema-level
  change should be tested against the real engine.
- `MockMvc` tests asserting only the status code, not the response body.
- Security: does the `@WebMvcTest` include the security filter chain, or is it
  testing an endpoint with auth disabled and thereby proving nothing about access
  control?

## Integration tests / Testcontainers (if present)

- Container reused across the class/suite rather than started per test.
- Fixed host ports (collide in CI) instead of mapped ports.
- Test data cleaned up or isolated between tests.
- No `Thread.sleep` for synchronisation — use Awaitility or a proper wait
  condition. Sleep-based tests are the main source of CI flake.

## Flakiness

Flag anything that depends on:

- Wall-clock time, the current date, or a timezone. `LocalDate.now()` in a test
  fails on the one day of the year that matters; inject a `Clock`.
- Iteration order of a `HashMap`/`HashSet`.
- Real network, real filesystem paths, or a real external service.
- Random values without a fixed seed.
- Execution order or leftover state from another test.
