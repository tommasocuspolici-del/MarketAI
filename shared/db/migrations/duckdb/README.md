# DuckDB Migrations

Rule 27 (v6.0): Every DuckDB schema change MUST be a SQL file in this
directory. NEVER modify the schema manually.

## File naming convention

```
YYYYMMDD_NNN_description.sql
```

- `YYYYMMDD` — date (UTC) the migration was authored
- `NNN` — zero-padded sequence number for that day (001, 002, ...)
- `description` — short snake_case description

Examples:

```
20260401_001_initial_schema.sql
20260415_002_add_correlations_table.sql
20260520_003_add_indexes.sql
```

## Ordering

Migrations are applied in **alphabetical order**, which equals chronological
order thanks to the `YYYYMMDD_NNN_` prefix. Do not rely on any other ordering.

## How to add a new migration

1. Create a new `.sql` file with the next sequence number.
2. Write idempotent DDL when possible:
   - `CREATE TABLE IF NOT EXISTS`
   - `CREATE INDEX IF NOT EXISTS`
3. Test locally:
   ```bash
   make migrate
   ```
4. Verify via `duckdb_schema_version` table:
   ```sql
   SELECT * FROM duckdb_schema_version ORDER BY applied_at DESC;
   ```

## How migrations are applied

The `DuckDBMigrator` (shared/db/duckdb_migrator.py) runs automatically via:

- `make migrate` — explicit command
- Application startup (via `run_pending_migrations()`)

It wraps each migration in a transaction. If any statement fails, the whole
migration is rolled back and no version row is recorded.

## Rollbacks

There is **no automatic rollback** system (DuckDB is primarily append-only
for our use case). If you need to reverse a schema change:

1. Write a **new** migration that does the inverse (drops a table, removes
   a column, etc.).
2. Apply it normally.

Never edit a migration that has already been applied on any environment.
