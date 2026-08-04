#!/usr/bin/env python3
import argparse
import base64
import http.server
import json
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


class AssertionFailure(RuntimeError):
    pass


class ReadinessFailure(RuntimeError):
    pass


def wait_until_ready(operation, description, timeout):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            return operation()
        except ReadinessFailure as exc:
            last_error = exc
            time.sleep(1)
    raise ReadinessFailure(
        f"{description} did not become ready within {timeout}s: {last_error}"
    )


def http_request(url, method="GET", body=None, headers=None, timeout=3):
    request = urllib.request.Request(
        url,
        data=body,
        headers=headers or {},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", errors="replace")


def ready_http_request(url):
    try:
        return http_request(url)
    except (OSError, TimeoutError, urllib.error.URLError) as exc:
        raise ReadinessFailure(str(exc)) from exc


def command_http(args):
    status, body = wait_until_ready(
        lambda: ready_http_request(args.url),
        f"HTTP endpoint {args.url}",
        args.timeout,
    )
    if status != args.status:
        raise AssertionFailure(
            f"expected HTTP {args.status}, received {status}: {body}"
        )
    if args.contains not in body:
        raise AssertionFailure(
            f"response does not contain {args.contains!r}: {body}"
        )
    print(body)


class ResponseHandler(http.server.BaseHTTPRequestHandler):
    response_body = b""

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(self.response_body)))
        self.end_headers()
        self.wfile.write(self.response_body)
        self.wfile.flush()

    def log_message(self, format_string, *values):
        print(format_string % values, file=sys.stderr)


def command_serve(args):
    ResponseHandler.response_body = args.body.encode("utf-8")
    server = http.server.ThreadingHTTPServer(("0.0.0.0", args.port), ResponseHandler)
    server.serve_forever()


def connect(host, port):
    return socket.create_connection((host, port), timeout=3)


def redis_encode(*parts):
    payload = [f"*{len(parts)}\r\n".encode()]
    for part in parts:
        value = str(part).encode()
        payload.extend((f"${len(value)}\r\n".encode(), value, b"\r\n"))
    return b"".join(payload)


def redis_read(stream):
    prefix = stream.read(1)
    raw_line = stream.readline()
    if not raw_line.endswith(b"\r\n"):
        raise AssertionFailure(f"truncated Redis response line: {raw_line!r}")
    line = raw_line[:-2]
    if prefix == b"+":
        return line.decode()
    if prefix == b":":
        return int(line)
    if prefix == b"$":
        try:
            length = int(line)
        except ValueError as exc:
            raise AssertionFailure(
                f"invalid Redis bulk-string length: {line!r}"
            ) from exc
        if length == -1:
            return None
        value = stream.read(length)
        if len(value) != length or stream.read(2) != b"\r\n":
            raise AssertionFailure("truncated Redis bulk-string response")
        return value.decode()
    if prefix == b"-":
        raise AssertionFailure(f"Redis error: {line.decode()}")
    raise AssertionFailure(f"unexpected Redis response prefix: {prefix!r}")


def redis_ready(host, port):
    try:
        with connect(host, port) as client:
            stream = client.makefile("rb")
            client.sendall(redis_encode("PING"))
            if redis_read(stream) != "PONG":
                raise ReadinessFailure("Redis PING did not return PONG")
    except AssertionFailure as exc:
        raise ReadinessFailure(str(exc)) from exc
    except OSError as exc:
        raise ReadinessFailure(str(exc)) from exc


def redis_roundtrip(host, port):
    try:
        with connect(host, port) as client:
            stream = client.makefile("rb")
            client.sendall(redis_encode("SET", "dhi-contract", "redis-ok"))
            if redis_read(stream) != "OK":
                raise AssertionFailure("Redis SET failed")
            client.sendall(redis_encode("GET", "dhi-contract"))
            if redis_read(stream) != "redis-ok":
                raise AssertionFailure("Redis GET returned the wrong value")
    except OSError as exc:
        raise AssertionFailure(f"Redis connection failed during contract: {exc}") from exc


def command_redis(args):
    wait_until_ready(
        lambda: redis_ready(args.host, args.port),
        f"Redis at {args.host}:{args.port}",
        args.timeout,
    )
    redis_roundtrip(args.host, args.port)
    print("redis application contract passed")


def memcached_line(stream):
    line = stream.readline()
    if not line.endswith(b"\r\n"):
        raise AssertionFailure(f"truncated Memcached response line: {line!r}")
    return line[:-2]


def memcached_ready(host, port):
    try:
        with connect(host, port) as client:
            stream = client.makefile("rb")
            client.sendall(b"version\r\n")
            response = memcached_line(stream)
            if not response.startswith(b"VERSION "):
                raise ReadinessFailure(
                    f"Memcached VERSION returned an invalid response: {response!r}"
                )
    except AssertionFailure as exc:
        raise ReadinessFailure(str(exc)) from exc
    except OSError as exc:
        raise ReadinessFailure(str(exc)) from exc


def memcached_roundtrip(host, port):
    try:
        with connect(host, port) as client:
            stream = client.makefile("rb")
            value = b"memcached-ok"
            client.sendall(
                f"set dhi-contract 0 60 {len(value)}\r\n".encode()
                + value
                + b"\r\n"
            )
            response = memcached_line(stream)
            if response != b"STORED":
                raise AssertionFailure(f"Memcached SET failed: {response!r}")

            client.sendall(b"get dhi-contract\r\n")
            header = memcached_line(stream)
            fields = header.split()
            if len(fields) != 4 or fields[:2] != [b"VALUE", b"dhi-contract"]:
                raise AssertionFailure(f"Memcached GET header is invalid: {header!r}")
            try:
                length = int(fields[3])
            except ValueError as exc:
                raise AssertionFailure(
                    f"Memcached GET length is invalid: {fields[3]!r}"
                ) from exc
            received = stream.read(length)
            if stream.read(2) != b"\r\n":
                raise AssertionFailure("Memcached GET payload is truncated")
            if memcached_line(stream) != b"END":
                raise AssertionFailure("Memcached GET did not terminate with END")
            if received != value:
                raise AssertionFailure(
                    f"Memcached GET returned {received!r}, expected {value!r}"
                )
    except OSError as exc:
        raise AssertionFailure(
            f"Memcached connection failed during contract: {exc}"
        ) from exc


