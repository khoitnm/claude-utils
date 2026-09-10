# React / frontend — security

Apply when the diff touches raw HTML, URLs, tokens, auth state, user-supplied
content, external communication, or dependencies.

The governing principle: **the frontend is not a trust boundary.** Anything
enforced only in the browser is not enforced. Every check here is about limiting
damage and not creating new holes, not about replacing server-side controls.

## XSS

- **`dangerouslySetInnerHTML`** with any value that is not a compile-time constant.
  Trace the value to its origin. If it can contain user input, it must be
  sanitized with DOMPurify (or the repo's sanitizer) at the point of rendering, and
  configured to strip event handlers and `javascript:` URLs — not merely escaped
  somewhere upstream. Rendering unsanitized user HTML is a blocker.
- Markdown or rich-text rendering with raw HTML enabled.
- `href`/`src` built from user or API data: a `javascript:` or `data:` URL executes.
  Validate the scheme against an allowlist (`https:`, `mailto:`, relative).
- A URL from a query parameter used for redirect or as an iframe `src` — open
  redirect / clickjacking vector.
- `eval`, `new Function`, `setTimeout("string")`, or dynamic `import()` of a
  computed path.
- Injecting into `document.write`, `innerHTML`, or a script/style tag directly.
- SVG uploaded by users rendered inline — SVG can carry script.

## Tokens, storage, and secrets

- **Access/refresh tokens in `localStorage` or `sessionStorage`** are readable by
  any script that reaches the page, so any XSS becomes full account takeover.
  Prefer httpOnly cookies. Where the repo already made this choice, do not
  relitigate it in a PR — but do flag a *new* token being put there.
- Secrets in frontend code or env vars: anything in a `VITE_*` /
  `NEXT_PUBLIC_*` / `REACT_APP_*` variable **ships to the browser**. An API key,
  client secret, or private token there is exposed. Blocker.
- PHI/PII persisted to `localStorage`, IndexedDB, or a URL — URLs land in browser
  history, referrers, and server access logs. In a healthcare product treat this
  as a blocker.
- Sensitive values in `console.log` left in production code, or in an error report
  sent to a third-party monitoring service.
- Auth state or user data cached without clearing it on logout — the next user of
  the machine sees it.

## Authorization in the UI

- Hiding a button is not access control. If this PR adds a permission-gated
  action, confirm the server enforces it too; if you cannot see the server, say
  that explicitly rather than assuming.
- Data over-fetching: the API returns fields the UI filters out. Those fields are
  in the browser's network tab. If they are sensitive, the fix is server-side.
- A client-side route guard with no server check behind it.
- Role/permission logic duplicated in the frontend that can drift from the server's.

## External communication

- **`target="_blank"` needs `rel="noopener noreferrer"`** — without `noopener` the
  opened page can navigate the opener. Most modern browsers imply it, but linters
  and older embedded webviews still care.
- `postMessage` sent with `"*"` as the target origin leaks the payload to whatever
  is in the frame; a `message` listener that does not verify `event.origin` accepts
  input from anyone. Both are real vulnerabilities.
- New third-party script, widget, iframe, or CDN import: who controls it, what does
  it get access to, does it break the CSP? A script tag added to `index.html` runs
  with full page privileges.
- CORS or credential settings changed on the client (`credentials: 'include'` to a
  new origin).
- User-supplied URLs fetched by the client.

## Input handling

- Regex built from user input (injection) or with nested quantifiers (catastrophic
  backtracking freezes the tab).
- `JSON.parse` on untrusted input inside a try/catch — and the catch must not
  swallow the failure silently.
- File upload: type and size checked client-side for UX, but the finding is
  whether the server checks too. Filenames from users rendered without escaping.
- Deep-merging user-controlled objects into config — prototype pollution.

## Dependencies

- A new package: is it needed, maintained, and reasonably popular? Does it
  duplicate something present? Check the install-size and transitive count.
- Typosquat risk on an unfamiliar package name — verify it is the package intended.
- A package with install scripts, or one added only as a transitive pin.
- Version downgrades, or a lockfile change that is not explained by the manifest
  change.
- Check `get_check_runs` for the repo's audit/Dependabot/Snyk job rather than
  duplicating it by hand.

## Content Security Policy

If the repo sets a CSP, check that new inline styles/scripts, `eval`-based
libraries, or new external origins do not require weakening it. A PR that adds
`unsafe-inline` or `unsafe-eval` to make something work is a blocker with a
discussion attached.
