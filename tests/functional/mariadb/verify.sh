#!/bin/sh
set -eu

lifecycle_phase="${DHI_LIFECYCLE_PHASE-}"
case "$lifecycle_phase" in
  initial|restart) ;;
  *)
    echo "MariaDB lifecycle phase must be exactly 'initial' or 'restart', got '${lifecycle_phase:-unset}'" >&2
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
      echo "MariaDB verifier attempted to record an invalid assertion ID '$assertion_id'" >&2
      exit 14
      ;;
  esac
  case "|$assertion_ids|" in
    *"|$assertion_id|"*)
      echo "MariaDB verifier attempted to record duplicate assertion ID '$assertion_id'" >&2
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
    echo "MariaDB verifier recorded $assertion_count assertions, expected 13" >&2
    exit 14
  fi
  printf 'DHI_ASSERTION_SUMMARY {"assertions":[%s],"counts":{"fail":0,"pass":%s},"outcome":"pass","schemaVersion":1,"suite":"mariadb"}\n' \
    "$assertion_records" "$assertion_count"
}

secret=/run/secrets/mariadb-app-password
if [ ! -f "$secret" ] || [ ! -r "$secret" ]; then
  echo "MariaDB application password fixture is missing or unreadable" >&2
  exit 12
fi
app_password="$(cat "$secret")"
if [ -z "$app_password" ]; then
  echo "MariaDB application password fixture is empty" >&2
  exit 12
fi

umask 077
app_options=/tmp/mariadb-app.cnf
wrong_options=/tmp/mariadb-wrong.cnf
cat > "$app_options" <<EOF
[client]
protocol=tcp
host=app
port=3306
user=dhi_app
password=${app_password}
EOF
cat > "$wrong_options" <<'EOF'
[client]
protocol=tcp
host=app
port=3306
user=dhi_app
password=definitely-wrong
EOF

app_sql() {
  mariadb --defaults-extra-file="$app_options" --database=dhi_contract "$@"
}

attempt=0
until app_sql --batch --skip-column-names --execute='SELECT 1' >/dev/null 2>&1; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 90 ]; then
    echo "MariaDB did not become ready for the authenticated application user" >&2
    exit 11
  fi
  sleep 1
done
record_assertion auth.application_ready

if mariadb --defaults-extra-file="$wrong_options" --database=dhi_contract \
  --execute='SELECT 1' >/tmp/mariadb-wrong-auth.log 2>&1; then
  echo "MariaDB accepted an incorrect application password" >&2
  exit 10
fi
echo "MariaDB rejected an incorrect application password as expected"
record_assertion auth.wrong_password_rejected

if ! app_sql <<'SQL'
CREATE TABLE IF NOT EXISTS parent_probe (
  id INT PRIMARY KEY,
  value VARCHAR(64) NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS child_probe (
  id INT PRIMARY KEY,
  parent_id INT NOT NULL,
  value VARCHAR(64) NOT NULL UNIQUE,
  CONSTRAINT fk_child_parent FOREIGN KEY (parent_id) REFERENCES parent_probe(id)
);
CREATE TABLE IF NOT EXISTS lifecycle_probe (
  id INT PRIMARY KEY,
  value VARCHAR(64) NOT NULL
);
SQL
then
  echo "MariaDB authenticated schema declaration failed" >&2
  exit 10
fi
record_assertion schema.ddl

exact_state_summary() {
  app_sql --batch --skip-column-names --execute="
SELECT CONCAT(
  (SELECT COUNT(*) FROM lifecycle_probe), '|',
  COALESCE((SELECT MAX(value) FROM lifecycle_probe WHERE id = 1), ''), '|',
  (SELECT COUNT(*) FROM parent_probe), '|',
  (SELECT COUNT(*) FROM parent_probe WHERE id = 1 AND value = 'mariadb-app-ok'), '|',
  (SELECT COUNT(*) FROM parent_probe WHERE id = 2 AND value = 'committed-value'), '|',
  (SELECT COUNT(*) FROM child_probe), '|',
  (SELECT COUNT(*) FROM child_probe WHERE id = 1 AND parent_id = 1 AND value = 'child-value')
);
"
}

if ! observed_state="$(exact_state_summary)"; then
  echo "MariaDB lifecycle state inspection failed before CRUD reset" >&2
  exit 10
fi

case "$lifecycle_phase" in
  initial)
    if [ "$observed_state" != "0||0|0|0|0|0" ]; then
      echo "MariaDB initial phase found state '$observed_state', expected an empty database state" >&2
      exit 10
    fi
    echo "MariaDB lifecycle marker is absent on the fresh data volume as expected"
    ;;
  restart)
    if [ "$observed_state" != "1|mariadb-persistence-v1|2|1|1|1|1" ]; then
      echo "MariaDB restart found persisted state '$observed_state', expected '1|mariadb-persistence-v1|2|1|1|1|1'" >&2
      exit 10
    fi
    echo "MariaDB verified the durable lifecycle marker and application state before CRUD reset"
    ;;
