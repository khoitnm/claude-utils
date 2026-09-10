# React / TypeScript — testing

Apply when the diff changes a test file, **or** adds component/hook logic without
one. Match the idioms to the runner and libraries in `package.json` (Jest vs
Vitest, RTL, MSW, Playwright/Cypress).

## Coverage of the change

- Every new branch and conditional render path — loading, empty, error, success,
  permission-denied. The error and empty states are the ones that ship broken.
- **Would the test fail without the fix?** For a bug fix, the regression test must
  fail against the old code. If it would have passed, it is not a regression test.
- New user-facing behaviour tested through the user's actions, not by calling the
  handler directly.
- A new hook: tested through a component that uses it, or with the repo's
  hook-testing utility — and covering its cleanup, not just its happy path.
- Boundaries: empty list, one item, many items, long strings, missing optional
  fields.

## Testing Library idioms

- **Query priority**: `getByRole` (with an accessible name) > `getByLabelText` >
  `getByPlaceholderText` > `getByText` > `getByTestId`. A new `data-testid` where a
  role query would work is a missed accessibility check — a role query that fails
  tells you the markup is not accessible, which is exactly the feedback you want.
- `getBy*` throws if absent (use to assert presence), `queryBy*` returns null (the
  only correct choice for asserting **absence**), `findBy*` is async (the correct
  choice for anything that appears later). `expect(getByText(...)).toBeNull()` can
  never pass — it throws first. Worth checking for; it appears regularly.
- **`userEvent` over `fireEvent`.** `fireEvent.change` on an input skips focus,
  keydown, and the browser behaviours the component may depend on. `userEvent` in
  v14+ is async and must be awaited — a missing `await` produces a test that
  asserts before the interaction completes and passes for the wrong reason.
- `waitFor` should contain **one assertion** and no side effects — it retries the
  callback, so a `userEvent` call inside it runs repeatedly.
- Never `waitFor` an arbitrary timeout or `setTimeout` a test into passing. Wait
  for the condition.
- `act()` warnings suppressed rather than fixed usually mean a state update the
  test does not know about — often a real bug (an effect updating state after
  unmount).
- Asserting on implementation: querying by CSS class, snapshotting internal state,
  reaching into instance methods. A test coupled to the DOM structure breaks on
  every refactor and catches no bugs.
- **Large snapshot tests** are near-worthless: nobody reviews a 400-line snapshot
  diff, so they get updated blindly. Small, focused snapshots or explicit
  assertions instead. If a PR updates a snapshot, check whether the change in it is
  actually intended — a snapshot update hiding a regression is a common finding.

## Mocking

- **Mock at the network boundary** (MSW) rather than mocking the fetching hook or
  the module. Mocking `useQuery` tests that your mock returns what you told it to.
- Mocks reset between tests (`clearMocks`/`restoreMocks` in config, or explicit
  `beforeEach`). Leaked mock state makes tests order-dependent.
- Mocking a child component to avoid dealing with it hides integration bugs; do it
  only for genuinely heavy or environment-dependent children (a map, a chart, a
  canvas).
- Over-mocked tests that pass while the app is broken. If the setup is longer than
  the assertions, that is the signal.
- Fake timers: used consistently, advanced explicitly, and restored afterwards.
  Mixing fake timers with `userEvent` needs the `advanceTimers` option or the test
  hangs.
- A fixed date/timezone for anything date-dependent — otherwise the test fails at a
  month boundary or in CI's timezone.

## Async and flake

Flag any test that depends on:

- A real timer, a sleep, or a fixed delay.
- Network, real time, `Math.random`, or `Date.now()` without control.
- Execution order, or state left by another test.
- Animation completion.
- The specific number of renders.

These are the tests that will be `.skip`ped in six months.

## Assertions

- `toBeInTheDocument` / `toBeVisible` / `toHaveAccessibleName` from jest-dom rather
  than `expect(el).toBeTruthy()`.
- Asserting the visible text or state the user perceives, not the props passed.
- `toEqual` vs `toStrictEqual` — `toEqual` ignores `undefined` properties, which
  can hide a missing field.
- A test with no assertion, or one whose assertion cannot fail.

## E2E (if Playwright / Cypress is present)

- Reserved for critical user journeys. A PR adding ten E2E tests for unit-level
  logic is adding CI time and flake.
- Selectors that are stable (role or a dedicated test id), not CSS chains.
- Auto-waiting used rather than fixed waits.
- Test data set up and torn down; tests independent and parallel-safe.

## Structure

- Test name states the scenario and the expected outcome.
- One behaviour per test.
- No logic (`if`/loops) in test bodies.
- `describe` grouping that matches the component's states rather than its methods.
- `.only` or `.skip` left in the diff — always a finding. `.only` silently disables
  every other test in the file, and CI usually will not notice.
