#!/bin/sh
set -eu

export PATH="/usr/lib/postgresql/15/bin:$PATH"
export PGDATA="${PGDATA:-/var/lib/postgresql/data}"
marker="$PGDATA/.dhi-functional-initialized"
superuser_secret=/run/secrets/postgresql-superuser-password
app_secret=/run/secrets/postgresql-app-password

read_test_secret() {
  secret_name="$1"
  secret_path="$2"

  if [ ! -f "$secret_path" ] || [ ! -r "$secret_path" ]; then
    echo "PostgreSQL test $secret_name secret is missing or unreadable: $secret_path" >&2
    exit 12
  fi
  secret_value="$(cat "$secret_path")"
  case "$secret_value" in
    "")
      echo "PostgreSQL test $secret_name secret must not be empty" >&2
      exit 12
      ;;
    *[!A-Za-z0-9_@%+=:.,-]*)
      echo "PostgreSQL test $secret_name secret contains unsupported fixture characters" >&2
      exit 12
      ;;
  esac
  printf '%s' "$secret_value"
}

superuser_password="$(read_test_secret superuser-password "$superuser_secret")"
app_password="$(read_test_secret app-password "$app_secret")"

mkdir -p "$PGDATA" /run/postgresql
if [ -e "$marker" ] && [ ! -s "$PGDATA/PG_VERSION" ]; then
  echo "PostgreSQL test data marker exists without a valid cluster" >&2
  exit 12
fi

if [ ! -e "$marker" ]; then
  if [ -s "$PGDATA/PG_VERSION" ] || find "$PGDATA" -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
    echo "PostgreSQL test refuses to initialize a nonempty or partially initialized data directory" >&2
    exit 12
  fi

  initdb \
    -D "$PGDATA" \
    --username=postgres \
    --pwfile="$superuser_secret" \
    --auth-local=peer \
    --auth-host=scram-sha-256 \
    --data-checksums

  cat > "$PGDATA/pg_hba.conf" <<'EOF'
local all all peer
host all all 0.0.0.0/0 scram-sha-256
host all all ::/0 scram-sha-256
EOF
  cat >> "$PGDATA/postgresql.conf" <<'EOF'
listen_addresses = '*'
password_encryption = 'scram-sha-256'
unix_socket_directories = '/run/postgresql'
EOF

  bootstrap_started=false
  stop_bootstrap() {
    if [ "$bootstrap_started" = true ]; then
      pg_ctl -D "$PGDATA" -m immediate -w stop >/dev/null 2>&1 || true
    fi
  }
  trap stop_bootstrap EXIT INT TERM

  if ! pg_ctl -D "$PGDATA" -w start \
    -o "-c listen_addresses='' -c unix_socket_directories=/run/postgresql"; then
    echo "PostgreSQL credential bootstrap server failed to start" >&2
    exit 11
  fi
  bootstrap_started=true

  if ! psql \
    --no-psqlrc \
    --host=/run/postgresql \
    --username=postgres \
    --dbname=postgres \
    --set=ON_ERROR_STOP=1 \
    --set=app_password="$app_password" <<'SQL'
SELECT 'CREATE ROLE dhi_app LOGIN'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dhi_app')
\gexec
ALTER ROLE dhi_app
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION
  PASSWORD :'app_password';
SELECT 'CREATE DATABASE dhi_contract OWNER dhi_app'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'dhi_contract')
\gexec
SQL
  then
    echo "PostgreSQL application role bootstrap failed" >&2
    exit 10
  fi

  if ! psql \
    --no-psqlrc \
    --host=/run/postgresql \
    --username=postgres \
    --dbname=dhi_contract \
    --set=ON_ERROR_STOP=1 <<'SQL'
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO dhi_app;
ALTER SCHEMA public OWNER TO dhi_app;
SQL
  then
    echo "PostgreSQL application schema bootstrap failed" >&2
    exit 10
  fi

  if ! pg_ctl -D "$PGDATA" -m fast -w stop; then
    echo "PostgreSQL credential bootstrap server did not stop cleanly" >&2
    exit 11
  fi
  bootstrap_started=false
  umask 077
  : > "$marker"
  trap - EXIT INT TERM
fi

exec postgres -D "$PGDATA" -p 5432