esac
record_assertion persistence.lifecycle_state

if ! app_sql <<'SQL'
DELETE FROM child_probe;
DELETE FROM parent_probe;

INSERT INTO parent_probe (id, value) VALUES (1, 'initial-value');
PREPARE update_probe FROM 'UPDATE parent_probe SET value = ? WHERE id = ?';
SET @probe_value = 'mariadb-app-ok', @probe_id = 1;
EXECUTE update_probe USING @probe_value, @probe_id;
DEALLOCATE PREPARE update_probe;

START TRANSACTION;
INSERT INTO parent_probe (id, value) VALUES (2, 'committed-value');
COMMIT;

START TRANSACTION;
INSERT INTO parent_probe (id, value) VALUES (3, 'rolled-back-value');
ROLLBACK;

INSERT INTO child_probe (id, parent_id, value) VALUES (1, 1, 'child-value');
INSERT INTO parent_probe (id, value) VALUES (4, 'delete-me');
DELETE FROM parent_probe WHERE id = 4;

INSERT INTO parent_probe (id, value) VALUES (1, 'mariadb-app-ok')
  ON DUPLICATE KEY UPDATE value = VALUES(value);
INSERT INTO parent_probe (id, value) VALUES (1, 'mariadb-app-ok')
  ON DUPLICATE KEY UPDATE value = VALUES(value);
INSERT INTO lifecycle_probe (id, value) VALUES (1, 'mariadb-persistence-v1')
  ON DUPLICATE KEY UPDATE value = VALUES(value);
SQL
then
  echo "MariaDB authenticated DDL/CRUD/transaction contract failed" >&2
  exit 10
fi

if app_sql --execute="INSERT INTO parent_probe (id, value) VALUES (5, 'mariadb-app-ok')" \
  >/tmp/mariadb-unique.log 2>&1; then
  echo "MariaDB failed to enforce the unique constraint" >&2
  exit 10
fi
echo "MariaDB unique constraint rejected duplicate data as expected"
record_assertion constraint.unique

if app_sql --execute="INSERT INTO child_probe (id, parent_id, value) VALUES (2, 999, 'orphan')" \
  >/tmp/mariadb-foreign-key.log 2>&1; then
  echo "MariaDB failed to enforce the foreign-key constraint" >&2
  exit 10
fi
echo "MariaDB foreign-key constraint rejected orphan data as expected"
record_assertion constraint.foreign_key

if app_sql --execute="CREATE USER 'dhi_forbidden'@'%' IDENTIFIED BY 'not-used'" \
  >/tmp/mariadb-privilege.log 2>&1; then
  echo "MariaDB application user unexpectedly obtained account-administration privileges" >&2
  exit 10
fi
echo "MariaDB application user was denied account administration as expected"
record_assertion authorization.account_admin_denied

if ! summary="$(exact_state_summary)"; then
  echo "MariaDB authenticated state verification failed" >&2
  exit 10
fi
if [ "$summary" != "1|mariadb-persistence-v1|2|1|1|1|1" ]; then
  echo "MariaDB returned state '$summary', expected '1|mariadb-persistence-v1|2|1|1|1|1'" >&2
  exit 10
fi
record_assertion crud.insert_update_find
record_assertion crud.delete
record_assertion crud.idempotent_upsert
record_assertion transaction.commit
record_assertion transaction.rollback
record_assertion state.final_summary
printf '%s\n' "MariaDB authenticated application contract passed: phase=$lifecycle_phase state=$summary"
emit_assertion_summary
