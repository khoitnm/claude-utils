# Shared: severity, finding format, and the summary

## Severity levels

| Level | Meaning | Bar for using it |
| --- | --- | --- |
| **BLOCKER** | Merging this ships a defect. | You can name the input or state that triggers it and the wrong result. Data loss, security hole, crash, wrong output, broken contract, leaked resource, race. |
| **IMPROVEMENT** | Should be fixed, but not merge-blocking. | Real maintainability or correctness-adjacent cost: missing test for new branching logic, duplicated logic that will drift, unclear error handling, missing index on a new hot query. |
| **NITPICK** | Optional. Style, naming, preference. | Use sparingly. More than three nitpicks in a review means you are padding. |
| **QUESTION** | You genuinely cannot tell from the diff. | Ask it as a question, not as a disguised assertion. |
| **PRAISE** | A non-obvious good decision. | At most one or two, and only when they teach something. Skip the participation trophies. |

Severity is about consequence, not confidence. A definite typo in a log message is
still a nitpick; a race condition you are 70% sure about is still a blocker — say
you are 70% sure.

## The bar for reporting anything

Before you write a finding, answer all three:

1. **What input or state triggers it?** If you cannot say, it is not a finding.
2. **What is the wrong result?** "This is fragile" is not a result.
3. **Did I check the code that would make me wrong?** The caller, the test, the
   annotation on the class, the framework default. Most plausible findings die here.

Delete anything that fails this. An unverified finding costs the author more time
than it saves — they have to disprove it.

## Finding format (each inline comment)

```
**BLOCKER — Null `customerId` reaches the cache key**

`resolveTenant()` returns `null` for unauthenticated requests (see
`TenantResolver.java:88`), so a logged-out request builds the key `"quote:null"`
and every anonymous user shares one cache entry.

Suggested fix: reject the request before caching, or scope anonymous lookups to a
separate keyspace.
```

Rules:

- One finding per comment. Two problems on one line means two comments.
- Lead with the severity and a one-line claim. Reviewers skim.
- Give evidence: the file and line that proves it, not just an assertion.
- Suggest a direction, not a rewrite. Use GitHub's ```suggestion blocks only for
  changes that are genuinely one or two lines and unambiguous.
- No preamble, no "Great work but...". Say the thing.
- Comment must be concise, short and simple, easy for even junior developer can understand.

## Summary body (posted once, as the review body)

```markdown
## Review summary

**Stack detected:** Java 17 / Spring Boot 3.2 / Spring Data JPA / JUnit 5 + Mockito
**Scope:** 12 files, +430 / -88. Checklists applied: correctness, persistence, API contracts, testing, security.

**Recommendation: Request changes** — 2 blockers.

| # | Severity | Finding | Location |
| --- | --- | --- | --- |
| 1 | BLOCKER | Anonymous requests share one cache entry | `QuoteService.java:142` |
| 2 | BLOCKER | `@Transactional` on a private method is a no-op | `LedgerService.java:57` |
| 3 | IMPROVEMENT | New `status` branch has no test | `OrderMapper.java:31` |

### What this PR gets right
One or two sentences, only if there is something real.

### Not reviewed
Anything you deliberately skipped, and why (generated files, an area needing
domain knowledge you lack).
```

For a re-review, add:

```markdown
### Previously raised
| Finding | Status |
| --- | --- |
| Cache key missing tenant scope | Fixed |
| Missing test for the retry path | Not addressed |
```

## The recommendation

One of:

- **Approve** — no blockers, nothing meaningful outstanding.
- **Approve with suggestions** — no blockers, improvements worth doing.
- **Request changes** — at least one blocker.

State it in the summary body. Do **not** encode it in the GitHub review `event`
unless the user explicitly asked you to approve or request changes on their
behalf — see `github-review.md`.

## Calibration

A good review of a 300-line PR is typically 3–8 findings. If you have 25, you are
reviewing style; re-read the bar above and cut. If you have zero, say so plainly
and state what you checked — "no findings" from a review that names its coverage is
useful; "LGTM" is not.
