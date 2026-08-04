#!/bin/sh
set -eu

export PATH="/usr/lib/postgresql/15/bin:$PATH"
export PGDATA="${PGDATA:-/var/lib/postgresql/data}"

mkdir -p "$PGDATA" /run/postgresql
if [ ! -s "$PGDATA/PG_VERSION" ]; then
  initdb -D "$PGDATA" --username=postgres --auth-local=trust --auth-host=trust
  printf '%s\n' \
    'host all all 0.0.0.0/0 trust' \
    'host all all ::/0 trust' >> "$PGDATA/pg_hba.conf"
fi

exec postgres -D "$PGDATA" -c listen_addresses='*' -p 5432
