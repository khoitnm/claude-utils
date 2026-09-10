# React / TypeScript review — dispatch index

Read this table, then read **only** the files whose condition the diff actually
meets.

Every file is gated on what
[`../pr-review-shared/stack-detection.md`](../pr-review-shared/stack-detection.md)
found in `package.json` and `tsconfig.json`. Skip any section whose library is not
a dependency of this repo.

| Read this | When the diff… |
| --- | --- |
| **[react-core.md](react-core.md)** | Touches any component, hook, or `.tsx` file. Always applies to React changes. Hook rules, effects, state, keys, refs, context, error boundaries, styling. |
| **[typescript.md](typescript.md)** | Touches any `.ts`/`.tsx`. Type soundness, `any`, assertions, narrowing, generics, discriminated unions, props typing. |
| **[state-and-data.md](state-and-data.md)** | Touches data fetching, caching, a global store, forms, routing, or URL state. Covers React Query/SWR/Apollo, Redux/Zustand/Jotai, react-hook-form/Formik/Zod. |
| **[accessibility.md](accessibility.md)** | Adds or changes rendered markup, an interactive control, a modal/menu/tooltip, a form, an icon-only button, or anything driven by color. |
| **[performance.md](performance.md)** | Touches a list, a large component tree, a frequently re-rendering component, an expensive computation, a bundle entry point, or an image/asset. |
| **[security.md](security.md)** | Touches HTML injection, URLs, tokens/storage, auth state, external links, user-supplied content, or dependency versions. |
| **[testing.md](testing.md)** | Touches any test file, **or** adds component/hook logic with no accompanying test. |

Also always apply
[`../pr-review-shared/cross-cutting.md`](../pr-review-shared/cross-cutting.md).

For repo conventions, design-system rules, architecture, and requirements, follow
[`../pr-review-shared/project-context.md`](../pr-review-shared/project-context.md).

## Version and tooling gating

Before raising a finding that depends on a version or a tool:

| Do not raise | Unless |
| --- | --- |
| `useTransition`, `useDeferredValue`, `useId`, automatic batching | React 18+ |
| Actions, `useActionState`, `useOptimistic`, `use()`, ref-as-prop, the compiler making manual memo unnecessary | React 19+ |
| Server/client component boundaries, `"use client"`, route caching | Next.js App Router is in use |
| `React.FC` / `key` / hook-dependency findings the linter already reports | `eslint-plugin-react-hooks` is **not** configured, or CI is not running it |
| a11y findings | `eslint-plugin-jsx-a11y` does not already cover the specific rule |
| Formatting and import order | Prettier/Biome/ESLint is not enforcing it in CI |

If the repo's linters pass in `get_check_runs`, spend the review on what a linter
cannot see: wrong data, wrong lifecycle, wrong contract.

**Where the repo has its own rules or its own doc on one of these aspects, that
document wins over the file here, and the finding should cite it.** Look for
`CLAUDE.md`, `.claude/CLAUDE.md`, `.claude/rules/**` whose `paths:` globs match a
changed file (frontend rules are commonly scoped that way), custom ESLint rules in
the repo, and any doc CLAUDE.md `@`-imports. See
[`../pr-review-shared/project-context.md`](../pr-review-shared/project-context.md).
