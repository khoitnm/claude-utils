# React — accessibility

Apply when the diff adds or changes rendered markup, an interactive control, a
dialog/menu/tooltip, a form, an icon-only button, dynamic content, or anything
conveyed by color.

If `eslint-plugin-jsx-a11y` is configured and passing in CI, skip the rules it
already enforces (alt text, `onClick` on a non-interactive element without a role,
invalid ARIA attributes) and spend the review on what a linter cannot check:
focus behaviour, announcement, and whether the semantics are actually right.

## Semantics first

- **A `div` or `span` with an `onClick` is not a button.** It is not focusable, not
  keyboard-activatable, and not announced as an action. Every such element needs
  `role`, `tabIndex={0}`, and `onKeyDown` handling for Enter and Space — or, far
  better, be a real `<button>`. A native element is almost always the right fix;
  suggest that rather than the ARIA patch.
- Links vs buttons: `<a>` navigates (and must have a real `href`), `<button>`
  performs an action. An `<a>` with no `href` is not focusable; a `<button>` used
  for navigation breaks open-in-new-tab and middle-click.
- Headings form an outline: one `h1`, no skipped levels. A heading level chosen for
  its font size is a finding — style it instead.
- Lists as `ul`/`ol`/`li`, tables as `table`/`th` with `scope`, not divs with grid
  CSS, when the content is genuinely tabular.
- Landmarks (`main`, `nav`, `header`, `aside`) on new page-level structure.

## Names and labels

- **Every form control needs a programmatic label**: a `<label htmlFor>` matching
  the input's `id`, or `aria-label`/`aria-labelledby`. Placeholder text is not a
  label — it disappears on input and many screen readers skip it.
- **Icon-only buttons need an accessible name.** An icon button with no text and no
  `aria-label` is announced as "button" and is unusable. This is the single most
  common a11y defect in React PRs.
- Decorative icons/images: `alt=""` or `aria-hidden="true"`, so they are not
  announced. Meaningful images need real alt text describing the content, not the
  filename.
- Duplicated `id`s from a component rendered more than once break every
  `htmlFor`/`aria-describedby` association. Use `useId()` (React 18+) rather than a
  module-level counter.
- Link text that reads as "click here" or "read more" out of context.

## Keyboard

- **Everything doable with a mouse must be doable with a keyboard.** Walk the new
  UI mentally with Tab, Shift+Tab, Enter, Space, Escape, and arrows.
- Focus must be visible. A CSS reset removing `outline` with no replacement focus
  style is a blocker for keyboard users — check any new `:focus` or `outline: none`.
- Tab order follows visual order. Positive `tabIndex` values (anything > 0) break
  the natural order globally; almost always wrong.
- `tabIndex={-1}` on something the user needs to reach removes it from the tab
  order.
- Custom widgets follow the expected key pattern: menus and tabs respond to arrow
  keys, Escape closes overlays, Enter/Space activate.

## Focus management

- **Modals and dialogs**: focus moves into the dialog on open, is trapped inside
  while it is open, and returns to the triggering element on close. Losing focus to
  the top of the document strands keyboard and screen-reader users. Prefer the
  repo's existing dialog primitive (Radix, MUI, headlessui) over a hand-rolled one —
  these behaviours are why it exists.
- Content behind a modal should be inert (`aria-hidden` or the `inert` attribute)
  so it is not reachable.
- After a route change, focus should move to the new content or a heading.
- After deleting a row, focus should land somewhere sensible, not be lost.
- Do not steal focus on mount for something the user did not initiate.

## Dynamic content and state

- Async results, validation errors, toasts, and status messages need to be
  **announced**: a live region (`aria-live="polite"`, or `role="alert"` for errors)
  or an equivalent from the component library. A sighted user sees the toast; a
  screen-reader user gets nothing.
- Loading states announced, not just a spinner.
- Component state exposed to assistive tech: `aria-expanded` on a disclosure,
  `aria-selected` on a tab, `aria-checked` on a custom checkbox, `aria-current` on
  the active nav item, `aria-invalid` + `aria-describedby` on a field with an
  error.
- ARIA that lies is worse than no ARIA. An `aria-expanded` that never updates
  actively misinforms.
- `aria-hidden` on something focusable creates an element that can be tabbed to but
  not announced.

## Visual

- **Color must not be the only signal.** Error state shown only in red, required
  fields marked only by color, a status conveyed only by a colored dot — add an
  icon, text, or pattern.
- Contrast: text at 4.5:1 (3:1 for large text), and UI component boundaries and
  focus indicators at 3:1. Check any new color pair against the token palette.
- Text must survive 200% zoom and reflow at 320px width — fixed pixel heights on
  text containers cause clipping.
- Respect `prefers-reduced-motion` for new animations, especially anything that
  moves or parallaxes.
- Do not disable pinch zoom in viewport meta.

## Component libraries

If the repo uses MUI/Chakra/Radix/Ant, the accessible behaviour is usually already
in the primitive. The finding is typically **not using it** — a hand-rolled
dropdown next to twelve `Select` usages — or overriding it in a way that breaks it
(replacing the internal button, spreading props that clobber ARIA attributes).

## Scale the demand

For a small PR, raise the concrete defects in the changed markup. Do not turn a
two-line change into an audit of the surrounding page — note broader problems once,
in the summary, as context rather than as blockers on this author.
