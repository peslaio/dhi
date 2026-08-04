#!/bin/sh
set -eu

export RABBITMQ_CONFIG_FILE=/etc/rabbitmq/rabbitmq
export RABBITMQ_ENABLED_PLUGINS_FILE=/var/lib/rabbitmq/enabled_plugins

rabbitmq-plugins enable --offline rabbitmq_management
exec /usr/sbin/rabbitmq-server
