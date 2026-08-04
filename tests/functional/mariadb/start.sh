#!/bin/sh
set -eu

datadir=/var/lib/mysql
socket=/run/mysqld/mysqld.sock
marker="$datadir/.dhi-functional-initialized"
in_progress="$datadir/.dhi-functional-bootstrap-in-progress"
root_secret=/run/secrets/mariadb-root-password
app_secret=/run/secrets/mariadb-app-password

read_test_secret() {
  secret_name="$1"
  secret_path="$2"

  if [ ! -f "$secret_path" ] || [ ! -r "$secret_path" ]; then
    echo "MariaDB test $secret_name secret is missing or unreadable: $secret_path" >&2
    exit 12
  fi
  secret_value="$(cat "$secret_path")"
  case "$secret_value" in
    "")
      echo "MariaDB test $secret_name secret must not be empty" >&2
      exit 12
      ;;
    *[!A-Za-z0-9_@%+=:.,-]*)
      echo "MariaDB test $secret_name secret contains unsupported fixture characters" >&2
      exit 12
      ;;
  esac
  printf '%s' "$secret_value"
}

root_password="$(read_test_secret root-password "$root_secret")"
app_password="$(read_test_secret app-password "$app_secret")"

mkdir -p "$datadir" /run/mysqld /var/log/mysql
if [ -e "$marker" ] && [ ! -d "$datadir/mysql" ]; then
  echo "MariaDB test data marker exists without a system database" >&2
  exit 12
fi

if [ ! -e "$marker" ]; then
  bootstrap_user=root
  if [ -e "$in_progress" ]; then
    echo "MariaDB test found an interrupted credential bootstrap and will not overwrite it" >&2
    exit 12
  fi

  if [ -d "$datadir/mysql" ]; then
    if [ ! -f "$datadir/debian-10.11.flag" ]; then
      echo "MariaDB test refuses to adopt an unrecognized preinitialized data directory" >&2
      exit 12
    fi
    for database_directory in "$datadir"/*; do
      [ -d "$database_directory" ] || continue
      case "${database_directory##*/}" in
        mysql|performance_schema|sys) ;;
        *)
          echo "MariaDB test refuses to adopt preinitialized application data: $database_directory" >&2
          exit 12
          ;;
      esac
    done
    echo "MariaDB test is securing the package-created system database"
    bootstrap_user=mysql
  elif find "$datadir" -mindepth 1 -maxdepth 1 ! -name .cache -print -quit | grep -q .; then
    echo "MariaDB test refuses to initialize a nonempty or partially initialized data directory" >&2
    exit 12
  else
    mariadb-install-db \
      --datadir="$datadir" \
      --auth-root-authentication-method=normal \
      --skip-test-db
  fi

  umask 077
  : > "$in_progress"

  bootstrap_pid=""
  stop_bootstrap() {
    if [ -n "$bootstrap_pid" ] && kill -0 "$bootstrap_pid" 2>/dev/null; then
      kill -TERM "$bootstrap_pid" 2>/dev/null || true
      wait "$bootstrap_pid" 2>/dev/null || true
    fi
  }
  trap stop_bootstrap EXIT INT TERM

  /usr/sbin/mariadbd \
    --datadir="$datadir" \
    --socket="$socket" \
    --pid-file=/run/mysqld/mysqld-bootstrap.pid \
    --skip-networking \
    --skip-name-resolve &
  bootstrap_pid="$!"

  attempt=0
  until mariadb-admin --socket="$socket" --user="$bootstrap_user" ping --silent >/dev/null 2>&1; do
    attempt=$((attempt + 1))
    if ! kill -0 "$bootstrap_pid" 2>/dev/null; then
      echo "MariaDB credential bootstrap server exited before becoming ready" >&2
      wait "$bootstrap_pid" || true
      exit 11
    fi
    if [ "$attempt" -ge 90 ]; then
      echo "MariaDB credential bootstrap server did not become ready" >&2
      exit 11
    fi
    sleep 1
  done

  if ! mariadb --socket="$socket" --user="$bootstrap_user" <<SQL
DELETE FROM mysql.global_priv WHERE User = 'root' AND Host <> 'localhost';
ALTER USER 'root'@'localhost' IDENTIFIED BY '${root_password}';
CREATE DATABASE dhi_contract CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'dhi_app'@'%' IDENTIFIED BY '${app_password}';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, DROP, ALTER, INDEX, REFERENCES
  ON dhi_contract.* TO 'dhi_app'@'%';
DROP USER IF EXISTS 'mysql'@'localhost';
FLUSH PRIVILEGES;
SHUTDOWN;
SQL
  then
    echo "MariaDB credential bootstrap failed" >&2
    exit 10
  fi

  if ! wait "$bootstrap_pid"; then
    echo "MariaDB credential bootstrap server did not stop cleanly" >&2
    exit 11
  fi
  bootstrap_pid=""
  mv "$in_progress" "$marker"
  trap - EXIT INT TERM
fi

exec /usr/sbin/mariadbd \
  --datadir="$datadir" \
  --socket="$socket" \
  --pid-file=/run/mysqld/mysqld.pid \
  --bind-address=0.0.0.0 \
  --port=3306 \
  --skip-name-resolve
