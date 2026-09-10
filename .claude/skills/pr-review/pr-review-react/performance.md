# React — performance

Apply when the diff touches a list, a large tree, a component that re-renders
often, an expensive computation, an entry point, or assets.

**Only raise a performance finding you can tie to a real cost**: a list that is
large in production, a component in a typing/scroll/drag path, a computation over
a big array, a bundle a user waits on. Speculative memoisation is noise, and it
costs readability.

If the repo has the React Compiler enabled (React 19+), manual `useMemo`/
`useCallback`/`memo` findings are largely obsolete — check before raising them.

## Re-render cost

- **A new object, array, or function created inline in render** and passed to a
  memoised child, a context value, or a hook dependency array defeats the
  memoisation entirely. This is the main reason `React.memo` "does nothing".
- **Context value not memoised** — every consumer re-renders on every provider
  render. See [react-core.md](react-core.md).
- A component subscribing to more state than it uses (`useSelector` over a whole
  slice, `useContext` on a broad context) re-renders on unrelated changes.
- State that lives too high: a text input's value in a top-level component
  re-renders the whole page on every keystroke. Push it down, or isolate the input.
- `useMemo`/`useCallback` **added** in this PR: is the wrapped work actually
  expensive, or is the memo more expensive than the computation? A `useMemo` around
  `a + b` is a net loss. Conversely, a `useMemo` whose dependency array contains an
  inline object never hits.
- `React.memo` on a component that receives `children` as JSX — `children` is a new
  element every render, so the memo never hits.
- Expensive work in the render body rather than in a memo or an event handler.

## Lists

- A long list rendering every row. Ask what the realistic maximum is; above roughly
  a few hundred rows, virtualisation (`react-window`, `@tanstack/react-virtual`,
  or the repo's existing approach) is the right answer.
- Sorting, filtering, or mapping a large array on every render instead of in a memo.
- Index keys causing full re-renders and DOM reuse bugs on reorder — see
  [react-core.md](react-core.md).
- An inline arrow per row (`onClick={() => f(id)}`) is fine for a small list and a
  real cost for a large virtualised one.
- Nested `.find()` inside a `.map()` — O(n²) over the data. Build a lookup map.

## Effects and network

- A dependency array containing an inline object/array so the effect refetches on
  every render — a request storm, and a real production incident when it hits an
  API.
- Waterfalls: dependent queries that could run in parallel.
- Unthrottled/undebounced handlers on `scroll`, `resize`, `mousemove`, or
  search-as-you-type input.
- Missing `AbortController` on a fetch that a fast-typing user triggers repeatedly.
- Polling added with a short interval and no backoff or visibility check — it keeps
  running in a background tab.

## Bundle size

- A new dependency: what does it add, and does the repo already have something that
  does the job? Adding a date library when one is present, or a 300KB chart library
  for one sparkline, is worth a comment.
- Importing a whole library for one function (`import _ from 'lodash'` instead of
  the specific module, or a barrel `index.ts` that pulls in everything).
- A heavy component (editor, chart, PDF viewer, map) loaded eagerly on a route that
  usually does not show it — `React.lazy` + `Suspense`, or the repo's dynamic
  import pattern.
- New route without the code-splitting treatment the other routes have.
- Large static data (a JSON blob, an icon set, a locale bundle) imported at module
  scope.

## Assets and layout

- Images without explicit dimensions cause layout shift; without `loading="lazy"`
  below the fold they block. If the repo uses Next.js, `next/image` handles this.
- Unoptimised image formats/sizes committed to the repo.
- A new web font loaded without a display strategy.
- Animating anything other than `transform` and `opacity` forces layout on every
  frame.
- Reading layout properties (`offsetHeight`, `getBoundingClientRect`) then writing
  styles in the same synchronous block — forced reflow.

## Memory

- Listeners, intervals, observers, or subscriptions without cleanup — a leak that
  compounds across navigations. See [react-core.md](react-core.md).
- Caches or arrays that grow without bound in a long-lived component or module
  scope.
- Closures in a long-lived subscription capturing large objects.

## What not to raise

- `useMemo`/`useCallback` missing on cheap values in components that render rarely.
- Micro-optimisations in code that runs once at startup.
- Virtualising a list that has five items.
- Anything you cannot describe a user-visible or measurable cost for.
