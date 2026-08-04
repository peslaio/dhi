#!/bin/sh
set -eu

export PATH="/usr/lib/postgresql/15/bin:$PATH"
secret=/run/secrets/postgresql-app-password
if [ ! -f "$secret" ] || [ ! -r "$secret" ]; then
  echo "PostgreSQL application password fixture is missing or unreadable" >&2
  exit 12
fi
app_password="$(cat "$secret")"
if [ -z "$app_password" ]; then
  echo "PostgreSQL application password fixture is empty" >&2
  exit 12
fi

umask 077
app_pgpass=/tmp/postgresql-app.pgpass
wrong_pgpass=/tmp/postgresql-wrong.pgpass
printf '*:*:*:dhi_app:%s\n' "$app_password" > "$app_pgpass"
printf '%s\n' '*:*:*:dhi_app:definitely-wrong' > "$wrong_pgpass"

export PGHOST=app
export PGPORT=5432
export PGDATABASE=dhi_contract
export PGUSER=dhi_app
export PGPASSFILE="$app_pgpass"

app_psql() {
  psql --no-psqlrc --set=ON_ERROR_STOP=1 "$@"
}

attempt=0
until app_psql --tuples-only --no-align --command='SELECT 1' >/dev/null 2>&1; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 90 ]; then
    echo "PostgreSQL did not become ready for the authenticated application role" >&2
    exit 11
  fi
  sleep 1
done

if PGPASSFILE="$wrong_pgpass" app_psql --command='SELECT 1' \
  >/tmp/postgresql-wrong-auth.log 2>&1; then
  echo "PostgreSQL accepted an incorrect application password" >&2
  exit 10
fi
echo "PostgreSQL rejected an incorrect application password as expected"

if ! app_psql <<'SQL'
CREATE TABLE IF NOT EXISTS parent_probe (
  id integer PRIMARY KEY,
  value text NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS child_probe (
  id integer PRIMARY KEY,
  parent_id integer NOT NULL REFERENCES parent_probe(id),
  value text NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS lifecycle_probe (
  id integer PRIMARY KEY,
  value text NOT NULL
);
SQL
then
  echo "PostgreSQL authenticated schema declaration failed" >&2
  exit 10
fi

state_summary() {
  app_psql --tuples-only --no-align --command="
SELECT
  (SELECT value FROM parent_probe WHERE id = 1) || '|' ||
  (SELECT COUNT(*) FROM parent_probe WHERE id = 2) || '|' ||
  (SELECT COUNT(*) FROM parent_probe WHERE id = 3) || '|' ||
  (SELECT COUNT(*) FROM parent_probe WHERE id = 4) || '|' ||
  (SELECT COUNT(*) FROM child_probe WHERE parent_id = 1);
"
}

if ! lifecycle_state="$(app_psql --tuples-only --no-align --command="
SELECT
  COUNT(*) || '|' ||
  COALESCE(MAX(value) FILTER (WHERE id = 1), '')
FROM lifecycle_probe;
")"; then
  echo "PostgreSQL lifecycle marker inspection failed before CRUD reset" >&2
  exit 10
fi

case "$lifecycle_state" in
  "0|")
    lifecycle_phase=initial
    echo "PostgreSQL lifecycle marker is absent on the fresh data volume as expected"
    ;;
  "1|postgresql-persistence-v1")
    lifecycle_phase=restart
    if ! persisted_summary="$(state_summary)"; then
      echo "PostgreSQL persisted application-state inspection failed before CRUD reset" >&2
      exit 10
    fi
    if [ "$persisted_summary" != "postgresql-app-ok|1|0|0|1" ]; then
      echo "PostgreSQL restart found persisted state '$persisted_summary', expected 'postgresql-app-ok|1|0|0|1'" >&2
      exit 10
    fi
    echo "PostgreSQL verified the durable lifecycle marker and application state before CRUD reset"
    ;;
  *)
    echo "PostgreSQL lifecycle marker state '$lifecycle_state' is inconsistent" >&2
    exit 10
    ;;
