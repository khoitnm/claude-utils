# TypeScript

Applies to any `.ts` / `.tsx` change. First check `tsconfig.json`: if `strict` is
off, `strictNullChecks` findings are a project-level conversation, not a
per-PR comment — raise the pattern once, not fifteen times.

## Escapes from the type system

Each of these turns off checking at a specific point. They are the places bugs
hide.

- **`any`** — new `any` in a signature propagates: everything downstream is
  unchecked. If the shape is genuinely unknown, `unknown` forces a narrowing at the
  boundary, which is the point.
- **`as` assertions** — an assertion is a claim the compiler cannot verify. Ask what
  makes it true. `as SomeType` on a value from an API response is the classic:
  the type says it is safe, nothing checked that it is.
- **`as unknown as T`** — a double assertion exists specifically to defeat the
  compiler's objection. Always worth a comment.
- **Non-null `!`** — asserts something the compiler thinks can be null is not.
  If it can actually be null at runtime, this is a crash with the type system's
  blessing.
- **`@ts-ignore` / `@ts-expect-error`** — needs a comment explaining why.
  `@ts-expect-error` is strictly better than `@ts-ignore` because it errors when
  the underlying problem is fixed.
- **Type predicates (`x is T`)** — the body is unchecked. A predicate whose logic
  does not actually establish `T` lies to every caller.

## Boundaries — where untyped data enters

The type system covers the code, not the data. At every boundary — HTTP response,
`localStorage`, `JSON.parse`, URL params, `postMessage`, env vars, a third-party
callback — the declared type is a hope.

- `await res.json()` is `any`. Assigning it to a typed variable validates nothing.
- If the repo has Zod/Yup/io-ts, new boundaries should be parsed with it. If it
  does not, at least the risk should be acknowledged.
- `process.env.X` is `string | undefined`; treating it as `string` is a runtime
  crash on the environment where it is unset.
- A generic `apiGet<T>()` helper: `T` is asserted, not verified. Not a blocker on
  its own, but do not treat its output as trustworthy.

## Nullability and narrowing

- Optional chaining that silently swallows a real problem: `a?.b?.c` returning
  `undefined` where the caller needed a value produces a blank UI rather than an
  error.
- `??` vs `||`: `||` treats `0`, `""`, and `false` as missing. A default applied
  with `||` to a numeric or boolean prop is a common real bug.
- Narrowing lost across an `await` or a callback boundary — the compiler
  re-widens, and code that "worked" gets a non-null assertion bolted on.
- Optional properties (`field?: T`) vs `field: T | undefined` — the first lets
  callers omit the key entirely; check which the consumers rely on.
- An index access `arr[i]` is typed as `T`, not `T | undefined`, unless
  `noUncheckedIndexedAccess` is on. A loop reading past the end gets `undefined`
  typed as `T`.

## Type design

- **Discriminated unions over optional-field soup.** A type with
  `{ status: string; data?: T; error?: E }` permits states that cannot occur
  (`status: "success"` with no data). A union on a literal `status` makes the
  impossible states unrepresentable and forces exhaustive handling.
- **Exhaustiveness**: a `switch` over a union should have a `never` default so that
  adding a variant becomes a compile error rather than a silent fallthrough. Check
  this specifically when the PR adds a variant to an existing union — the missing
  case is exactly the bug.
- Primitive obsession where a branded type or a union of literals would prevent
  mixing up two `string` IDs.
- `enum` vs a union of string literals — follow the repo's convention; do not start
  a new one.
- Over-generic code: three type parameters and a conditional type where a plain
  interface would do. Complexity in types is paid back by every reader.
- `interface` vs `type` — follow the repo. Not worth a comment on its own.

## React-specific typing

- Props typed as `any` or as an inline object literal that is duplicated at the
  call site.
- `React.FC` — its implicit `children` was removed in React 18 types; whichever the
  repo uses, be consistent. Not worth raising unless it causes a real problem.
- Event handlers typed as `Function` or `any` instead of
  `React.ChangeEvent<HTMLInputElement>` etc.
- `useState` with no initial value infers `undefined` — `useState<T>()` returns
  `T | undefined` and every read needs handling. `useState<T | null>(null)` is
  usually clearer.
- `useRef<T>(null)` gives a read-only ref for DOM nodes; `useRef<T>(null!)` or
  `useRef<T | null>` for mutable ones — mixing them up produces a confusing
  "cannot assign to current" error that people fix with `as any`.
- Generic components losing their type parameter through a `memo` or `forwardRef`
  wrapper.

## Changes that break consumers

- Widening a return type or narrowing a parameter type on an exported function.
- Making an optional prop required.
- Renaming an exported type — a `.d.ts` consumer in another package breaks.
- Removing a union member that consumers switch on.

If the package is consumed by other repos, these are contract changes and belong in
the summary, not just an inline note.