def command_memcached(args):
    wait_until_ready(
        lambda: memcached_ready(args.host, args.port),
        f"Memcached at {args.host}:{args.port}",
        args.timeout,
    )
    memcached_roundtrip(args.host, args.port)
    print("memcached application contract passed")


def rabbitmq_request(args, path, method="GET", payload=None):
    credentials = base64.b64encode(f"{args.username}:{args.password}".encode()).decode()
    headers = {
        "Authorization": f"Basic {credentials}",
        "Content-Type": "application/json",
    }
    body = None if payload is None else json.dumps(payload).encode()
    return http_request(
        f"http://{args.host}:{args.port}{path}",
        method=method,
        body=body,
        headers=headers,
    )


def rabbitmq_roundtrip(args):
    queue = "dhi-contract"
    encoded_queue = urllib.parse.quote(queue, safe="")
    status, _ = rabbitmq_request(
        args,
        f"/api/queues/%2F/{encoded_queue}",
        method="PUT",
        payload={"durable": False, "auto_delete": True, "arguments": {}},
    )
    if status not in (201, 204):
        raise AssertionFailure(
            f"RabbitMQ queue declaration returned HTTP {status}"
        )

    status, body = rabbitmq_request(
        args,
        "/api/exchanges/%2F/amq.default/publish",
        method="POST",
        payload={
            "properties": {},
            "routing_key": queue,
            "payload": "rabbitmq-ok",
            "payload_encoding": "string",
        },
    )
    try:
        publish_result = json.loads(body)
    except json.JSONDecodeError as exc:
        raise AssertionFailure(
            f"RabbitMQ publish returned invalid JSON: {body}"
        ) from exc
    if status != 200 or not publish_result.get("routed"):
        raise AssertionFailure(
            f"RabbitMQ publish failed: HTTP {status}: {body}"
        )

    status, body = rabbitmq_request(
        args,
        f"/api/queues/%2F/{encoded_queue}/get",
        method="POST",
        payload={"count": 1, "ackmode": "ack_requeue_false", "encoding": "auto"},
    )
    try:
        messages = json.loads(body)
    except json.JSONDecodeError as exc:
        raise AssertionFailure(
            f"RabbitMQ consume returned invalid JSON: {body}"
        ) from exc
    if status != 200 or not messages or messages[0].get("payload") != "rabbitmq-ok":
        raise AssertionFailure(
            f"RabbitMQ consume failed: HTTP {status}: {body}"
        )


def rabbitmq_ready(args):
    try:
        status, body = rabbitmq_request(args, "/api/overview")
    except (OSError, TimeoutError, urllib.error.URLError) as exc:
        raise ReadinessFailure(str(exc)) from exc
    if status != 200:
        raise ReadinessFailure(
            f"RabbitMQ overview returned HTTP {status}: {body}"
        )


def command_rabbitmq(args):
    wait_until_ready(
        lambda: rabbitmq_ready(args),
        f"RabbitMQ management API at {args.host}:{args.port}",
        args.timeout,
    )
    try:
        rabbitmq_roundtrip(args)
    except (OSError, TimeoutError, urllib.error.URLError) as exc:
        raise AssertionFailure(
            f"RabbitMQ API failed during contract: {exc}"
        ) from exc
    print("rabbitmq application contract passed")


def add_network_arguments(parser, default_port):
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=default_port)
    parser.add_argument("--timeout", type=int, default=90)


def parse_args():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)

    http_parser = commands.add_parser("http")
    http_parser.add_argument("--url", required=True)
    http_parser.add_argument("--status", type=int, default=200)
    http_parser.add_argument("--contains", required=True)
    http_parser.add_argument("--timeout", type=int, default=90)
    http_parser.set_defaults(handler=command_http)

    serve_parser = commands.add_parser("serve")
    serve_parser.add_argument("--port", type=int, default=8080)
    serve_parser.add_argument("--body", required=True)
    serve_parser.set_defaults(handler=command_serve)

    redis_parser = commands.add_parser("redis")
    add_network_arguments(redis_parser, 6379)
    redis_parser.set_defaults(handler=command_redis)

    memcached_parser = commands.add_parser("memcached")
    add_network_arguments(memcached_parser, 11211)
    memcached_parser.set_defaults(handler=command_memcached)

    rabbitmq_parser = commands.add_parser("rabbitmq")
    add_network_arguments(rabbitmq_parser, 15672)
    rabbitmq_parser.add_argument("--username", default="guest")
    rabbitmq_parser.add_argument("--password", default="guest")
    rabbitmq_parser.set_defaults(handler=command_rabbitmq)

    return parser.parse_args()


def main():
    args = parse_args()
    args.handler(args)


if __name__ == "__main__":
    try:
        main()
    except AssertionFailure as exc:
        print(f"contract assertion failed: {exc}", file=sys.stderr)
        raise SystemExit(10)
    except ReadinessFailure as exc:
        print(f"contract readiness failed: {exc}", file=sys.stderr)
        raise SystemExit(11)
    except Exception as exc:
        print(f"contract infrastructure failed: {exc}", file=sys.stderr)
        raise SystemExit(14)
