# Java — security

Apply when the diff touches authentication, authorization, tenancy, untrusted
input, crypto, files, deserialization, logging of user data, or dependencies.

Cross-cutting security basics are in
[`../pr-review-shared/cross-cutting.md`](../pr-review-shared/cross-cutting.md) §3;
this file is the Java-specific detail.

## Authorization — the highest-value check

- **A new endpoint or handler**: is it actually covered by the security
  configuration? Compare the new path literally against the matchers in the
  `SecurityFilterChain` / `WebSecurityConfigurerAdapter`. New prefixes routinely
  fall outside them and ship unauthenticated.
- **Object-level authorization**: the caller is authenticated, but is this
  *their* record? A method taking an ID from the request and loading it without
  checking ownership or tenant is the most common real vulnerability in enterprise
  Java. `findById(id)` with no tenant predicate is a blocker.
- Authorization checked in the controller but the service is also reachable from a
  message consumer, a scheduled job, or another controller that does not check.
- `@PreAuthorize` with a SpEL expression referencing a parameter that can be
  manipulated, or that fails open when the expression errors.
- Role checks by string literal, duplicated and easy to typo — one misspelling
  makes the check always false, i.e. always deny, or `hasAnyRole` making it always
  allow.
- Method security not enabled at all, making every `@PreAuthorize` decorative.
  Verify the enabling annotation exists somewhere.

## Injection

- **SQL/JPQL**: any query built by concatenation with a value that originates from
  a request. Bind parameters. MyBatis `${}` is concatenation.
- Dynamic `ORDER BY`/table names cannot be bound — must be validated against an
  allowlist, not escaped.
- **Command injection**: `Runtime.exec`, `ProcessBuilder` with user input.
- **Path traversal**: a filename or path segment from a request used to build a
  file path. Normalise and verify the resolved path stays under the intended root;
  `..` in a filename is the whole attack.
- **SSRF**: a URL from user input passed to an HTTP client. Allowlist the host; a
  blocklist does not work.
- **XXE**: any XML parser (`DocumentBuilderFactory`, `SAXParserFactory`,
  `XMLInputFactory`, `Unmarshaller`, XSLT) on untrusted input must have external
  entities and DTDs disabled. Defaults are unsafe in older Java.
- **Deserialization**: Java native deserialization of untrusted bytes is remote code
  execution. Jackson polymorphic typing with a type field from input is the same
  class of bug. `ObjectInputStream` on anything from outside the process is a
  blocker.
- **Log injection**: unsanitised newline-containing user input written to logs
  forges log entries.
- **Template/SpEL/OGNL injection**: user input evaluated as an expression.

## Secrets and crypto

- Credentials, tokens, keys, or connection strings in source, `application.yml`,
  test fixtures, or a comment. Once committed they are in git history — say so, and
  say the credential must be rotated, not just deleted.
- `Random` used to generate anything security-relevant (tokens, IDs, passwords,
  nonces). Must be `SecureRandom`.
- Passwords hashed with MD5/SHA-1/SHA-256-without-salt. Must be bcrypt/scrypt/
  Argon2/PBKDF2 with a work factor.
- Hardcoded IV, hardcoded salt, ECB mode, or a key derived from a constant.
- TLS verification disabled — a trust-all `TrustManager` or `HostnameVerifier`.
  This appears "temporarily" and never leaves. Blocker.
- Comparing secrets/HMACs with `String.equals` — timing side channel; use
  `MessageDigest.isEqual`.
- Encryption added without a key-rotation story.

## Sensitive data handling

In a healthcare or financial codebase, treat these as blockers rather than
improvements:

- PHI/PII written to logs, including inside an exception message or a serialized
  request body dumped on error.
- PHI in a URL path or query string — URLs land in access logs, proxies, and
  browser history.
- A new response field exposing data the caller is not entitled to — check what the
  mapper copies, not what the DTO is called.
- Audit trail: does an operation on protected data need an audit record, and does
  the repo's existing pattern for that get followed here?
- Caching of user-scoped data with a key that omits the user/tenant.
- Data crossing a tenant boundary in a join, a cache, a static field, or a
  `ThreadLocal` not cleared.

## Web-specific

- CSRF disabled for a cookie-authenticated app.
- CORS with `allowedOrigins("*")` plus credentials.
- Missing/loosened security headers if the repo sets them elsewhere.
- Open redirect: a redirect target taken from a request parameter.
- Error responses leaking stack traces, SQL, internal hostnames, or framework
  versions to the client.
- Mass assignment — see [api-contracts.md](api-contracts.md).
- File upload: content type and size limits, extension allowlist, stored outside
  the web root, filename not taken from the client.

## Dependencies

- A newly added dependency: is it needed, maintained, and does it duplicate
  something already present? Does the repo's scanner (Dependabot, Snyk, OWASP
  dependency-check) pass — check `get_check_runs`.
- A version *downgrade*, or a pin that moves off a patched release.
- A transitive dependency pulled in with a known-vulnerable version.
- `SNAPSHOT` or unpinned version ranges in a production build.
