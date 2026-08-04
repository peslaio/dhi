#!/bin/sh
set -eu

export RABBITMQ_CONFIG_FILE=/etc/rabbitmq/rabbitmq
export RABBITMQ_ENABLED_PLUGINS_FILE=/var/lib/rabbitmq/enabled_plugins
export RABBITMQ_LOGS=-
export RABBITMQ_SASL_LOGS=-

if [ -e /var/lib/rabbitmq/.erlang.cookie ]; then
    echo "source image must not contain a baked Erlang cookie" >&2
    exit 10
fi

rabbitmq-plugins enable --offline rabbitmq_management
exec /usr/lib/rabbitmq/bin/rabbitmq-server
