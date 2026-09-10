# Java review — dispatch index

Read this table, then read **only** the files whose condition the diff actually
meets. Do not load all eight for a two-file change.

Every file is written to be gated on what
[`../pr-review-shared/stack-detection.md`](../pr-review-shared/stack-detection.md)
found in `pom.xml` / `build.gradle`. Skip any section whose library is not a
dependency of this repo.

| Read this | When the diff…                                                                                                                                                                                   |
| --- |--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **[core-java.md](core-java.md)** | Touches any `.java` file. Always applies. Language semantics, nullability, collections, streams, `equals`/`hashCode`, immutability, Optional, Lombok.                                            |
| **[spring.md](spring.md)** | Touches Spring components: `@Service`, `@Component`, `@Controller`, `@Configuration`, `@Transactional`, bean wiring, `application.yml`, Spring Security config, `@Scheduled`, `@Async`, WebFlux. |
| **[persistence-sql.md](persistence-sql.md)** | Touches entities, repositories, DAOs, queries (JPQL/SQL/Criteria/MyBatis), migrations (Flyway/Liquibase), `*.sql`, or stored procedures.                                                         |
| **[api-contracts.md](api-contracts.md)** | Adds or changes an endpoint, request/response DTO (`*Dto.java`), serialized payload, published event (`*Event*.java`), or Transactional Outbox methods (`*OutboxJob*.java`).                     |
| **[concurrency-performance.md](concurrency-performance.md)** | Touches threads, executors, `@Async`, `CompletableFuture`, `ParallelStream`, reactive chains, shared mutable state, batch jobs, or anything in a hot path.                                       |
| **[caching.md](caching.md)** | Adds or changes a cache — `@Cacheable`/`@CacheEvict`, Caffeine/Guava/Ehcache/Redis/Hazelcast, a cache key, TTL, eviction rule, invalidation path, or warm-up — **or** adds a de facto cache: a static `Map`, a memoised field, reference data loaded once at startup. |
| **[security.md](security.md)** | Touches authentication, authorization, tenancy, input handling, crypto, file/path handling, deserialization, logging of user data, or dependency versions.                                       |
| **[testing.md](testing.md)** | Touches any `src/test/**` file, **or** adds production logic with no accompanying test.                                                                                                          |

Also always apply
[`../pr-review-shared/cross-cutting.md`](../pr-review-shared/cross-cutting.md).

For repo conventions, architecture, and requirements, follow
[`../pr-review-shared/project-context.md`](../pr-review-shared/project-context.md) —
it says when those are worth reading and when they are not.

**Where the repo has its own rules or its own doc on one of these aspects, that
document wins over the file here, and the finding should cite it.** Look for
`CLAUDE.md`, `.claude/CLAUDE.md`, `.claude/rules/**` whose `paths:` globs match a
changed file, and any doc CLAUDE.md `@`-imports. Applying a generic checklist over
the top of a team's explicit rule is the fastest way to make a review ignorable.

## Version-gating reminders

Before raising a finding that depends on a language or framework version:

| Do not suggest | Unless |
| --- | --- |
| `record`, `switch` expressions, text blocks, pattern matching | Language level supports it (records: 16+, text blocks: 15+, pattern matching for `switch`: 21+) **and** the repo's own style rules permit it |
| `var` | **Never suggest it.** This skill prescribes explicit types — see [core-java.md](core-java.md). |
| Virtual threads, structured concurrency | Java 21+ |
| `jakarta.*` imports | Spring Boot 3+ / Jakarta EE 9+. On Boot 2 it is `javax.*`. |
| `SecurityFilterChain` bean style | Spring Security 5.4+; older code uses `WebSecurityConfigurerAdapter` |
| `@MockitoBean` | Spring Boot 3.4+; older code uses `@MockBean` |
| AssertJ / Testcontainers idioms | Those libraries are on the test classpath |
