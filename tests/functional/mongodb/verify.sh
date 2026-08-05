#!/bin/sh
set -eu

secret=/run/secrets/mongodb-app-password
lifecycle_phase="${DHI_LIFECYCLE_PHASE:-}"
case "$lifecycle_phase" in
  initial|restart)
    ;;
  *)
    echo "MongoDB lifecycle phase must be exactly initial or restart" >&2
    exit 12
    ;;
esac
DHI_MONGODB_LIFECYCLE_PHASE="$lifecycle_phase"
export DHI_MONGODB_LIFECYCLE_PHASE

if [ ! -f "$secret" ] || [ ! -r "$secret" ]; then
  echo "MongoDB application password fixture is missing or unreadable" >&2
  exit 12
fi
app_password="$(cat "$secret")"
if [ -z "$app_password" ]; then
  echo "MongoDB application password fixture is empty" >&2
  exit 12
fi

export HOME=/tmp
app_uri='mongodb://app:27017/dhi_contract?directConnection=true'

app_mongosh() {
  /usr/bin/mongosh --quiet --norc "$app_uri" \
    --username=dhi_app \
    --password="$app_password" \
    --authenticationDatabase=dhi_contract \
    "$@"
}

attempt=0
until app_mongosh \
  --eval='quit(db.adminCommand({ ping: 1 }).ok === 1 && db.hello().isWritablePrimary === true ? 0 : 1)' \
  >/dev/null 2>&1; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 90 ]; then
    echo "MongoDB did not become ready as an authenticated writable replica-set primary" >&2
    exit 11
  fi
  sleep 1
done

if /usr/bin/mongosh --quiet --norc "$app_uri" \
  --username=dhi_app \
  --password=definitely-wrong \
  --authenticationDatabase=dhi_contract \
  --eval='db.adminCommand({ ping: 1 })' >/tmp/mongodb-wrong-auth.log 2>&1; then
  echo "MongoDB accepted an incorrect application password" >&2
  exit 10
fi
echo "MongoDB rejected an incorrect application password as expected"
export DHI_MONGODB_WRONG_PASSWORD_REJECTED=1

if ! app_mongosh /usr/local/bin/mongodb-verify.js; then
  echo "MongoDB authenticated replica-set CRUD/index/transaction contract failed" >&2
  exit 10
fi
