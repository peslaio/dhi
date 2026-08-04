#!/bin/sh
set -eu

datadir=/data/db
marker="$datadir/.dhi-functional-initialized"
root_secret=/run/secrets/mongodb-root-password
app_secret=/run/secrets/mongodb-app-password
key_secret=/run/secrets/mongodb-keyfile
runtime_key=/run/mongodb/dhi-functional-keyfile
replica_set=dhi-rs

read_test_secret() {
  secret_name="$1"
  secret_path="$2"

  if [ ! -f "$secret_path" ] || [ ! -r "$secret_path" ]; then
    echo "MongoDB test $secret_name secret is missing or unreadable: $secret_path" >&2
    exit 12
  fi
  secret_value="$(cat "$secret_path")"
  case "$secret_value" in
    "")
      echo "MongoDB test $secret_name secret must not be empty" >&2
      exit 12
      ;;
    *[!A-Za-z0-9_@%+=:.,-]*)
      echo "MongoDB test $secret_name secret contains unsupported fixture characters" >&2
      exit 12
      ;;
  esac
  printf '%s' "$secret_value"
}

root_password="$(read_test_secret root-password "$root_secret")"
app_password="$(read_test_secret app-password "$app_secret")"
key_value="$(read_test_secret keyfile "$key_secret")"

mkdir -p "$datadir" /run/mongodb /var/log/mongodb
umask 077
printf '%s\n' "$key_value" > "$runtime_key"
chmod 0400 "$runtime_key"

if [ -e "$marker" ] && [ ! -f "$datadir/WiredTiger" ]; then
  echo "MongoDB test data marker exists without a valid WiredTiger data directory" >&2
  exit 12
fi

if [ ! -e "$marker" ]; then
  if [ -f "$datadir/WiredTiger" ] || find "$datadir" -mindepth 1 -maxdepth 1 ! -name .cache -print -quit | grep -q .; then
    echo "MongoDB test refuses to initialize a nonempty or partially initialized data directory" >&2
    exit 12
  fi

  bootstrap_pid=""
  stop_bootstrap() {
    if [ -n "$bootstrap_pid" ] && kill -0 "$bootstrap_pid" 2>/dev/null; then
      kill -TERM "$bootstrap_pid" 2>/dev/null || true
      wait "$bootstrap_pid" 2>/dev/null || true
    fi
  }
  trap stop_bootstrap EXIT INT TERM

  /usr/bin/mongod \
    --dbpath "$datadir" \
    --port 27017 \
    --bind_ip 127.0.0.1 \
    --replSet "$replica_set" &
  bootstrap_pid="$!"

  attempt=0
  until HOME=/tmp /usr/bin/mongosh --quiet --norc \
    'mongodb://127.0.0.1:27017/admin?directConnection=true' \
    --eval='quit(db.adminCommand({ ping: 1 }).ok === 1 ? 0 : 1)' \
    >/dev/null 2>&1; do
    attempt=$((attempt + 1))
    if ! kill -0 "$bootstrap_pid" 2>/dev/null; then
      echo "MongoDB bootstrap server exited before becoming ready" >&2
      wait "$bootstrap_pid" || true
      exit 11
    fi
    if [ "$attempt" -ge 90 ]; then
      echo "MongoDB bootstrap server did not become ready" >&2
      exit 11
    fi
    sleep 1
  done

  if ! HOME=/tmp /usr/bin/mongosh --quiet --norc \
    'mongodb://127.0.0.1:27017/admin?directConnection=true' \
    --eval="
      const initiated = rs.initiate({
        _id: '${replica_set}',
        members: [{ _id: 0, host: 'localhost:27017' }]
      });
      if (initiated.ok !== 1) {
        throw new Error('single-node replica-set initiation failed: ' + tojson(initiated));
      }
    "; then
    echo "MongoDB single-node replica-set initiation failed" >&2
    exit 10
  fi

  attempt=0
  until HOME=/tmp /usr/bin/mongosh --quiet --norc \
    'mongodb://127.0.0.1:27017/admin?directConnection=true' \
    --eval='quit(db.hello().isWritablePrimary === true ? 0 : 1)' \
    >/dev/null 2>&1; do
    attempt=$((attempt + 1))
    if ! kill -0 "$bootstrap_pid" 2>/dev/null; then
      echo "MongoDB bootstrap server exited before replica-set primary election" >&2
      wait "$bootstrap_pid" || true
      exit 11
    fi
    if [ "$attempt" -ge 90 ]; then
      echo "MongoDB single-node replica set did not elect a writable primary" >&2
      exit 11
    fi
    sleep 1
  done

  if ! HOME=/tmp /usr/bin/mongosh --quiet --norc \
    'mongodb://127.0.0.1:27017/admin?directConnection=true' \
    --eval="
      const result = db.getSiblingDB('admin').runCommand({
        createUser: 'dhi_root',
        pwd: '${root_password}',
        roles: [{ role: 'root', db: 'admin' }]
      });
      if (result.ok !== 1) {
        throw new Error('root user bootstrap failed: ' + JSON.stringify(result));
      }
    "; then
    echo "MongoDB root credential bootstrap failed" >&2
    exit 10
  fi

  if ! HOME=/tmp /usr/bin/mongosh --quiet --norc \
    'mongodb://127.0.0.1:27017/admin?directConnection=true' \
    --username=dhi_root \
    --password="$root_password" \
    --authenticationDatabase=admin \
    --eval="
      const result = db.getSiblingDB('dhi_contract').runCommand({
        createUser: 'dhi_app',
        pwd: '${app_password}',
        roles: [{ role: 'readWrite', db: 'dhi_contract' }]
      });
      if (result.ok !== 1) {
        throw new Error('application user bootstrap failed: ' + JSON.stringify(result));
      }
    "; then
    echo "MongoDB application credential bootstrap failed" >&2
    exit 10
  fi

  kill -TERM "$bootstrap_pid"
  if ! wait "$bootstrap_pid"; then
    echo "MongoDB bootstrap server did not stop cleanly" >&2
    exit 11
  fi
  bootstrap_pid=""
  : > "$marker"
  trap - EXIT INT TERM
fi

exec /usr/bin/mongod \
  --config /etc/mongodb/mongodb.conf \
  --replSet "$replica_set" \
  --auth \
  --keyFile "$runtime_key"
