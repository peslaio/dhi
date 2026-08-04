#!/usr/bin/env python3
import base64
import json
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


class AssertionFailure(RuntimeError):
    pass


class ReadinessFailure(RuntimeError):
    pass


HOST = "app"
PORT = 15672
USERNAME = "dhi_app"
VHOST = "dhi"
PASSWORD_FILE = pathlib.Path("/run/secrets/rabbitmq-app-password")


def read_password():
    try:
        password = PASSWORD_FILE.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise AssertionFailure(
            f"RabbitMQ application password fixture is missing or unreadable: {error}"
        ) from error
    if not password:
        raise AssertionFailure("RabbitMQ application password fixture is empty")
    return password


def encode_path(value):
    return urllib.parse.quote(value, safe="")


def request(path, username, password, method="GET", payload=None):
    credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
    headers = {
        "Authorization": f"Basic {credentials}",
        "Content-Type": "application/json",
    }
    body = None if payload is None else json.dumps(payload).encode()
    operation = urllib.request.Request(
        f"http://{HOST}:{PORT}{path}",
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(operation, timeout=3) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", errors="replace")


def decode_json(body, description):
    try:
        return json.loads(body)
    except json.JSONDecodeError as error:
        raise AssertionFailure(f"{description} returned invalid JSON") from error


def wait_until(description, operation, timeout=180):
    deadline = time.monotonic() + timeout
    last_error = "no attempt completed"
    while time.monotonic() < deadline:
        try:
            result = operation()
            if result:
                return result
            last_error = "condition was not yet true"
        except (OSError, TimeoutError, urllib.error.URLError) as error:
            last_error = str(error)
        time.sleep(1)
    raise ReadinessFailure(f"{description} did not become ready: {last_error}")


def require_status(status, expected, description):
    if status not in expected:
        raise AssertionFailure(
            f"{description} returned HTTP {status}; expected one of {sorted(expected)}"
        )


def main():
    password = read_password()

    def authenticated_overview():
        status, _ = request("/api/overview", USERNAME, password)
        return status == 200

    wait_until("authenticated RabbitMQ management API", authenticated_overview)

    wrong_status, _ = request("/api/overview", USERNAME, "definitely-wrong")
    require_status(wrong_status, {401, 403}, "wrong-password request")
    print("RabbitMQ rejected an incorrect application password as expected")

    guest_status, _ = request("/api/overview", "guest", "guest")
    require_status(guest_status, {401, 403}, "remote guest request")
    print("RabbitMQ rejected remote guest access as expected")

    forbidden_status, _ = request(
        "/api/vhosts/dhi-forbidden", USERNAME, password, method="PUT", payload={}
    )
    if forbidden_status in {201, 204}:
        raise AssertionFailure(
            "RabbitMQ application user unexpectedly obtained vhost-administration privileges"
        )
    print("RabbitMQ application user was denied vhost administration as expected")

    vhost = encode_path(VHOST)
    exchange_name = "dhi.exchange"
    queue_name = "dhi.contract"
    marker_queue_name = "dhi.persistence"
    routing_key = "dhi.route"
    marker_routing_key = "dhi.persistence.route"
    exchange = encode_path(exchange_name)
    queue = encode_path(queue_name)
    marker_queue = encode_path(marker_queue_name)

    exchange_path = f"/api/exchanges/{vhost}/{exchange}"
    queue_path = f"/api/queues/{vhost}/{queue}"
    marker_queue_path = f"/api/queues/{vhost}/{marker_queue}"

    def assert_durable_exchange(body, description):
        state = decode_json(body, description)
        if (
            state.get("type") != "direct"
            or state.get("durable") is not True
            or state.get("auto_delete") is not False
        ):
            raise AssertionFailure(
                f"{description} did not retain durable direct-exchange settings"
            )

    def assert_durable_queue(body, description):
        state = decode_json(body, description)
        if state.get("durable") is not True or state.get("auto_delete") is not False:
            raise AssertionFailure(
                f"{description} did not retain durable, non-auto-delete settings"
            )
        return state

    def marker_message_is_ready():
        status, body = request(marker_queue_path, USERNAME, password)
        if status != 200:
            return False
        state = decode_json(body, "lifecycle-marker queue-depth inspection")
        message_count = state.get("messages") or 0
        ready_count = state.get("messages_ready") or 0
        if message_count > 1 or ready_count > 1:
            raise AssertionFailure(
                "RabbitMQ lifecycle-marker queue contains duplicate messages"
            )
        return message_count == 1 and ready_count == 1

    def verify_requeued_marker(context):
        try:
            wait_until(
                f"{context} lifecycle-marker visibility",
                marker_message_is_ready,
                timeout=60,
            )
        except ReadinessFailure as error:
            raise AssertionFailure(
                f"RabbitMQ {context} did not expose exactly one durable lifecycle marker"
            ) from error
        status, body = request(
            f"{marker_queue_path}/get",
            USERNAME,
            password,
            method="POST",
            payload={
                "count": 1,
                "ackmode": "ack_requeue_true",
                "encoding": "auto",
                "truncate": 50000,
            },
        )
        require_status(status, {200}, f"{context} lifecycle-marker consume")
        messages = decode_json(body, f"{context} lifecycle-marker consume")
        if (
            len(messages) != 1
            or messages[0].get("payload") != "rabbitmq-persistence-v1"
            or messages[0].get("properties", {}).get("delivery_mode") != 2
        ):
            raise AssertionFailure(
                f"RabbitMQ {context} returned the wrong durable lifecycle marker"
            )
        wait_until(
            f"{context} lifecycle-marker requeue",
            marker_message_is_ready,
            timeout=60,
        )

    exchange_status, exchange_body = request(exchange_path, USERNAME, password)
    queue_status, queue_body = request(queue_path, USERNAME, password)
    marker_status, marker_body = request(marker_queue_path, USERNAME, password)
    persisted_statuses = (exchange_status, queue_status, marker_status)

    if persisted_statuses == (404, 404, 404):
        lifecycle_phase = "initial"
        print("RabbitMQ lifecycle resources are absent on the fresh data volume as expected")
    elif persisted_statuses == (200, 200, 200):
        lifecycle_phase = "restart"
        assert_durable_exchange(exchange_body, "persisted exchange")
        contract_state = assert_durable_queue(queue_body, "persisted contract queue")
        assert_durable_queue(marker_body, "persisted lifecycle-marker queue")
        if (contract_state.get("messages") or 0) != 0:
            raise AssertionFailure(
                "RabbitMQ restart found an unexpected message in the contract queue"
            )
        verify_requeued_marker("restart")
        print(
            "RabbitMQ verified the durable exchange, queues, and persistent marker "
            "before idempotent declarations"
        )
    else:
        raise AssertionFailure(
            "RabbitMQ lifecycle resources are inconsistent before declarations: "
            f"exchange={exchange_status} contract_queue={queue_status} "
            f"marker_queue={marker_status}"
        )

    exchange_payload = {
        "type": "direct",
        "durable": True,
        "auto_delete": False,
        "internal": False,
        "arguments": {},
    }
    for attempt in ("initial", "idempotent"):
        status, _ = request(
            exchange_path,
            USERNAME,
            password,
            method="PUT",
            payload=exchange_payload,
        )
        require_status(status, {201, 204}, f"{attempt} durable exchange declaration")

    queue_payload = {"durable": True, "auto_delete": False, "arguments": {}}
    for declared_queue, description in (
        (queue, "contract queue"),
        (marker_queue, "lifecycle-marker queue"),
    ):
        for attempt in ("initial", "idempotent"):
            status, _ = request(
                f"/api/queues/{vhost}/{declared_queue}",
                USERNAME,
                password,
                method="PUT",
                payload=queue_payload,
            )
            require_status(
                status, {201, 204}, f"{attempt} durable {description} declaration"
            )

    for bound_queue, bound_key, description in (
        (queue, routing_key, "contract queue binding"),
        (marker_queue, marker_routing_key, "lifecycle-marker queue binding"),
    ):
        status, _ = request(
            f"/api/bindings/{vhost}/e/{exchange}/q/{bound_queue}",
            USERNAME,
            password,
            method="POST",
            payload={"routing_key": bound_key, "arguments": {}},
        )
        require_status(status, {201, 204}, description)

    status, body = request(queue_path, USERNAME, password)
    require_status(status, {200}, "durable queue inspection")
    assert_durable_queue(body, "durable queue inspection")

    status, body = request(
        f"/api/exchanges/{vhost}/{exchange}/publish",
        USERNAME,
        password,
        method="POST",
        payload={
            "properties": {"delivery_mode": 2, "content_type": "text/plain"},
            "routing_key": routing_key,
            "payload": "rabbitmq-persistent-ok",
            "payload_encoding": "string",
        },
    )
    require_status(status, {200}, "persistent publish")
    if decode_json(body, "persistent publish").get("routed") is not True:
        raise AssertionFailure("RabbitMQ did not route the persistent message")

    def contract_message_is_ready():
        status, body = request(queue_path, USERNAME, password)
        if status != 200:
            return False
        return (decode_json(body, "queue depth inspection").get("messages_ready") or 0) >= 1

    wait_until("persistent message visibility", contract_message_is_ready, timeout=60)

    get_path = f"/api/queues/{vhost}/{queue}/get"
    requeue_payload = {
        "count": 1,
        "ackmode": "ack_requeue_true",
        "encoding": "auto",
        "truncate": 50000,
    }
    status, body = request(
        get_path, USERNAME, password, method="POST", payload=requeue_payload
    )
    require_status(status, {200}, "requeue consume")
    messages = decode_json(body, "requeue consume")
    if (
        len(messages) != 1
        or messages[0].get("payload") != "rabbitmq-persistent-ok"
        or messages[0].get("properties", {}).get("delivery_mode") != 2
    ):
        raise AssertionFailure("RabbitMQ requeue consume returned the wrong persistent message")
    wait_until("requeued message visibility", contract_message_is_ready, timeout=60)

    requeue_payload["ackmode"] = "ack_requeue_false"
    status, body = request(
        get_path, USERNAME, password, method="POST", payload=requeue_payload
    )
    require_status(status, {200}, "acknowledged consume")
    messages = decode_json(body, "acknowledged consume")
    if len(messages) != 1 or messages[0].get("payload") != "rabbitmq-persistent-ok":
        raise AssertionFailure("RabbitMQ acknowledged consume returned the wrong message")

    def queue_is_empty():
        status, body = request(queue_path, USERNAME, password)
        if status != 200:
            return False
        queue_depth = decode_json(body, "acknowledged queue-depth inspection")
        return (queue_depth.get("messages") or 0) == 0

    wait_until("acknowledged queue drain", queue_is_empty, timeout=60)

    status, body = request(
        f"/api/exchanges/{vhost}/{exchange}/publish",
        USERNAME,
        password,
        method="POST",
        payload={
            "properties": {"delivery_mode": 2},
            "routing_key": "dhi.missing",
            "payload": "must-not-route",
            "payload_encoding": "string",
        },
    )
    require_status(status, {200}, "unroutable publish")
    if decode_json(body, "unroutable publish").get("routed") is not False:
        raise AssertionFailure("RabbitMQ unexpectedly routed a message without a binding")

    forbidden_queue = encode_path("forbidden.contract")
    status, _ = request(
        f"/api/queues/{vhost}/{forbidden_queue}",
        USERNAME,
        password,
        method="PUT",
        payload=queue_payload,
    )
    if status in {201, 204}:
        raise AssertionFailure(
            "RabbitMQ application user configured a queue outside its permission pattern"
        )
    print("RabbitMQ application permissions rejected an out-of-scope queue as expected")

    if lifecycle_phase == "initial":
        status, body = request(
            f"{exchange_path}/publish",
            USERNAME,
            password,
            method="POST",
            payload={
                "properties": {"delivery_mode": 2, "content_type": "text/plain"},
                "routing_key": marker_routing_key,
                "payload": "rabbitmq-persistence-v1",
                "payload_encoding": "string",
            },
        )
        require_status(status, {200}, "lifecycle-marker publish")
        if decode_json(body, "lifecycle-marker publish").get("routed") is not True:
            raise AssertionFailure("RabbitMQ did not route the lifecycle-marker message")
        verify_requeued_marker("initial")

    print(
        "RabbitMQ authenticated durable management-API contract passed: "
        f"phase={lifecycle_phase} exchange=dhi.exchange queue=dhi.contract "
        "delivery_mode=2 requeue=ok ack=ok persistence_marker=ready"
    )
    passed_assertion_ids = [
        "auth.management_ready",
        "auth.wrong_password_rejected",
        "auth.remote_guest_rejected",
        "authorization.vhost_admin_denied",
        "topology.durable_exchange",
        "topology.durable_queues",
        "topology.idempotent_declarations",
        "messaging.persistent_publish",
        "messaging.requeue",
        "messaging.acknowledge",
        "messaging.unroutable",
        "authorization.resource_scope",
        "persistence.lifecycle_marker",
        "state.queue_drained",
    ]
    print(
        "DHI_ASSERTION_SUMMARY "
        + json.dumps(
            {
                "assertions": [
                    {"id": assertion_id, "status": "pass"}
                    for assertion_id in passed_assertion_ids
                ],
                "counts": {"fail": 0, "pass": len(passed_assertion_ids)},
                "outcome": "pass",
                "schemaVersion": 1,
                "suite": "rabbitmq",
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        flush=True,
    )


if __name__ == "__main__":
    try:
        main()
    except AssertionFailure as error:
        print(f"contract assertion failed: {error}", file=sys.stderr)
        raise SystemExit(10)
    except ReadinessFailure as error:
        print(f"contract readiness failed: {error}", file=sys.stderr)
        raise SystemExit(11)
    except Exception as error:
        print(f"contract infrastructure failed: {error}", file=sys.stderr)
        raise SystemExit(14)
