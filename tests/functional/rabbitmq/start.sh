#!/bin/sh
set -eu

export RABBITMQ_CONFIG_FILE=/etc/rabbitmq/rabbitmq
export RABBITMQ_ENABLED_PLUGINS_FILE=/var/lib/rabbitmq/enabled_plugins
export RABBITMQ_LOGS=-
export RABBITMQ_SASL_LOGS=-

password_secret=/run/secrets/rabbitmq-app-password
runtime_config=/run/rabbitmq/rabbitmq.conf

if [ ! -f "$password_secret" ] || [ ! -r "$password_secret" ]; then
    echo "RabbitMQ application password fixture is missing or unreadable" >&2
    exit 12
fi
app_password="$(cat "$password_secret")"
case "$app_password" in
    "")
        echo "RabbitMQ application password fixture must not be empty" >&2
        exit 12
        ;;
    *[!A-Za-z0-9_@%+=:.,-]*)
        echo "RabbitMQ application password fixture contains unsupported fixture characters" >&2
        exit 12
        ;;
esac

umask 077
cat /etc/rabbitmq/rabbitmq.conf > "$runtime_config"
printf 'default_pass = %s\n' "$app_password" >> "$runtime_config"
export RABBITMQ_CONFIG_FILE=/run/rabbitmq/rabbitmq

rabbitmq-plugins enable --offline rabbitmq_management
exec /usr/lib/rabbitmq/bin/rabbitmq-server
