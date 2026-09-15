# explain

Explains one thing in a way a junior developer can follow, without turning it into a document
nobody reads. Every point is one to three sentences.

## Install

This repo doubles as a marketplace, so there is nothing to copy or link. From a shell at the repo
root:

```bash
claude plugin marketplace add ./
claude plugin install explain@claude-utils
```

Or from inside a session, with `/plugin marketplace add ./` and `/plugin install explain@claude-utils`.
The source must be a path the resolver accepts — `./` or `./some/dir`, not a bare `C:\...`.

## Use

```
/explain:explain-concise OrderSyncService
/explain:explain-concise why does this test fail intermittently
/explain:explain-concise PR 1482
/explain:explain-concise what is optimistic locking
```

Typing `/explain` and picking from the completion list works too. The skill also fires on its own
when you ask Claude to explain, walk through, break down, or clarify something.

Give it a target: a file, a class, an error, a pull request, a diff, a design, or a term. With no
target, it asks one question instead of guessing.

## What comes back

```markdown
## Summary
Two or three sentences: what it is, what job it does, the one fact that matters most.

## Explain body

### Context
Where it sits and why it exists. A small diagram when the shape is hard to picture.

### Concepts
Only the ideas needed to follow the rest, one sentence of definition each.

### Challenges
The real problems, and what breaks if they are not handled.

### Solutions
How each challenge is handled, in the same order, pointing at the code.

### Pros and cons
What the approach buys and what it costs. The costs are never left out.
```

A section is dropped when it does not apply — a vocabulary question has no challenges.

## Writing rules it follows

- Short sentences, one idea each.
- Every sentence has a subject and a verb, bullets included.
- Every abbreviation and specialized term is spelled out the first time it appears.
- Ordinary words over jargon: "use", not "leverage".
- Real class names, endpoints, and numbers instead of vague description.
- Nothing is guessed. If a detail could not be confirmed, it says so in one line.

Diagrams are plain text in the terminal, because the terminal does not render Mermaid, and Mermaid
in files that get rendered.

## Layout

```
plugins/explain/
  .claude-plugin/plugin.json
  skills/explain-concise/
    SKILL.md                      the process and the output structure
    references/writing-style.md   sentence, word, and brevity rules
    references/diagrams.md        when to draw one, and the formats
```
