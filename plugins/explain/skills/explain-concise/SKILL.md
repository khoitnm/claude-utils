---
name: explain-concise
description: Explain a topic briefly so a junior developer can follow it — a short summary, then context, concepts, challenges, solutions, and pros and cons, at one to three sentences each. Use when asked to explain, walk through, break down, teach, or clarify some code, a design, a bug, a pull request, an error, or a technical term.
allowed-tools: Read, Grep, Glob, Bash, WebFetch, WebSearch, ToolSearch
---

# explain-concise

Explain one thing briefly. The reader is a developer with about a year of experience: they can read
code, but they have not seen this part of the system and do not know the team's shorthand.

Three rules sit above everything else:

1. **Be brief.** Every item below is one to three sentences. Nothing is exempt.
2. **Never guess.** Read the code, the logs, or the docs first. An invented detail is worse than a
   missing one, because the reader cannot tell which parts are real.
3. **Explain what was asked.** Do not widen the topic into a tour of the system.

## Step 1 — Find the topic

| The user points at | Do this first |
| --- | --- |
| A file, function, or class | Read it, plus its callers and what it calls |
| A concept or term | Explain from knowledge; check how *this* repo uses it |
| A bug, error, or stack trace | Read the failing code and its call path |
| A pull request or a diff | Read the changed files, not just the diff lines |
| A design or architecture | Read the entry points, the configuration, and the boundaries |
| Nothing specific | Ask one short question: "What would you like me to explain?" |

Read enough to be accurate, then stop. If something matters but you could not confirm it, say so in
one line instead of filling the gap.

## Step 2 — Write it

Use exactly these headings:

```markdown
## Summary

## Explain body

### Context

### Concepts

### Challenges

### Solutions

### Pros and cons
```

**Summary** — two or three sentences. Say what the thing is, what job it does, and the one fact that
matters most. A reader who stops here must not be misled.

**Explain body** — the sections below. In each one, write short bullets, and keep **every bullet to
one sentence, three at the very most**. Three or four bullets per section is plenty; if you have
more, you are explaining too much.

- **Context** — where this sits and why it exists. Add a diagram only when the shape is hard to hold
  in your head; see `references/diagrams.md`, and keep it small.
- **Concepts** — only the ideas needed to follow the rest. One sentence of definition each, ordered
  so no concept depends on a later one. Skip what a junior developer already knows.
- **Challenges** — the real problems or constraints. Name the problem and what breaks if it is not
  handled. Skip invented ones like "the code had to be maintainable".
- **Solutions** — how each challenge is handled, in the same order. Name the mechanism, point at the
  code, and define any new term on the spot.
- **Pros and cons** — what the approach buys and what it costs, as two short lists or a small table.
  State consequences, not opinions. Always include the costs.

Skip a section only when it truly does not apply — a vocabulary question has no challenges. Drop the
heading too; never leave one empty.

## Step 3 — Check the writing

Apply `references/writing-style.md`. The short version:

- Short sentences, one idea each.
- Every sentence has a subject and a verb, including bullets and table cells.
- Spell out each abbreviation and specialized term the first time it appears: "Java Virtual Machine
  (JVM)", "idempotent — running it twice has the same effect as running it once".
- Use the ordinary word: "use", not "leverage"; "fast", not "performant".
- Name the real class, endpoint, or number instead of describing it vaguely.
- Cut filler: "it is important to note that", "basically", "simply", "obviously".

Then cut the draft again. Delete any sentence the reader could skip without losing the point.

## Where it goes

Answer in the conversation by default, and use plain-text diagrams there, because the terminal does
not render Mermaid. Write a file only when the user asks for one or wants something kept; then use
Mermaid, and ask where to put it if they did not say.
