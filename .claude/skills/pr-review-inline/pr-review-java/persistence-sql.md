# Java — persistence, SQL, and migrations

Apply the subsections whose technology is actually a dependency. A MyBatis repo
gets nothing from the Hibernate section.

**Check the repo's data-access rules before writing any finding here.** This is the
area teams most often constrain deliberately, and where a generic finding is most
likely to be wrong. Where a repo bans a construct, **the finding is the ban, not
the tuning advice**:

- Some repos forbid mapped associations entirely (`@ManyToOne`, `@OneToMany`,
  `@ManyToOne`, `@OneToOne` — eager *or* lazy) and require a scalar id column plus
  a query-specific projection. In such a repo, "make it `LAZY` and add a
  `JOIN FETCH`" is the wrong comment; adding the association at all is the finding,
  and the whole N+1 section below has to be re-read in terms of projections.
- Others mandate `@Query`/JPQL over derived query methods, ban `findAll` in favour
  of tenant-scoped variants, or fix the migration file naming. Cite the rule file.

Where to look: `CLAUDE.md`, `.claude/CLAUDE.md`, `.claude/rules/**` matching the
changed path, and any doc CLAUDE.md `@`-imports — see
[`../pr-review-shared/project-context.md`](../pr-review-shared/project-context.md).

## JPA / Hibernate

### Fetching — the N+1 section

The most common performance defect in a Java PR, and it never shows up in a unit
test with two rows.

- A new `@ManyToOne`/`@OneToOne` defaults to **EAGER**. Every load of the owning
  entity now drags in the association, everywhere in the application — not just in
  the code this PR touched. Prefer `FetchType.LAZY` explicitly.
- A loop (or a stream `map`) over entities that touches a lazy association issues
  one query per element. Fix with a `JOIN FETCH`, an `@EntityGraph`, or a batch
  size.
- `JOIN FETCH` on two collections in one query produces a cartesian product.
- A new `findAll()` on a table that grows unbounded.
- Pagination combined with `JOIN FETCH` on a collection makes Hibernate paginate in
  memory — it logs a warning and loads everything.

### Entity mapping

- `equals`/`hashCode` on entities: see [core-java.md](core-java.md). Generated IDs
  are null before persist.
- `@Data`/`@ToString` from Lombok on an entity triggers lazy loads and can recurse
  on bidirectional relationships.
- Bidirectional relations need both sides maintained; setting only the inverse side
  does not persist the change.
- `CascadeType.ALL` / `REMOVE` on a `@ManyToOne` deletes the parent when a child
  goes. Almost never intended.
- `orphanRemoval = true` combined with replacing the whole collection.
- Missing `@Version` where concurrent updates are possible — last write silently
  wins.
- New column: nullable in the DB but non-null in the entity (or vice versa),
  wrong length, wrong precision for a decimal.
- Enum persisted with the default `ORDINAL` — reordering the enum silently
  corrupts every existing row. Should be `@Enumerated(EnumType.STRING)`.
- `LAZY` on a field accessed after the session closes → `LazyInitializationException`
  in production, often only for one code path.
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
