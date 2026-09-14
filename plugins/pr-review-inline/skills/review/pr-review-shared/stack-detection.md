# Shared: detecting the stack and the actual frameworks

Two separate questions. Answer both before loading any checklist.

## A. Which stacks does the diff touch?

Classify from the changed-file paths returned by `get_files`:

| Signal in changed paths | Stack |
| --- | --- |
| `*.java`, `*.kt`, `pom.xml`, `build.gradle`, `build.gradle.kts`, `*.jsp` | **Java** |
| `*.ts`, `*.tsx`, `*.js`, `*.jsx`, `*.css`, `*.scss`, `package.json` | **React / TypeScript** |
| `*.sql`, `db/migration/**`, MyBatis or Liquibase XML | **Java** (SQL/migration section) |
| `Dockerfile`, `.github/workflows/*.yml`, `helm/**`, `*.tf` | **Neither** — cross-cutting only |

A PR may be both. Load both sets. A PR that is only config or CI gets the
cross-cutting checklist and nothing else.

Ignore generated and vendored paths when classifying: `target/`, `build/`, `dist/`,
`out/`, `node_modules/`, `*.min.js`, `__generated__/`, `*.lock`, `package-lock.json`,
`yarn.lock`, `pnpm-lock.yaml`.

## B. Which frameworks does this repo actually use?

**Never assume a framework. Read the manifest.** A checklist item naming a library
the repo does not use is noise, and it costs credibility on the findings that are real.

### Java — read `pom.xml`, or `build.gradle` / `build.gradle.kts`

Grep the dependency block for the artifacts that gate each section. Check parent
POMs and imported BOMs too: a Spring Boot starter parent implies a large set of
managed dependencies that never appear by name in the child POM.

| Look for | Gates |
| --- | --- |
| `spring-boot-starter-web`, `spring-boot-starter`, `spring-context` | Spring core + web sections |
| `spring-boot-starter-webflux`, `reactor-core` | Reactive rules (materially different from MVC) |
| `spring-boot-starter-data-jpa`, `hibernate-core`, `jakarta.persistence` | JPA / Hibernate section |
| `mybatis`, `spring-boot-starter-jdbc`, `jooq` | Non-JPA persistence section |
| `spring-boot-starter-security`, `spring-security-*` | Spring Security section |
| `flyway-core`, `liquibase-core` | Migration section |
| `junit-jupiter` vs `junit` 4.x vs `testng` | Which test idioms to expect |
| `mockito-core`, `easymock` | Mocking idioms |
| `assertj-core`, `hamcrest` | Assertion idioms |
| `testcontainers` | Integration-test expectations |
| `lombok` | Lombok-specific pitfalls |
| `jackson-databind`, `gson` | Serialization section |
| `spring-boot-starter-cache`, `spring-context-support`, `@EnableCaching` | `pr-review-java/caching/spring-cache.md` |
| `caffeine`, `guava`, `ehcache`, `infinispan` | Local-cache rules: eviction policy, TTL/TTI, weigher, `recordStats` |
| `spring-boot-starter-data-redis`, `lettuce`, `jedis`, `hazelcast` | Distributed-cache rules: serialization, timeouts, cross-instance invalidation |
| `resilience4j`, `hystrix` | Resilience section |
| `micrometer`, `opentelemetry` | Observability expectations |
| `maven.compiler.release` / `sourceCompatibility` / `<java.version>` | Available language features |

Record the **Java language level**. Suggesting records, sealed types, pattern
matching, or virtual threads on a Java 8 codebase is a wasted comment.

Also record **Spring Boot 2 vs 3** — it decides `javax.*` vs `jakarta.*`, and much
of the Spring Security configuration idiom.

### React / TypeScript — read `package.json`

Read `dependencies` and `devDependencies`. Read `tsconfig.json` for `strict` —
strictness decides which type findings are worth raising at all.

| Look for | Gates |
| --- | --- |
| `react` and its major version | Hooks vs class idioms; React 18 concurrency; React 19 Actions / `use` |
| `next` | Server/client component boundary, data fetching, caching |
| `vite`, `webpack`, `react-scripts` | Build and bundle findings |
| `typescript` + `strict` setting | Depth of type findings |
| `@tanstack/react-query`, `swr`, `@apollo/client` | Server-state section |
| `redux`, `@reduxjs/toolkit`, `zustand`, `jotai`, `mobx` | Client-state section |
| `react-router-dom`, `@tanstack/react-router` | Routing section |
| `react-hook-form`, `formik`, `zod`, `yup` | Forms and validation |
| `jest` vs `vitest` | Test runner idioms |
| `@testing-library/react`, `@testing-library/user-event` | RTL testing section |
| `msw`, `nock` | Network mocking expectations |
| `playwright`, `cypress` | E2E expectations |
| `styled-components`, `@emotion/*`, `tailwindcss`, `*.module.css` | Styling section |
| `@mui/*`, `antd`, `@chakra-ui/*`, `@radix-ui/*` | Component-library conventions and built-in a11y |
| `eslint-plugin-jsx-a11y`, `eslint-plugin-react-hooks` | Already linted — raise only what the linter misses |

### Monorepos

If the repo has `packages/*`, `apps/*`, `nx.json`, `pnpm-workspace.yaml`, or a
multi-module `pom.xml`, resolve the manifest **nearest to each changed file**, not
the root one. Different packages sit on different React or Spring versions.

## C. Write down what you found

Before reviewing, state in one line what you detected:

> Stack: Java 17, Spring Boot 3.2, Spring Data JPA, JUnit 5 + Mockito + AssertJ,
> Testcontainers. Frontend untouched.

This makes detection errors obvious to the user, and it keeps you honest about
which checklists you are entitled to apply.

## D. Lint and format findings are usually not yours

If the repo runs Checkstyle, Spotless, SpotBugs, PMD, ESLint, Prettier, or Biome in
CI, do not spend review comments on what those tools already catch. Check
`get_check_runs` — if the linter passed, formatting is settled. Review the things a
linter cannot see.
