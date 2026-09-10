# React — components, hooks, and rendering

Applies to any component or hook change.

## Hook rules

- Hooks called unconditionally, at the top level — never inside an `if`, a loop, an
  early return, or a nested function. A hook after an early return changes the hook
  order between renders and corrupts state. `eslint-plugin-react-hooks` catches
  most of this; check whether it is actually configured before spending a comment.
- A custom hook must itself follow the rules and be named `useX`.

## `useEffect` — the highest-yield section

Most effect bugs come from using an effect where none is needed.

- **Effects that should not exist.** An effect that only derives state from props
  or other state should be a plain computed value during render. The
  `useState` + `useEffect(() => setB(f(a)), [a])` pattern renders twice, can flash
  the stale value, and drifts out of sync.
- **Missing dependencies.** A dependency array that omits a value the effect reads
  captures a stale closure — the effect runs with an old value and the bug is
  intermittent. Suppressing the lint rule with a comment is a finding unless the
  comment explains why.
- **Over-broad dependencies.** An object, array, or inline function in the deps is
  a new reference every render, so the effect runs every render. Common cause of
  infinite loops and request storms. Fix by depending on primitives, or memoising
  the value.
- **No cleanup.** Every subscription, event listener, `setInterval`/`setTimeout`,
  `AbortController`, observer, or websocket opened in an effect must be torn down in
  the returned function. Otherwise: leaks, duplicated handlers after remount, and
  under React 18 StrictMode double-invocation, doubled side effects.
- **Race conditions in async effects.** Two fetches in flight, the slower one
  resolves last and overwrites the newer data. Needs an `AbortController` or an
  `ignore` flag checked before `setState`.
- **`setState` on an unmounted component** after an await — same fix as above.
- **Effects that write to the DOM or scroll during paint** should usually be
  `useLayoutEffect` (or the flicker is the bug).
- An effect with an empty dep array that reads props — it will never see updates.

## State

- **Derived state stored in `useState`.** If it can be computed from existing state
  or props, compute it. Duplicated state goes stale.
- **State that should be a ref**: a value that changes but must not trigger a
  re-render (a timer id, a previous value, a mutable instance).
- **Stale-closure updates**: `setCount(count + 1)` twice in one handler increments
  once. Use the updater form `setCount(c => c + 1)` whenever the next value depends
  on the previous.
- **Mutating state directly**: `arr.push(x); setArr(arr)` does not re-render because
  the reference is unchanged. Same for `obj.field = x`. (Unless the repo uses
  Immer/RTK, where mutation inside a producer is correct.)
- **Deeply nested state objects** where a shallow spread misses a level, so an
  update silently drops fields.
- State lifted higher than needed re-renders a whole subtree; state duplicated in
  two places will disagree.
- **`key` to reset state**: when a component needs to fully reset on identity
  change, changing its `key` is the idiomatic fix — better than an effect that
  resets fields.
- Initial state computed by an expensive call: `useState(expensive())` runs every
  render; `useState(() => expensive())` runs once.

## Lists and keys

- **`key` must be stable and unique among siblings.** Array index as a key is a real
  bug when the list can reorder, filter, or have items inserted/removed: React
  reuses the wrong DOM node, and uncontrolled input values, focus, and animation
  state attach to the wrong row.
- `key={Math.random()}` remounts every item on every render.
- Keys on the outermost element of the mapped item, including inside a `Fragment`
  (`<React.Fragment key=...>`, not `<>`).

## Props and component contracts

- New required prop added to a shared component: every call site updated? Grep for
  the component name, including lazy/dynamic usages.
- A prop's meaning changed while the name stayed — check every consumer.
- Boolean props that are mutually exclusive; a union or a variant string is clearer
  than four booleans that can contradict.
- Passing an inline object/array/function as a prop to a memoised child defeats the
  memo. See [performance.md](performance.md).
- Spreading `{...props}` onto a DOM element passes unknown attributes through to
  the DOM and produces React warnings — and can leak internal props into HTML.
- Components that take a callback should not also manage the state that callback
  changes; pick controlled or uncontrolled and be consistent. A component that is
  controlled sometimes and not others (a `value` prop that can go from defined to
  `undefined`) triggers React's controlled/uncontrolled warning and loses input.

## Conditional rendering

- `{count && <Thing/>}` renders a literal `0` when count is 0. Use
  `{count > 0 && ...}` or a ternary. This is a genuine visible-bug finding, not a
  nitpick.
- `{items.length && ...}` — same problem.
- A ternary chain three levels deep is unreadable; suggest extracting.

## Refs

- Reading `ref.current` during render (it may not be attached yet, and it is not
  reactive).
- `useRef` used where state is needed — changing a ref does not re-render.
- Callback refs that are inline arrow functions get called with `null` then the node
  on every render; memoise if the callback does real work.
- `forwardRef` needed for a shared component that consumers must attach a ref to
  (React 19 allows `ref` as a plain prop — check the version).

## Context

- A context `value` built inline (`value={{ user, setUser }}`) is a new object every
  render, so **every consumer re-renders** regardless of memoisation. Memoise it.
- A context carrying both frequently-changing and stable data causes unnecessary
  re-renders across the app; splitting contexts is the usual fix.
- A consumer with no provider above it gets the default value — often `undefined`,
  which then throws on property access. A custom hook that throws a clear error is
  the standard guard.

## Error and loading states

- A component that fetches must handle **loading, empty, and error** states, not
  just success. An "empty" state that is indistinguishable from "still loading" is
  a UX bug.
- An error boundary above anything that can throw during render. Note that error
  boundaries do **not** catch errors in event handlers, async code, or effects
  cleanup — those need their own handling.
- A `catch` in a component that just logs and renders nothing leaves the user
  staring at a blank area with no idea what happened.

## Styling (gate on what the repo uses)

- Consistency with the repo's approach — do not introduce inline styles into a
  Tailwind codebase or a fourth styling system into a project that has three.
- CSS Modules / styled-components: no global selector leaking out of a component.
- `styled` components defined **inside** a render function are recreated every
  render, remounting the DOM subtree and losing state. A real bug.
- Hardcoded colors, spacing, or breakpoints where the design system exposes tokens.
- `z-index` chosen ad hoc rather than from the scale.
- New fixed pixel widths that break at small viewports, or that assume a font size.
- Dark mode / theme support if the repo has it.

## Cleanliness

- Commented-out JSX, unused props left in the signature, `console.log`.
- A component that has grown past a few hundred lines with multiple
  responsibilities — one comment suggesting the split, not a redesign demand.
