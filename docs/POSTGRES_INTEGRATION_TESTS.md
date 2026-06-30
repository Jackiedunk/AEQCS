# PostgreSQL Integration Tests

AEQCS keeps PostgreSQL integration tests opt-in so normal local test runs do
not require a database.

## Requirements

- PostgreSQL test database
- TimescaleDB extension available to the test database user
- pgvector extension available to the test database user
- Python dependencies installed with the project development extras

The test user must be allowed to run:

```sql
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS vector;
```

Use a disposable database. The tests create the AEQCS schema and clean rows
with integration-test identifiers, but the safest setup is still a dedicated
test database.

## Run

PowerShell:

```powershell
$env:AEQCS_TEST_PG_DSN = "postgresql://user:password@localhost:5432/aeqcs_test"
python -m pytest tests/integration -m integration
```

Run the full suite with the integration test enabled:

```powershell
$env:AEQCS_TEST_PG_DSN = "postgresql://user:password@localhost:5432/aeqcs_test"
python -m pytest
```

Without `AEQCS_TEST_PG_DSN`, the integration test is skipped.

## Current Coverage

The current integration test verifies:

- schema bootstrap using `deploy.init_db.SCHEMA_SQL`
- Timescale-backed daily bar table can store and query PIT market data
- financial indicator PIT query works against PostgreSQL
- uploaded document and chunk round trip through `PgCoreStore`
- proposal submission and gate review round trip through `PgCoreStore`
