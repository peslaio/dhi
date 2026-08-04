#!/bin/sh
set -eu

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

if mariadb --defaults-extra-file="$wrong_options" --database=dhi_contract \
  --execute='SELECT 1' >/tmp/mariadb-wrong-auth.log 2>&1; then
  echo "MariaDB accepted an incorrect application password" >&2
  exit 10
fi
echo "MariaDB rejected an incorrect application password as expected"

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

state_summary() {
  app_sql --batch --skip-column-names --execute="
SELECT CONCAT(
  (SELECT value FROM parent_probe WHERE id = 1), '|',
  (SELECT COUNT(*) FROM parent_probe WHERE id = 2), '|',
  (SELECT COUNT(*) FROM parent_probe WHERE id = 3), '|',
  (SELECT COUNT(*) FROM parent_probe WHERE id = 4), '|',
  (SELECT COUNT(*) FROM child_probe WHERE parent_id = 1)
);
"
}

if ! lifecycle_state="$(app_sql --batch --skip-column-names --execute="
SELECT CONCAT(
  COUNT(*), '|',
  COALESCE(MAX(CASE WHEN id = 1 THEN value END), '')
)
FROM lifecycle_probe;
")"; then
  echo "MariaDB lifecycle marker inspection failed before CRUD reset" >&2
  exit 10
fi

case "$lifecycle_state" in
  "0|")
    lifecycle_phase=initial
    echo "MariaDB lifecycle marker is absent on the fresh data volume as expected"
    ;;
  "1|mariadb-persistence-v1")
    lifecycle_phase=restart
    if ! persisted_summary="$(state_summary)"; then
      echo "MariaDB persisted application-state inspection failed before CRUD reset" >&2
      exit 10
    fi
    if [ "$persisted_summary" != "mariadb-app-ok|1|0|0|1" ]; then
      echo "MariaDB restart found persisted state '$persisted_summary', expected 'mariadb-app-ok|1|0|0|1'" >&2
      exit 10
    fi
    echo "MariaDB verified the durable lifecycle marker and application state before CRUD reset"
    ;;
  *)
    echo "MariaDB lifecycle marker state '$lifecycle_state' is inconsistent" >&2
    exit 10
    ;;
esac

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

if app_sql --execute="INSERT INTO child_probe (id, parent_id, value) VALUES (2, 999, 'orphan')" \
  >/tmp/mariadb-foreign-key.log 2>&1; then
  echo "MariaDB failed to enforce the foreign-key constraint" >&2
  exit 10
fi
echo "MariaDB foreign-key constraint rejected orphan data as expected"

if app_sql --execute="CREATE USER 'dhi_forbidden'@'%' IDENTIFIED BY 'not-used'" \
  >/tmp/mariadb-privilege.log 2>&1; then
  echo "MariaDB application user unexpectedly obtained account-administration privileges" >&2
  exit 10
fi
echo "MariaDB application user was denied account administration as expected"

if ! summary="$(state_summary)"; then
  echo "MariaDB authenticated state verification failed" >&2
  exit 10
fi
if [ "$summary" != "mariadb-app-ok|1|0|0|1" ]; then
  echo "MariaDB returned state '$summary', expected 'mariadb-app-ok|1|0|0|1'" >&2
  exit 10
fi
printf '%s\n' "MariaDB authenticated application contract passed: phase=$lifecycle_phase state=$summary"
printf '%s\n' 'DHI_ASSERTION_SUMMARY {"assertions":[{"id":"auth.application_ready","status":"pass"},{"id":"auth.wrong_password_rejected","status":"pass"},{"id":"schema.ddl","status":"pass"},{"id":"crud.insert_update_find","status":"pass"},{"id":"crud.delete","status":"pass"},{"id":"crud.idempotent_upsert","status":"pass"},{"id":"transaction.commit","status":"pass"},{"id":"transaction.rollback","status":"pass"},{"id":"constraint.unique","status":"pass"},{"id":"constraint.foreign_key","status":"pass"},{"id":"authorization.account_admin_denied","status":"pass"},{"id":"persistence.lifecycle_state","status":"pass"},{"id":"state.final_summary","status":"pass"}],"counts":{"fail":0,"pass":13},"outcome":"pass","schemaVersion":1,"suite":"mariadb"}'
