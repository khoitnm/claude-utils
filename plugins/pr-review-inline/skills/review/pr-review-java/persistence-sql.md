# Java — persistence, SQL, and migrations

Apply the subsections whose technology is actually a dependency. A MyBatis repo
gets nothing from the Hibernate section.

**Check the repo's data-access rules before writing any finding here.** This is the
area teams most often constrain deliberately — which mappings, query styles, and
repository methods are allowed — so it is where a generic finding is most likely to
be wrong. Read the repo's rules first and follow them; where they ban something
this file would tune, the finding is the ban. See
[`../pr-review-shared/project-context.md`](../pr-review-shared/project-context.md).

This file takes a position of its own on one question — relationships are scalar
ids plus per-query projections, never mapped associations (see the next section).
A repo whose rules say otherwise still wins; the precedence above is unchanged.

## JPA / Hibernate

### Relationships — scalar ids, not mapped associations

**This skill prescribes one style: model relationships as plain scalar id columns
(`private long featureId;`) and have each query fetch exactly what it needs via an
explicit join returning a projection or DTO.** No `@ManyToOne`, `@OneToMany`,
`@ManyToMany`, or `@OneToOne` — and that means avoiding *both* fetch strategies,
not choosing between them:

- `EAGER` drags the association into every load of the owning entity, application
  wide, including the paths this PR never touched, and produces N+1 or cartesian
  products that no two-row unit test reveals.
- `LAZY` moves the cost to an unpredictable dereference point and throws
  `LazyInitializationException` as soon as the proxy is touched outside an open
  session — near-guaranteed where `spring.jpa.open-in-view` is `false`, since the
  session then lives only inside an explicit transaction or a single repository
  call.

Nothing about the fetch *strategy* fixes either problem; removing the mapping does.

So, when the diff adds a mapped association, **the finding is the mapping**, eager
or lazy. Ask for a scalar id column plus a query that selects the related fields —
a dedicated `@Query` with an explicit join returning an interface projection or
DTO, or a second lookup where that is simpler.

### Fetching — the N+1 section

The most common performance defect in a Java PR, and it never shows up in a unit
test with two rows. In the scalar-id style it takes these shapes:

- A loop, or a `stream().map(id -> repo.findById(id))`, issuing one query per
  element. Fix with a batch query (`WHERE id IN (:ids)`) and a lookup map, or a
  single join projecting both sides.
- A service that fetches a list and then enriches each element with a per-row call
  — the same defect wearing a nicer name.
- A projection or mapper that quietly loads whole entities to build a DTO,
  reintroducing exactly the cost this style exists to avoid. Check the query
  selects columns rather than entities.
- A partially populated DTO: one mapper method should map every field of its
  target, or callers start hand-patching the gaps at each call site and the gaps
  drift apart.
- A join that fans out (one parent, many children) returning duplicated parent
  rows, then de-duplicated in Java — usually two queries would be cheaper and
  clearer than one.
- A new `findAll()` on a table that grows unbounded — and in a multi-tenant repo,
  any query with no tenant predicate at all.
- Batch loops that flush per row where one statement would do, and per-row
  `save()` in a loop over a large collection.

### Entity mapping

- `equals`/`hashCode` on entities: see [core-java.md](core-java.md). Generated IDs
  are null before persist.
- Missing `@Version` where concurrent updates are possible — last write silently
  wins.
- New column: nullable in the DB but non-null in the entity (or vice versa),
  wrong length, wrong precision for a decimal.
- Enum persisted with the default `ORDINAL` — reordering the enum silently
  corrupts every existing row. Should be `@Enumerated(EnumType.STRING)`.
- `@Transient` vs the JPA/Spring annotation confusion.

### Queries

- Native or JPQL string built by concatenating user input — injection. Bind
  parameters.
- A query changed but not its `countQuery` in a paginated repository method.
- `@Modifying` queries need `clearAutomatically`/`flushAutomatically` consideration,
  or the persistence context serves stale entities afterwards.
- Derived query method names that no longer match the entity's field names — this
  fails at startup, so check the field really exists.
- A new query with no supporting index (see the SQL section below).
- `getOne`/`getReferenceById` returns a proxy; touching it outside a transaction
  throws.

### Transactions and the session

Covered in [spring.md](spring.md). The persistence-specific traps:

- Reading an entity, modifying it, and relying on dirty checking — works only
  inside a transaction. Outside one, the change is silently discarded.
- Flushing in a loop, or a batch insert without `hibernate.jdbc.batch_size`.
- The first-level cache growing unbounded in a long-running batch — needs periodic
  `flush()` + `clear()`.

## MyBatis / JDBC / jOOQ

- MyBatis `${}` interpolates directly (injection); `#{}` binds. Every `${}` on a
  user-controlled value is a blocker.
- Manual JDBC: `PreparedStatement` with bound parameters, never string
  concatenation; `Connection`/`Statement`/`ResultSet` in try-with-resources.
- `ResultSet.getInt` returns 0 for SQL NULL — check `wasNull()` or use the boxed
  getter.
- Result mapping updated when a column is added or renamed.

## SQL and schema

- **Indexes**: a new query filtering, joining, or sorting on an unindexed column
  will table-scan. Check whether an index exists for the new predicate; if the
  table is large, a missing index is a blocker.
- Index column order matters for composite indexes — leading column must be the one
  filtered on.
- A function applied to a column in a predicate (`WHERE UPPER(name) = ?`,
  `WHERE DATE(created_at) = ?`) defeats the index.
- Implicit type conversion in a predicate does the same.
- `SELECT *` in production code — breaks when a column is added, and fetches more
  than needed.
- Unbounded result sets: no `LIMIT`/pagination on a query over a growing table.
- `NOT IN` with a subquery that can contain NULL returns no rows. Common and
  silent.
- Missing `ORDER BY` on a paginated query — pages overlap and skip rows
  non-deterministically.
- New nullable-aware logic: `= NULL` never matches; `<>` excludes NULLs.
- Lock ordering: two code paths taking the same rows in different orders deadlock
  under concurrency.

## Migrations (Flyway / Liquibase)

- **Never edit an already-applied migration.** Flyway checksums fail; Liquibase
  changeset checksums fail. New change = new file.
- Versioning and naming follow the repo's existing convention; duplicate version
  numbers break the deploy.
- **Rolling-deploy safety**: during deploy, old and new code both run against the
  new schema. A migration that drops or renames a column breaks the old instances
  still serving traffic. The safe shape is expand → migrate → contract across two
  releases.
- Adding a `NOT NULL` column with no default to an existing table fails if rows
  exist; with a default it may rewrite the whole table and lock it.
- Long-running DDL on a large table — does this need `CONCURRENTLY` (Postgres) or
  an online-DDL path?
- Data migrations in the same file as schema DDL, in a DB where DDL is not
  transactional, leave a half-applied state on failure.
- Is a rollback path defined, or is it a one-way door? Say which.
- New table/column: are the naming conventions, charset, collation, and audit
  columns consistent with neighbouring tables?

## Stored procedures (if the repo uses them)

- Parameters bound, not concatenated.
- Error handling inside the procedure: does a failure roll back, and does the
  caller learn about it?
- The procedure's contract (parameter count/order/types) matched by the Java call
  site — this is not checked at compile time.
- Versioning: is the procedure source in the repo and applied by a migration, or
  edited directly in the database? Direct edits are a finding.
