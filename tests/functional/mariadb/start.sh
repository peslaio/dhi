#!/bin/sh
set -eu

datadir=/var/lib/mysql
socket=/run/mysqld/mysqld.sock

mkdir -p "$datadir" /run/mysqld /var/log/mysql
if [ ! -d "$datadir/mysql" ]; then
  mariadb-install-db \
    --datadir="$datadir" \
    --auth-root-authentication-method=normal \
    --skip-test-db
fi

exec /usr/sbin/mariadbd \
  --datadir="$datadir" \
  --socket="$socket" \
  --pid-file=/run/mysqld/mysqld.pid \
  --bind-address=0.0.0.0 \
  --port=3306 \
  --skip-name-resolve \
  --skip-grant-tables