esac

if ! app_psql <<'SQL'
TRUNCATE child_probe, parent_probe;

INSERT INTO parent_probe (id, value) VALUES (1, 'initial-value');
PREPARE update_probe(text, integer) AS
  UPDATE parent_probe SET value = $1 WHERE id = $2;
EXECUTE update_probe('postgresql-app-ok', 1);
DEALLOCATE update_probe;

BEGIN;
INSERT INTO parent_probe (id, value) VALUES (2, 'committed-value');
COMMIT;

BEGIN;
INSERT INTO parent_probe (id, value) VALUES (3, 'rolled-back-value');
ROLLBACK;

INSERT INTO child_probe (id, parent_id, value) VALUES (1, 1, 'child-value');
INSERT INTO parent_probe (id, value) VALUES (4, 'delete-me');
DELETE FROM parent_probe WHERE id = 4;

INSERT INTO parent_probe (id, value) VALUES (1, 'postgresql-app-ok')
ON CONFLICT (id) DO UPDATE SET value = EXCLUDED.value;
INSERT INTO parent_probe (id, value) VALUES (1, 'postgresql-app-ok')
ON CONFLICT (id) DO UPDATE SET value = EXCLUDED.value;
INSERT INTO lifecycle_probe (id, value) VALUES (1, 'postgresql-persistence-v1')
ON CONFLICT (id) DO UPDATE SET value = EXCLUDED.value;
SQL
then
  echo "PostgreSQL authenticated DDL/CRUD/transaction contract failed" >&2
  exit 10
fi

if app_psql --command="INSERT INTO parent_probe (id, value) VALUES (5, 'postgresql-app-ok')" \
  >/tmp/postgresql-unique.log 2>&1; then
  echo "PostgreSQL failed to enforce the unique constraint" >&2
  exit 10
fi
echo "PostgreSQL unique constraint rejected duplicate data as expected"

if app_psql --command="INSERT INTO child_probe (id, parent_id, value) VALUES (2, 999, 'orphan')" \
  >/tmp/postgresql-foreign-key.log 2>&1; then
  echo "PostgreSQL failed to enforce the foreign-key constraint" >&2
  exit 10
fi
echo "PostgreSQL foreign-key constraint rejected orphan data as expected"

if app_psql --command='CREATE ROLE dhi_forbidden LOGIN' \
  >/tmp/postgresql-privilege.log 2>&1; then
  echo "PostgreSQL application role unexpectedly obtained role-administration privileges" >&2
  exit 10
fi
echo "PostgreSQL application role was denied role administration as expected"

if ! summary="$(state_summary)"; then
  echo "PostgreSQL authenticated state verification failed" >&2
  exit 10
fi
if [ "$summary" != "postgresql-app-ok|1|0|0|1" ]; then
  echo "PostgreSQL returned state '$summary', expected 'postgresql-app-ok|1|0|0|1'" >&2
  exit 10
fi
printf '%s\n' "PostgreSQL authenticated application contract passed: phase=$lifecycle_phase state=$summary"
printf '%s\n' 'DHI_ASSERTION_SUMMARY {"assertions":[{"id":"auth.application_ready","status":"pass"},{"id":"auth.wrong_password_rejected","status":"pass"},{"id":"schema.ddl","status":"pass"},{"id":"crud.insert_update_find","status":"pass"},{"id":"crud.delete","status":"pass"},{"id":"crud.idempotent_upsert","status":"pass"},{"id":"transaction.commit","status":"pass"},{"id":"transaction.rollback","status":"pass"},{"id":"constraint.unique","status":"pass"},{"id":"constraint.foreign_key","status":"pass"},{"id":"authorization.role_admin_denied","status":"pass"},{"id":"persistence.lifecycle_state","status":"pass"},{"id":"state.final_summary","status":"pass"}],"counts":{"fail":0,"pass":13},"outcome":"pass","schemaVersion":1,"suite":"postgresql"}'
