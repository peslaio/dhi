#!/bin/sh
set -eu

lifecycle_phase="${DHI_LIFECYCLE_PHASE-}"
case "$lifecycle_phase" in
  initial|restart) ;;
  *)
    echo "PostgreSQL lifecycle phase must be exactly 'initial' or 'restart', got '${lifecycle_phase:-unset}'" >&2
    exit 10
    ;;
esac

assertion_records=""
assertion_ids=""
assertion_count=0

record_assertion() {
  assertion_id="$1"
  case "$assertion_id" in
    ""|*[!a-z0-9._-]*)
      echo "PostgreSQL verifier attempted to record an invalid assertion ID '$assertion_id'" >&2
      exit 14
      ;;
  esac
  case "|$assertion_ids|" in
    *"|$assertion_id|"*)
      echo "PostgreSQL verifier attempted to record duplicate assertion ID '$assertion_id'" >&2
      exit 14
      ;;
  esac
  assertion_ids="${assertion_ids}${assertion_ids:+|}${assertion_id}"
  assertion_record="{\"id\":\"$assertion_id\",\"status\":\"pass\"}"
  assertion_records="${assertion_records}${assertion_records:+,}${assertion_record}"
  assertion_count=$((assertion_count + 1))
}

emit_assertion_summary() {
  if [ "$assertion_count" -ne 13 ]; then
    echo "PostgreSQL verifier recorded $assertion_count assertions, expected 13" >&2
    exit 14
  fi
  printf 'DHI_ASSERTION_SUMMARY {"assertions":[%s],"counts":{"fail":0,"pass":%s},"outcome":"pass","schemaVersion":1,"suite":"postgresql"}\n' \
    "$assertion_records" "$assertion_count"
}

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
record_assertion auth.application_ready

if PGPASSFILE="$wrong_pgpass" app_psql --command='SELECT 1' \
  >/tmp/postgresql-wrong-auth.log 2>&1; then
  echo "PostgreSQL accepted an incorrect application password" >&2
  exit 10
fi
echo "PostgreSQL rejected an incorrect application password as expected"
record_assertion auth.wrong_password_rejected

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
record_assertion schema.ddl

exact_state_summary() {
  app_psql --tuples-only --no-align --command="
SELECT CONCAT(
  (SELECT COUNT(*) FROM lifecycle_probe), '|',
  COALESCE((SELECT MAX(value) FROM lifecycle_probe WHERE id = 1), ''), '|',
  (SELECT COUNT(*) FROM parent_probe), '|',
  (SELECT COUNT(*) FROM parent_probe WHERE id = 1 AND value = 'postgresql-app-ok'), '|',
  (SELECT COUNT(*) FROM parent_probe WHERE id = 2 AND value = 'committed-value'), '|',
  (SELECT COUNT(*) FROM child_probe), '|',
  (SELECT COUNT(*) FROM child_probe WHERE id = 1 AND parent_id = 1 AND value = 'child-value')
);
"
}

if ! observed_state="$(exact_state_summary)"; then
  echo "PostgreSQL lifecycle state inspection failed before CRUD reset" >&2
  exit 10
fi

case "$lifecycle_phase" in
  initial)
    if [ "$observed_state" != "0||0|0|0|0|0" ]; then
      echo "PostgreSQL initial phase found state '$observed_state', expected an empty database state" >&2
      exit 10
    fi
    echo "PostgreSQL lifecycle marker is absent on the fresh data volume as expected"
    ;;
  restart)
    if [ "$observed_state" != "1|postgresql-persistence-v1|2|1|1|1|1" ]; then
      echo "PostgreSQL restart found persisted state '$observed_state', expected '1|postgresql-persistence-v1|2|1|1|1|1'" >&2
      exit 10
    fi
    echo "PostgreSQL verified the durable lifecycle marker and application state before CRUD reset"
    ;;
esac
record_assertion persistence.lifecycle_state

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
record_assertion constraint.unique

if app_psql --command="INSERT INTO child_probe (id, parent_id, value) VALUES (2, 999, 'orphan')" \
  >/tmp/postgresql-foreign-key.log 2>&1; then
  echo "PostgreSQL failed to enforce the foreign-key constraint" >&2
  exit 10
fi
echo "PostgreSQL foreign-key constraint rejected orphan data as expected"
record_assertion constraint.foreign_key

if app_psql --command='CREATE ROLE dhi_forbidden LOGIN' \
  >/tmp/postgresql-privilege.log 2>&1; then
  echo "PostgreSQL application role unexpectedly obtained role-administration privileges" >&2
  exit 10
fi
echo "PostgreSQL application role was denied role administration as expected"
record_assertion authorization.role_admin_denied

if ! summary="$(exact_state_summary)"; then
  echo "PostgreSQL authenticated state verification failed" >&2
  exit 10
fi
if [ "$summary" != "1|postgresql-persistence-v1|2|1|1|1|1" ]; then
  echo "PostgreSQL returned state '$summary', expected '1|postgresql-persistence-v1|2|1|1|1|1'" >&2
  exit 10
fi
record_assertion crud.insert_update_find
record_assertion crud.delete
record_assertion crud.idempotent_upsert
record_assertion transaction.commit
record_assertion transaction.rollback
record_assertion state.final_summary
printf '%s\n' "PostgreSQL authenticated application contract passed: phase=$lifecycle_phase state=$summary"
emit_assertion_summary
