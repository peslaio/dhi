#!/bin/sh
set -eu

attempt=0
until mongosh --quiet --host app --port 27017 \
  --eval='quit(db.adminCommand({ ping: 1 }).ok ? 0 : 1)' >/dev/null 2>&1; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 90 ]; then
    echo "MongoDB did not become ready" >&2
    exit 11
  fi
  sleep 1
done

if ! mongosh --quiet --host app --port 27017 --eval='
  const database = db.getSiblingDB("dhi_contract");
  database.probe.deleteMany({});
  database.probe.insertOne({ _id: 1, value: "mongodb-app-ok" });
  const document = database.probe.findOne({ _id: 1 });
  if (!document || document.value !== "mongodb-app-ok") {
    quit(1);
  }
  print("mongodb-app-ok");
'; then
  echo "MongoDB document write/read assertion failed" >&2
  exit 10
fi
