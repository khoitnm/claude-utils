# Writing style

The reader is a developer with about a year of experience. They do
not know this system, and they do not know the team's shorthand.

## Brevity

- One to three sentences per bullet, and three or four bullets per section. That is the whole budget.
- Delete any sentence the reader could skip without losing the point.
- Do not restate the heading in the first sentence under it, and do not describe the document
  ("this section will cover...").
- Say the thing once. A point made twice in different words is one point and one waste of a line.

## Sentences

**One idea per sentence.** If a sentence has two "and"s or a "which" in the middle, split it or cut
half of it.

**Every sentence needs a subject and a verb**, including bullets and table cells.

| Do not write | Write |
| --- | --- |
| Retry logic for failed calls. | The client retries a call that fails. |
| Faster, less memory. | The new version runs twice as fast and uses half the memory. |
| Because of thread safety. | `HashMap` is not thread safe, so two threads writing at once corrupt it. |

**Say who does what.** Use the active voice: "the scheduler calls the service", not "the service is
called". Keep sentences under about twenty-five words.

## Words

**Spell out every abbreviation the first time it appears**, then use the short form: "Java Virtual
Machine (JVM)", "Cross-Site Request Forgery (CSRF)", "Continuous Integration (CI)". Do this even for
ones that feel universal on your team.

**Define a specialized term where it first appears**, in the same sentence, after a dash:

- "The operation is *idempotent* — running it twice has the same effect as running it once."
- "The call is *blocking* — the thread waits and does nothing else until the answer arrives."

**Prefer the ordinary word.**

| Jargon | Plain |
| --- | --- |
| leverage, utilize | use |
| instantiate | create |
| performant | fast |
| orchestrate | coordinate |
| non-trivial | hard, or say how hard |
| in order to | to |

Keep a term when it is the real name of the thing. A `HashMap` is a `HashMap`; explain it, do not
rename it.

**Be concrete.** "It times out after 30 seconds" beats "it has a configurable timeout".

## Cut these

- Filler openers: "It is important to note that", "Basically", "At a high level".
- Flattery: "elegant", "robust", "seamless", "powerful".
- Words that hide difficulty: "simply", "just", "obviously". If it were obvious, nobody would ask.

## Formatting

- Put code, file names, class names, and configuration keys in backticks.
- Cite a location as `path/to/file.java:42` so the reader can open it.
- Use a table only when comparing things on the same points.
- Show a snippet only when the code itself is the point, and keep it to the few lines that matter.
- Use an analogy only when a concept has no everyday equivalent. Keep it to one sentence and say
  where it breaks down.

## The final pass

Reread the draft as the junior developer. Fix the first sentence where they would stop and ask "what
does that mean?". Then look for the longest paragraph and shorten it.
