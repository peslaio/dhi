#!/bin/sh
set -eu

attempt=0
until mariadb-admin --host=app --port=3306 --user=root ping --silent; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 90 ]; then
    echo "MariaDB did not become ready" >&2
    exit 11
  fi
  sleep 1
done

if ! mariadb --host=app --port=3306 --user=root <<'SQL'
CREATE DATABASE IF NOT EXISTS dhi_contract;
CREATE TABLE IF NOT EXISTS dhi_contract.probe (
  id INT PRIMARY KEY,
  value VARCHAR(64) NOT NULL
);
REPLACE INTO dhi_contract.probe (id, value) VALUES (1, 'mariadb-app-ok');
SQL
then
  echo "MariaDB contract write failed" >&2
  exit 10
fi

if ! value="$(mariadb --batch --skip-column-names --host=app --port=3306 --user=root \
  --execute='SELECT value FROM dhi_contract.probe WHERE id = 1')"; then
  echo "MariaDB contract read failed" >&2
  exit 10
fi
if [ "$value" != "mariadb-app-ok" ]; then
  echo "MariaDB returned '$value', expected 'mariadb-app-ok'" >&2
  exit 10
fi
printf '%s\n' "$value"
