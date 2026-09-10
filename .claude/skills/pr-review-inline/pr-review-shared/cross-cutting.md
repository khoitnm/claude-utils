# Shared: cross-cutting checks (every stack)

Apply these to any PR. They are language-independent; the stack folders cover the
language-specific expressions of the same ideas.

## 1. Does it do what it says?

- Re-read the PR description and the linked ticket. Walk each stated change and
  confirm it is actually in the diff. Half-implemented PRs are common and cheap to
  catch.
- Anything in the diff **not** explained by the description — an unrelated
  refactor, a commented-out block, a config change — call it out. Scope creep in a
  PR is how unreviewed changes ship.
- Debug leftovers: `console.log`, `System.out.println`, `printStackTrace`, `.only`/`@Disabled` on tests,
  hardcoded local URLs, `debugger` statements.

## 2. Error handling and silent failure

The single highest-yield cross-cutting category.

- **Swallowed exceptions** — an empty catch, or one that only logs at `debug`, is a
  bug being hidden. If the caller cannot proceed correctly, the error must
  propagate.
- **Catch too broad** — catching `Exception`/`Throwable`/bare `catch (e)` around a
  block where only one specific failure was anticipated masks the others, including
  programming errors.
- **Fallback that fabricates data** — returning an empty list, `0`, `null`, or a
  default object when the real operation failed makes the failure invisible and
  usually surfaces later as a wrong number in front of a user. A fallback is
  correct only when the caller genuinely does not care whether it worked; say why.
- **Lost context** — rethrowing without the cause, or logging the message without
  the stack trace, makes the production incident unsolvable.
- **Error messages that cannot be acted on** — "Operation failed" with no
  identifier, no operation name, no input.
- **Sensitive data in errors** — tokens, credentials, PHI/PII, full request bodies
  in a log line or an error returned to the client.
- **The unhappy path is untested** — if the PR adds error handling, the tests must
  exercise it. Error paths that were never run once are usually broken.

## 3. Security

- Untrusted input reaching a query, a command, a path, a template, a deserializer,
  or a redirect without validation.
- Authorization checked at the wrong layer, or checked for one entry point and not
  its sibling. Confirm the new endpoint/handler/action is actually covered by the
  existing guard rather than assumed to be.
- Tenancy and ownership: does the new query filter by the caller's tenant/org/user,
  or does it trust an ID from the request?
- Secrets, tokens, connection strings, or keys added to source, config, tests, or
  fixtures.
- New dependency: is it needed, is it maintained, does it duplicate something the
  repo already has, is the version pinned sensibly?
- Logging of credentials, PHI/PII, or full payloads. In a healthcare codebase treat
  PHI exposure as a blocker.

## 4. Concurrency and resource safety

- Shared mutable state reachable from more than one thread/request without
  synchronisation.
- Check-then-act sequences that are not atomic (`if (!exists) create`).
- Resources opened without a guaranteed close — streams, connections, locks,
  subscriptions, timers, listeners.
- Work started but never awaited or cancelled, and what happens if it fails.

## 5. Data and compatibility

- **Backward compatibility**: does this break existing clients, stored data,
  serialized payloads, or persisted enum values? A field rename is a data problem,
  not a code problem.
- **Migrations**: reversible? Safe on a large table? Does the code deploy before or
  after the migration, and does it work in both orders during a rolling deploy?
- **Nullability changes**: a field becoming optional means every read site needs a
  decision.
- **Defaults**: a new field with a default silently changes behaviour for existing
  records.

## 6. Tests

Language-specific depth lives in each stack's `testing.md`. Universally:

- New branching logic with no test covering the new branch is an IMPROVEMENT at
  minimum; new *business* logic with no test is closer to a BLOCKER.
- Tests must assert behaviour, not restate the implementation. A test that would
  still pass with the bug present is worse than no test — it creates false
  confidence.
- Check the test's own arithmetic and boundaries. Off-by-one in the *test* is
  common and makes the test meaningless.
- Error paths, empty inputs, and boundary values, not only the happy path.
- Mocks and fixtures updated to include new fields, so tests exercise realistic data.
- No test that depends on wall-clock time, execution order, network, or a shared
  mutable fixture.

## 7. Observability

- Can you tell from logs/metrics that this code ran and whether it succeeded?
- New failure modes need a signal. Silent degradation is the worst production bug.
- Log levels used correctly: `error` for things needing action, not for expected
  validation failures (that is how alert fatigue starts).
- No logging inside a hot loop.

## 8. Comments and docs

- A comment that contradicts the code it sits on is a defect — one of them is wrong,
  and the reader will trust the wrong one.
- Comments should explain **why**, not restate **what**. `// increment i` earns a
  deletion suggestion.
- Public API changes need their doc comment updated in the same PR.
- A stale comment left above changed code is a real finding, not a nitpick, when it
  now describes behaviour that no longer exists.

## 9. Dead code and cleanup

- Removed function/constant/flag: every reference gone, including strings, config,
  and docs?
- Newly unreachable branches, unused parameters, unused imports, orphaned tests.
- Feature flags: is there a removal plan, or is this permanent branching?
