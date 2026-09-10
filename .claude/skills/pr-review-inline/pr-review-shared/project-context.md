# Shared: pulling in the reviewed repo's own context

Read these **only when the diff makes them relevant**. Loading every doc in the
repo before reviewing a 40-line change wastes context and buries the actual review.

## Always cheap, always worth it

**Do not assume the conventions live in a root `CLAUDE.md`.** Half the repos that
have house rules keep them somewhere else, and a review that missed them reads as
generic. Run one `ls` before deciding the repo has no conventions:

```bash
ls CLAUDE.md AGENTS.md .claude/CLAUDE.md 2>/dev/null
ls .claude/rules .claude/skills docs 2>/dev/null
```

**Run those in the reviewed repo, not the one you happen to be sitting in.** This
skill may be invoked from a different checkout than the PR belongs to. If the
reviewed repo is checked out locally, `cd` to it (or prefix the paths) before
looking; if it is not, read the same files through
`get_file_contents` / `gh api ... /contents/<path>` at the PR's base ref. Reviewing
a PR with the *reviewing* repo's conventions is worse than reviewing it with none.

| Source | Why |
| --- | --- |
| `CLAUDE.md` / `AGENTS.md` at the repo root, **or** `.claude/CLAUDE.md` | The project's own conventions. Either location is normal; check both. A finding that contradicts it is wrong; a violation of it is a legitimate finding, and citing the rule makes it uncontestable. |
| Files that CLAUDE.md `@`-imports | A line like `@docs/naming-convention.md` or `@docs/caching/in-memory-dataset-caches.md` is part of the instructions, not a reading suggestion. Follow the ones whose subject the diff touches — that is usually where the real, hard-won rules are. |
| `.claude/rules/**` | A common convention for path-scoped rules (`paths:` frontmatter listing globs such as `sc-api/src/**`). Read every rule file whose globs match a changed file. These are frequently more specific and more binding than CLAUDE.md itself. |
| Nested `CLAUDE.md` in a changed directory or module | Module-specific rules override root ones. |
| `README.md` of the changed module | Tells you what the module is for, which is what "correct" means here. |

In a multi-module repo, resolve these per changed file, the same way
[`stack-detection.md`](stack-detection.md) resolves manifests: the rules that apply
to `sc-api/src/**` may say nothing about a change under `sc-app/src/**`.

## Read when the diff meets the condition

| Condition in the diff | Also read |
| --- | --- |
| A new public API, endpoint, or event is added | The repo's API/contract docs, OpenAPI spec, or `docs/api/**` — check the code matches the published contract. |
| The change alters a module boundary, adds a dependency between layers, or introduces a new service call | Architecture docs (`docs/architecture/**`, ADRs in `docs/adr/**`, `*.arch.md`). A layering violation is a blocker only if an ADR says so; otherwise it is a discussion. |
| The PR body links a ticket (Jira, Aha, GitHub issue) | Fetch it. The single most valuable check in review is *does this actually do what was asked* — you cannot answer that without the requirement. Use the issue tools for GitHub issues; ask the user for anything behind a system you cannot reach. |
| The PR touches auth, permissions, PHI/PII, audit, or tenancy | The repo's security or data-handling docs. In a healthcare codebase, mishandled PHI is a blocker, not a nitpick. |
| The repo has `.claude/skills/**` covering the changed area | Read the relevant skill. It encodes how this team wants that area written, and it is the cheapest source of house style. |
| The repo has a doc on the *aspect* the diff touches — caching, concurrency, tenancy, migrations, error handling (`docs/caching/**`, `docs/adr/**`, a `*-rules.md`) | Read it before applying the matching checklist from this skill, and see "When the repo has its own doc on the aspect" below. |
| The change modifies a shared library consumed by other repos | Check for a consumer list or a compatibility policy before calling a breaking change acceptable. |

## Do not read

- The whole `docs/` tree "for context".
- Architecture docs for a bug fix inside one method.
- Requirements for a dependency bump or a typo fix.

## Precedence when sources conflict

1. An explicit instruction in the PR description or from the user for this review.
2. The repo's `CLAUDE.md` / skills / ADRs.
3. The surrounding code's established pattern.
4. General best practice from these checklists.

If a checklist item here conflicts with the repo's own documented convention, the
repo wins — and say so rather than silently dropping the item, because a convention
that produces bad code is itself worth one comment (once, in the summary, not on
every occurrence).

Two conflicts that show up constantly, both worth checking before you write a
Java finding:

- The repo bans a construct this skill would otherwise suggest — `var`, records,
  JPA relationship mappings, Lombok, field injection. **Where a repo bans a
  construct, the finding is the ban, not the tuning advice.** Do not suggest
  `LAZY` + `JOIN FETCH` in a repo whose rules say "never map associations"; the
  finding there is "this adds a mapped association, which
  `.claude/rules/...` forbids — use a scalar id and a projection".
- The repo's testing rules and this skill's testing advice disagree about
  interaction assertions (`verify(times(1))` vs "assert on data, not on calls").
  Follow the repo — but note that a call-count assertion is sometimes the *only*
  thing that can express the requirement (one query for a burst of readers, one
  load per key). If the repo's own docs carve that exception out, cite the carve-out.

## When the repo has its own doc on the aspect

A repo doc about caching, concurrency, tenancy, or migrations beats these
checklists on its own subject. It knows the class names, the incidents, and the
constraints; this skill knows only the general shape.

1. Read the repo's doc **first**, and treat it as the specification.
2. Where the two disagree, the repo's doc wins — including when it forbids
   something this skill calls mandatory, or permits something this skill calls a
   blocker. Assume the repo doc's exception is deliberate unless the diff shows the
   author did not know about it.
3. Use these checklists only for what the repo's doc does not cover.
4. Cite the repo's doc in the finding (`docs/caching/in-memory-dataset-caches.md`
   §4), not this skill. A finding anchored to the team's own document does not get
   argued with.
5. If the diff clearly violates that doc, say which section. If the diff reveals a
   gap in the doc, say that once in the summary — updating it is often the more
   valuable follow-up than the code comment.
