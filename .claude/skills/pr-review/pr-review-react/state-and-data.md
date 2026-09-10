# React — data fetching, global state, forms, routing

Apply only the subsections whose library `package.json` actually contains.

## The server-state / client-state line

The most consequential architectural check in a frontend PR.

- Server data (anything fetched) copied into `useState` or a Redux slice needs
  manual cache invalidation, loading flags, and error handling — all of which the
  repo's query library already does. If the repo has React Query/SWR/Apollo and
  this PR fetches into `useState` + `useEffect` instead, say so.
- Conversely, pure UI state (a modal's open flag, a form draft) put into the server
  cache or a global store is over-engineering.

## React Query / TanStack Query (if `@tanstack/react-query`)

- **Query key completeness.** The key must contain every input the result depends
  on — id, filters, pagination, sort, **and the user/tenant/locale if the response
  varies by them**. A key missing a variable serves one user's data to another from
  the cache. That is a blocker, not a caching nitpick.
- Key structure consistent with the repo's convention (a key factory if one
  exists) — ad-hoc keys break invalidation because the invalidator no longer
  matches.
- **Invalidation after mutation**: which queries hold data this mutation changed?
  Missing an `invalidateQueries` shows as stale data on screen. Find every affected
  key, not just the obvious one.
- Optimistic updates need a rollback in `onError` and a settle/invalidate in
  `onSettled`, or a failed mutation leaves the UI showing a change that did not
  happen.
- `enabled` guard on a query whose parameter can be undefined — otherwise it fires
  with `undefined` in the URL.
- `staleTime` / `gcTime` chosen deliberately. The default `staleTime: 0` refetches
  on every mount and focus; for expensive or rarely-changing data that is a real
  load problem.
- Errors surfaced to the user, not just left in `isError` and ignored.
- Mutations that should be idempotent or debounced — a double-click submits twice.
- `useQueries` / dependent queries creating a waterfall where parallel would do.

## SWR / Apollo (if present)

- SWR: the key is the cache identity — same completeness rules as above. `mutate`
  scope after a write.
- Apollo: cache normalization needs an `id`/`__typename`; a query result missing
  them silently fails to update other views. `fetchPolicy` chosen deliberately.
  After a mutation, either `refetchQueries` or an explicit cache update — missing
  both leaves stale UI.

## Redux / Redux Toolkit (if present)

- Reducers must be pure: no I/O, no `Date.now()`, no `Math.random()`, no mutation
  outside an RTK/Immer producer.
- Non-serializable values (Dates, Maps, class instances, functions, Promises) in
  the store break persistence, devtools, and time travel.
- **Selectors returning a new reference every call** (`.filter()`, `.map()`, an
  object literal) make `useSelector` re-render on every store change anywhere.
  Memoise with `createSelector`, or select primitives.
- `useSelector(state => state.someSlice)` subscribes to the whole slice; select the
  narrowest value needed.
- Business logic in a component that belongs in a thunk, or vice versa —
  consistency with the repo matters more than the rule.
- State shape duplicated across slices, so two places disagree.
- If the repo uses RTK Query, the query-key/invalidation rules above apply via
  `providesTags` / `invalidatesTags` — a mutation with no `invalidatesTags` is the
  same stale-data bug.

## Zustand / Jotai / MobX (if present)

- Zustand: selecting the whole store instead of a slice re-renders on every change;
  a selector returning a new object needs a shallow comparator.
- Actions mutating state outside the store's prescribed mechanism.
- Jotai: atoms created inside a component are recreated every render.
- MobX: observable state mutated outside an action; a component reading observables
  without `observer` never updates.

## Forms (if `react-hook-form` / `formik` / a validation library)

- **Validation on both sides.** Client validation is UX; the server must validate
  too. A PR that adds only client validation for a security-relevant constraint is
  a finding.
- The schema matches the API's actual contract — field names, required-ness, and
  limits. A `maxLength` looser than the database column produces a 500 on submit.
- Error messages shown next to the field, associated with it for screen readers
  (see [accessibility.md](accessibility.md)).
- Submit disabled or guarded while in flight — otherwise double submission.
- Server-side errors mapped back onto the right fields, not just a toast.
- Controlled/uncontrolled consistency: a `value` that becomes `undefined` makes
  React switch the input to uncontrolled and the value is lost.
- Unsaved-changes handling on navigation, if the repo does that elsewhere.
- Number inputs: `e.target.value` is a string. `parseInt` without a radix, or
  without a `NaN` check, puts `NaN` in state and renders it.

## Routing and URL state (if a router is present)

- State that should survive a refresh or be shareable (filters, tab, page, search)
  kept only in component state — the URL is the right home for it.
- Route params are strings and can be anything; parse and validate them.
- New route: is it in the auth-guarded section, and does a direct deep link to it
  work (not just navigation from inside the app)?
- Navigation on an unmounted component, or a redirect in render instead of an
  effect/route config.
- A route added without its corresponding lazy-loading/code-split treatment if the
  repo splits routes.

## Effects vs data libraries

If the PR hand-rolls fetching in `useEffect`, check all of:

- Cleanup/abort on unmount and on parameter change (race condition).
- Loading and error state.
- `finally` resetting the loading flag on the error path too.
- The dependency array not containing an inline object that refetches forever.
