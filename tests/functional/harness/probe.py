#!/usr/bin/env python3
import argparse
import base64
import concurrent.futures
import contextlib
import hashlib
import http.cookiejar
import http.server
import json
import os
import re
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request


class AssertionFailure(RuntimeError):
    pass


class ReadinessFailure(RuntimeError):
    pass


class RedisErrorResponse:
    def __init__(self, message):
        self.message = message

    def __repr__(self):
        return f"RedisErrorResponse({self.message!r})"


class AssertionRecorder:
    def __init__(self, suite):
        self.suite = suite
        self.records = []
        self.ids = set()

    def record(self, assertion_id, status, detail=None):
        if assertion_id in self.ids:
            raise RuntimeError(f"duplicate assertion id: {assertion_id}")
        self.ids.add(assertion_id)
        record = {"id": assertion_id, "status": status}
        if detail:
            record["detail"] = detail
        self.records.append(record)

    def check(self, assertion_id, condition, message):
        if condition:
            self.record(assertion_id, "pass")
            return
        self.record(assertion_id, "fail", message)
        raise AssertionFailure(message)

    def fail(self, assertion_id, message):
        self.record(assertion_id, "fail", message)
        raise AssertionFailure(message)

    def emit(self, outcome, error=None):
        counts = {
            "fail": sum(item["status"] == "fail" for item in self.records),
            "pass": sum(item["status"] == "pass" for item in self.records),
        }
        summary = {
            "assertions": self.records,
            "counts": counts,
            "outcome": outcome,
            "schemaVersion": 1,
            "suite": self.suite,
        }
        if error:
            summary["error"] = error
        print(
            "DHI_ASSERTION_SUMMARY "
            + json.dumps(summary, sort_keys=True, separators=(",", ":")),
            flush=True,
        )


ASSERTIONS = None


def assert_that(assertion_id, condition, message):
    ASSERTIONS.check(assertion_id, condition, message)


def assertion_failure(assertion_id, message):
    ASSERTIONS.fail(assertion_id, message)


def wait_until_ready(operation, description, timeout):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            return operation()
        except ReadinessFailure as exc:
            last_error = exc
            time.sleep(min(1, max(0, deadline - time.monotonic())))
    raise ReadinessFailure(
        f"{description} did not become ready within {timeout}s: {last_error}"
    )


def poll_until(operation, predicate, description, timeout, interval=0.2):
    deadline = time.monotonic() + timeout
    last_value = None
    last_error = None
    while time.monotonic() < deadline:
        try:
            last_value = operation()
            if predicate(last_value):
                return last_value
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            last_error = exc
        time.sleep(min(interval, max(0, deadline - time.monotonic())))
    detail = f"last value: {last_value!r}"
    if last_error is not None:
        detail += f", last error: {last_error}"
    raise AssertionFailure(f"{description} did not converge within {timeout}s ({detail})")


def http_exchange(url, method="GET", body=None, headers=None, timeout=3, opener=None):
    request = urllib.request.Request(
        url,
        data=body,
        headers=headers or {},
        method=method,
    )
    open_request = opener.open if opener is not None else urllib.request.urlopen
    try:
        with open_request(request, timeout=timeout) as response:
            return (
                response.status,
                {key.lower(): value for key, value in response.headers.items()},
                response.read(),
            )
    except urllib.error.HTTPError as error:
        return (
            error.code,
            {key.lower(): value for key, value in error.headers.items()},
            error.read(),
        )


def http_request(url, method="GET", body=None, headers=None, timeout=3):
    status, _, response_body = http_exchange(
        url, method=method, body=body, headers=headers, timeout=timeout
    )
    return status, response_body.decode("utf-8", errors="replace")


def ready_http_request(url):
    try:
        result = http_request(url)
    except (OSError, TimeoutError, urllib.error.URLError) as exc:
        raise ReadinessFailure(str(exc)) from exc
    if result[0] in (502, 503, 504):
        raise ReadinessFailure(f"endpoint returned transient HTTP {result[0]}")
    return result


def command_http(args):
    status, body = wait_until_ready(
        lambda: ready_http_request(args.url),
        f"HTTP endpoint {args.url}",
        args.timeout,
    )
    assert_that("http.ready", True, "HTTP endpoint was not ready")
    assert_that(
        "http.status",
        status == args.status,
        f"expected HTTP {args.status}, received {status}: {body}",
    )
    assert_that(
        "http.body.contains",
        args.contains in body,
        f"response does not contain {args.contains!r}: {body}",
    )
    expected_checks = [item for item in args.checks.split(",") if item]
    if expected_checks:
        payload = parse_json_response("http.runtime.response-json", body.encode())
        assert_that("http.runtime.response-json", True, "runtime response was not JSON")
        observed_checks = payload.get("checks") if isinstance(payload, dict) else None
        exact_checks = (
            isinstance(observed_checks, list)
            and all(isinstance(item, str) for item in observed_checks)
            and len(observed_checks) == len(set(observed_checks))
            and set(observed_checks) == set(expected_checks)
        )
        assert_that(
            "http.runtime.check-set",
            exact_checks,
            f"runtime checks {observed_checks!r} did not match {expected_checks!r}",
        )
        for check_name in expected_checks:
            assert_that(
                f"http.runtime.{check_name}",
                check_name in observed_checks,
                f"runtime check {check_name!r} was not reported",
            )
    print(body)


class ResponseHandler(http.server.BaseHTTPRequestHandler):
    response_body = b""
    identity = "backend"
    control_token = None
    healthy = True
    state_lock = threading.Lock()
    # One request per connection keeps the fixture deterministic when active
    # health checkers close without reading the response body.
    protocol_version = "HTTP/1.0"

    def _send(self, status, body=b"", content_type="text/plain"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-DHI-Backend", self.identity)
        self.end_headers()
        if self.command != "HEAD" and body:
            try:
                self.wfile.write(body)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                # Active health checkers may close as soon as they have parsed
                # the status line. That is not a backend application failure.
                pass

    def _is_healthy(self):
        handler = type(self)
        with handler.state_lock:
            return handler.healthy

    def _echo(self):
        if not self._is_healthy():
            self._send(503, b"backend unhealthy\n")
            return
        length = int(self.headers.get("Content-Length", "0"))
        request_body = self.rfile.read(length) if length else b""
        payload = {
            "body": request_body.decode("utf-8", errors="replace"),
            "header": self.headers.get("X-DHI-Request", ""),
            "identity": self.identity,
            "method": self.command,
            "path": urllib.parse.urlsplit(self.path).path,
            "query": urllib.parse.urlsplit(self.path).query,
        }
        self._send(
            200,
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(),
            "application/json",
        )

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path == "/healthz":
            if self._is_healthy():
                self._send(200, b"healthy\n")
            else:
                self._send(503, b"unhealthy\n")
            return
        if path == "/echo" or path.endswith("/echo"):
            self._echo()
            return
        if not self._is_healthy():
            self._send(503, b"backend unhealthy\n")
            return
        self._send(200, self.response_body)

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path
        if path == "/control":
            if self.control_token is None or self.headers.get("X-DHI-Control") != self.control_token:
                self._send(403, b"forbidden\n")
                return
            length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(length) if length else b"{}"
            try:
                requested = json.loads(raw_body)
            except json.JSONDecodeError:
                self._send(400, b"invalid json\n")
                return
            if not isinstance(requested.get("healthy"), bool):
                self._send(400, b"healthy must be boolean\n")
                return
            handler = type(self)
            with handler.state_lock:
                handler.healthy = requested["healthy"]
                healthy = handler.healthy
            self._send(200, json.dumps({"healthy": healthy}).encode(), "application/json")
            return
        self._echo()

    def log_message(self, format_string, *values):
        print(format_string % values, file=sys.stderr)


def command_serve(args):
    ResponseHandler.response_body = args.body.encode("utf-8")
    ResponseHandler.identity = args.identity
    ResponseHandler.control_token = args.control_token
    ResponseHandler.healthy = True
    server = http.server.ThreadingHTTPServer(("0.0.0.0", args.port), ResponseHandler)
    server.serve_forever()


def url_at(base_url, path):
    return base_url.rstrip("/") + "/" + path.lstrip("/")


def parse_json_response(assertion_id, raw_body):
    try:
        return json.loads(raw_body.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        assertion_failure(assertion_id, f"response is not valid JSON: {exc}")


def command_web(args):
    root_url = url_at(args.base_url, "/")

    def ready():
        try:
            return http_exchange(root_url)
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            raise ReadinessFailure(str(exc)) from exc

    status, headers, body = wait_until_ready(
        ready, f"web endpoint {root_url}", args.timeout
    )
    assert_that("web.ready", True, "web endpoint did not become ready")
    assert_that("web.root.status", status == 200, f"root returned HTTP {status}")
    assert_that(
        "web.root.marker",
        args.marker.encode() in body,
        f"root did not contain {args.marker!r}",
    )
    assert_that(
        "web.root.mime",
        headers.get("content-type", "").lower().startswith("text/html"),
        f"root content type is {headers.get('content-type')!r}",
    )

    head_status, head_headers, head_body = http_exchange(root_url, method="HEAD")
    assert_that("web.head.status", head_status == 200, f"HEAD returned HTTP {head_status}")
    assert_that("web.head.empty-body", head_body == b"", "HEAD returned a response body")
    expected_length = str(len(body))
    assert_that(
        "web.head.content-length",
        head_headers.get("content-length") == expected_length,
        f"HEAD Content-Length {head_headers.get('content-length')!r}, expected {expected_length}",
    )

    range_end = min(3, len(body) - 1)
    range_status, range_headers, range_body = http_exchange(
        root_url, headers={"Range": f"bytes=0-{range_end}"}
    )
    assert_that("web.range.status", range_status == 206, f"range returned HTTP {range_status}")
    assert_that(
        "web.range.body",
        range_body == body[: range_end + 1],
        f"range body {range_body!r} did not match the root prefix",
    )
    assert_that(
        "web.range.header",
        range_headers.get("content-range", "").startswith(f"bytes 0-{range_end}/"),
        f"invalid Content-Range {range_headers.get('content-range')!r}",
    )

    conditional_headers = {}
    if headers.get("etag"):
        conditional_headers["If-None-Match"] = headers["etag"]
    elif headers.get("last-modified"):
        conditional_headers["If-Modified-Since"] = headers["last-modified"]
    assert_that(
        "web.conditional.validator-present",
        bool(conditional_headers),
        "root response contained neither ETag nor Last-Modified",
    )
    conditional_status, _, conditional_body = http_exchange(
        root_url, headers=conditional_headers
    )
    assert_that(
        "web.conditional.not-modified",
        conditional_status == 304 and conditional_body == b"",
        f"conditional request returned HTTP {conditional_status} with {len(conditional_body)} bytes",
    )

    missing_status, _, _ = http_exchange(url_at(args.base_url, "/.dhi-not-found"))
    assert_that("web.missing.status", missing_status == 404, f"missing path returned HTTP {missing_status}")
    traversal_status, _, traversal_body = http_exchange(
        url_at(args.base_url, "/..%2f..%2fetc%2fpasswd")
    )
    assert_that(
        "web.traversal.rejected",
        traversal_status in (400, 403, 404) and b"root:" not in traversal_body,
        f"encoded traversal returned HTTP {traversal_status}: {traversal_body[:120]!r}",
    )

    def concurrent_get(_):
        result_status, _, result_body = http_exchange(root_url)
        return result_status, args.marker.encode() in result_body

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=min(args.concurrency, 16)
    ) as executor:
        results = list(executor.map(concurrent_get, range(args.concurrency)))
    assert_that(
        "web.concurrent.correct",
        len(results) == args.concurrency and all(item == (200, True) for item in results),
        f"concurrent GET results were not all correct: {results}",
    )

    if args.proxy_path:
        proxy_url = url_at(args.base_url, args.proxy_path) + "?case=functional"
        request_body = b'{"message":"proxy-ok"}'

        def proxy_request():
            return http_exchange(
                proxy_url,
                method="POST",
                body=request_body,
                headers={
                    "Content-Type": "application/json",
                    "X-DHI-Request": "request-ok",
                },
            )

        proxy_status, proxy_headers, proxy_body = poll_until(
            proxy_request,
            lambda result: result[0] == 200,
            f"proxy endpoint {proxy_url}",
            min(args.timeout, 30),
        )
        assert_that("web.proxy.status", proxy_status == 200, f"proxy returned HTTP {proxy_status}")
        payload = parse_json_response("web.proxy.json", proxy_body)
        assert_that("web.proxy.json", True, "proxy response was not JSON")
        assert_that(
            "web.proxy.identity",
            payload.get("identity") == args.proxy_identity
            and proxy_headers.get("x-dhi-backend") == args.proxy_identity,
            f"proxy identity mismatch: headers={proxy_headers!r}, body={payload!r}",
        )
        assert_that(
            "web.proxy.forwarding",
            payload.get("method") == "POST"
            and payload.get("path") == "/echo"
            and payload.get("body") == request_body.decode()
            and payload.get("header") == "request-ok"
            and payload.get("query") == "case=functional",
            f"proxy did not preserve request semantics: {payload!r}",
        )

    print("web application contract passed")


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
    if not prefix or not raw_line.endswith(b"\r\n"):
        raise AssertionFailure(f"truncated Redis response line: {prefix + raw_line!r}")
    line = raw_line[:-2]
    if prefix == b"+":
        return line.decode()
    if prefix == b":":
        return int(line)
    if prefix == b"$":
        try:
            length = int(line)
        except ValueError as exc:
            raise AssertionFailure(f"invalid Redis bulk-string length: {line!r}") from exc
        if length == -1:
            return None
        if length < -1:
            raise AssertionFailure(f"invalid Redis bulk-string length: {length}")
        value = stream.read(length)
        if len(value) != length or stream.read(2) != b"\r\n":
            raise AssertionFailure("truncated Redis bulk-string response")
        return value.decode()
    if prefix == b"*":
        try:
            length = int(line)
        except ValueError as exc:
            raise AssertionFailure(f"invalid Redis array length: {line!r}") from exc
        if length == -1:
            return None
        if length < -1:
            raise AssertionFailure(f"invalid Redis array length: {length}")
        return [redis_read(stream) for _ in range(length)]
    if prefix == b"-":
        return RedisErrorResponse(line.decode(errors="replace"))
    raise AssertionFailure(f"unexpected Redis response prefix: {prefix!r}")


def redis_call(client, stream, *parts):
    client.sendall(redis_encode(*parts))
    return redis_read(stream)


@contextlib.contextmanager
def redis_connection(host, port, username=None, password=None):
    client = connect(host, port)
    stream = client.makefile("rb")
    try:
        if password is not None:
            auth_parts = ("AUTH", username, password) if username else ("AUTH", password)
            response = redis_call(client, stream, *auth_parts)
            if response != "OK":
                raise AssertionFailure(f"Redis AUTH failed: {response!r}")
        yield client, stream
    finally:
        stream.close()
        client.close()


def redis_ready(host, port, username=None, password=None):
    try:
        with redis_connection(host, port, username, password) as (client, stream):
            if redis_call(client, stream, "PING") != "PONG":
                raise ReadinessFailure("Redis PING did not return PONG")
    except AssertionFailure as exc:
        raise ReadinessFailure(str(exc)) from exc
    except OSError as exc:
        raise ReadinessFailure(str(exc)) from exc


def command_redis(args):
    wait_until_ready(
        lambda: redis_ready(args.host, args.port, args.username, args.password),
        f"Redis at {args.host}:{args.port}",
        args.timeout,
    )
    assert_that("redis.ready", True, "Redis did not become ready")

    if args.password is not None:
        with redis_connection(args.host, args.port) as (client, stream):
            response = redis_call(client, stream, "PING")
            assert_that(
                "redis.auth.required",
                isinstance(response, RedisErrorResponse) and "NOAUTH" in response.message,
                f"unauthenticated PING was not rejected: {response!r}",
            )
            wrong_auth = (
                ("AUTH", args.username, args.password + "-wrong")
                if args.username
                else ("AUTH", args.password + "-wrong")
            )
            response = redis_call(client, stream, *wrong_auth)
            assert_that(
                "redis.auth.wrong-password",
                isinstance(response, RedisErrorResponse) and "WRONGPASS" in response.message,
                f"wrong Redis password was not rejected: {response!r}",
            )

    increments = max(1, args.concurrency)
    lifecycle_phase = os.environ.get("DHI_LIFECYCLE_PHASE")
    assert_that(
        "redis.lifecycle.phase",
        lifecycle_phase in ("initial", "restart"),
        f"invalid Redis lifecycle phase: {lifecycle_phase!r}",
    )
    with redis_connection(args.host, args.port, args.username, args.password) as (client, stream):
        assert_that("redis.auth.valid", True, "valid Redis authentication failed")
        persistence_marker = redis_call(client, stream, "GET", "dhi:persistence")
        persisted_transaction = redis_call(client, stream, "GET", "dhi:transaction")
        persisted_counter = redis_call(client, stream, "GET", "dhi:counter")
        assert_that(
            "redis.persistence.marker",
            persistence_marker in (None, "redis-persistence-v1"),
            f"unexpected Redis persistence marker: {persistence_marker!r}",
        )
        assert_that(
            "redis.persistence.state",
            lifecycle_phase == "initial"
            and (
                persistence_marker is None
                and persisted_transaction is None
                and persisted_counter is None
            )
            or lifecycle_phase == "restart"
            and (
                persistence_marker == "redis-persistence-v1"
                and persisted_transaction == "2"
                and persisted_counter == str(increments)
            ),
            f"Redis persistence state did not match lifecycle phase {lifecycle_phase!r}",
        )
        assert_that(
            "redis.string.set",
            redis_call(client, stream, "SET", "dhi:string", "redis-ok") == "OK",
            "Redis SET failed",
        )
        assert_that(
            "redis.string.get",
            redis_call(client, stream, "GET", "dhi:string") == "redis-ok",
            "Redis GET returned the wrong value",
        )
        assert_that(
            "redis.ttl.expire-command",
            redis_call(client, stream, "EXPIRE", "dhi:string", 3) == 1,
            "Redis EXPIRE failed",
        )
        ttl = redis_call(client, stream, "TTL", "dhi:string")
        assert_that("redis.ttl.visible", isinstance(ttl, int) and 0 <= ttl <= 3, f"unexpected TTL: {ttl!r}")

        def expired():
            return redis_call(client, stream, "GET", "dhi:string")

        poll_until(expired, lambda value: value is None, "Redis TTL expiration", 7, interval=0.1)
        assert_that("redis.ttl.expired", True, "Redis key did not expire")

        assert_that("redis.transaction.multi", redis_call(client, stream, "MULTI") == "OK", "MULTI failed")
        queued_set = redis_call(client, stream, "SET", "dhi:transaction", 1)
        queued_incr = redis_call(client, stream, "INCR", "dhi:transaction")
        transaction = redis_call(client, stream, "EXEC")
        assert_that(
            "redis.transaction.exec",
            queued_set == "QUEUED" and queued_incr == "QUEUED" and transaction == ["OK", 2],
            f"unexpected Redis transaction result: {queued_set!r}, {queued_incr!r}, {transaction!r}",
        )

        forbidden = redis_call(client, stream, "CONFIG", "GET", "*")
        assert_that(
            "redis.acl.forbidden-admin",
            isinstance(forbidden, RedisErrorResponse) and "NOPERM" in forbidden.message,
            f"ACL did not reject CONFIG: {forbidden!r}",
        )
        wrong_prefix = redis_call(client, stream, "SET", "outside-prefix", "value")
        assert_that(
            "redis.acl.key-prefix",
            isinstance(wrong_prefix, RedisErrorResponse) and "NOPERM" in wrong_prefix.message,
            f"ACL did not reject an out-of-prefix key: {wrong_prefix!r}",
        )
        redis_call(client, stream, "DEL", "dhi:counter")

    def increment(_):
        with redis_connection(args.host, args.port, args.username, args.password) as (client, stream):
            return redis_call(client, stream, "INCR", "dhi:counter")

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(increments, 16)) as executor:
        results = list(executor.map(increment, range(increments)))
    with redis_connection(args.host, args.port, args.username, args.password) as (client, stream):
        final_value = redis_call(client, stream, "GET", "dhi:counter")
    assert_that(
        "redis.concurrent.exact-counter",
        len(set(results)) == increments and final_value == str(increments),
        f"concurrent INCR results={results!r}, final={final_value!r}",
    )
    with redis_connection(args.host, args.port, args.username, args.password) as (client, stream):
        assert_that(
            "redis.persistence.marker-written",
            redis_call(client, stream, "SET", "dhi:persistence", "redis-persistence-v1")
            == "OK",
            "Redis persistence marker could not be written",
        )
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
                raise ReadinessFailure(f"Memcached VERSION returned an invalid response: {response!r}")
    except AssertionFailure as exc:
        raise ReadinessFailure(str(exc)) from exc
    except OSError as exc:
        raise ReadinessFailure(str(exc)) from exc


def memcached_store(client, stream, operation, key, value, exptime=60, cas=None):
    suffix = f" {cas}" if cas is not None else ""
    client.sendall(
        f"{operation} {key} 0 {exptime} {len(value)}{suffix}\r\n".encode()
        + value
        + b"\r\n"
    )
    return memcached_line(stream)


def memcached_get(client, stream, *keys, include_cas=False):
    command = "gets" if include_cas else "get"
    client.sendall(f"{command} {' '.join(keys)}\r\n".encode())
    values = {}
    while True:
        header = memcached_line(stream)
        if header == b"END":
            return values
        fields = header.split()
        expected_fields = 5 if include_cas else 4
        if len(fields) != expected_fields or fields[0] != b"VALUE":
            raise AssertionFailure(f"invalid Memcached value header: {header!r}")
        try:
            length = int(fields[3])
        except ValueError as exc:
            raise AssertionFailure(f"invalid Memcached value length: {fields[3]!r}") from exc
        value = stream.read(length)
        if len(value) != length or stream.read(2) != b"\r\n":
            raise AssertionFailure("truncated Memcached value")
        values[fields[1].decode()] = (value, fields[4].decode() if include_cas else None)


def command_memcached(args):
    wait_until_ready(
        lambda: memcached_ready(args.host, args.port),
        f"Memcached at {args.host}:{args.port}",
        args.timeout,
    )
    assert_that("memcached.ready", True, "Memcached did not become ready")

    with connect(args.host, args.port) as client:
        stream = client.makefile("rb")
        client.sendall(b"version\r\n")
        version = memcached_line(stream)
        assert_that("memcached.version", version.startswith(b"VERSION 1.6."), f"unexpected version: {version!r}")
        restart_marker = memcached_get(client, stream, "dhi-restart-marker")
        assert_that(
            "memcached.restart.empty",
            "dhi-restart-marker" not in restart_marker,
            "Memcached retained an in-memory marker across process restart",
        )

        assert_that(
            "memcached.set",
            memcached_store(client, stream, "set", "dhi-primary", b"memcached-ok") == b"STORED",
            "Memcached SET failed",
        )
        values = memcached_get(client, stream, "dhi-primary")
        assert_that(
            "memcached.get",
            values.get("dhi-primary", (None,))[0] == b"memcached-ok",
            f"Memcached GET returned {values!r}",
        )
        assert_that(
            "memcached.add-existing",
            memcached_store(client, stream, "add", "dhi-primary", b"other") == b"NOT_STORED",
            "Memcached ADD replaced an existing key",
        )
        assert_that(
            "memcached.replace-missing",
            memcached_store(client, stream, "replace", "dhi-missing", b"value") == b"NOT_STORED",
            "Memcached REPLACE created a missing key",
        )
        cas_values = memcached_get(client, stream, "dhi-primary", include_cas=True)
        assert_that(
            "memcached.gets",
            "dhi-primary" in cas_values and cas_values["dhi-primary"][1] is not None,
            f"Memcached GETS returned no CAS token: {cas_values!r}",
        )
        old_value, cas_token = cas_values["dhi-primary"]
        assert_that(
            "memcached.cas-update",
            old_value == b"memcached-ok"
            and memcached_store(client, stream, "cas", "dhi-primary", b"cas-ok", cas=cas_token) == b"STORED",
            "Memcached CAS update failed",
        )
        assert_that(
            "memcached.cas-stale",
            memcached_store(client, stream, "cas", "dhi-primary", b"stale", cas=cas_token) == b"EXISTS",
            "Memcached accepted a stale CAS token",
        )

        memcached_store(client, stream, "set", "dhi-one", b"one")
        memcached_store(client, stream, "set", "dhi-two", b"two")
        values = memcached_get(client, stream, "dhi-one", "dhi-two")
        assert_that(
            "memcached.multiget",
            {key: value[0] for key, value in values.items()} == {"dhi-one": b"one", "dhi-two": b"two"},
            f"Memcached multiget returned {values!r}",
        )

        assert_that(
            "memcached.ttl.store",
            memcached_store(client, stream, "set", "dhi-ttl", b"expires", exptime=1) == b"STORED",
            "Memcached TTL SET failed",
        )

        def ttl_value():
            return memcached_get(client, stream, "dhi-ttl")

        poll_until(ttl_value, lambda values: "dhi-ttl" not in values, "Memcached TTL expiration", 5, interval=0.1)
        assert_that("memcached.ttl.expired", True, "Memcached key did not expire")

        client.sendall(b"stats\r\n")
        stats = {}
        while True:
            line = memcached_line(stream)
            if line == b"END":
                break
            fields = line.split(maxsplit=2)
            if len(fields) == 3 and fields[0] == b"STAT":
                stats[fields[1].decode()] = fields[2].decode()
        assert_that(
            "memcached.stats",
            stats.get("version", "").startswith("1.6.") and int(stats.get("threads", "0")) >= 1,
            f"Memcached stats lacked version/thread evidence: {stats!r}",
        )

        client.sendall(b"definitely-not-a-command\r\n")
        malformed = memcached_line(stream)
        assert_that("memcached.malformed-rejected", malformed == b"ERROR", f"malformed command returned {malformed!r}")

        oversized = b"x" * (1024 * 1024 + 1)
        oversized_response = memcached_store(client, stream, "set", "dhi-too-large", oversized)
        assert_that(
            "memcached.oversized-rejected",
            oversized_response.startswith(b"SERVER_ERROR object too large"),
            f"oversized value returned {oversized_response!r}",
        )

        memcached_store(client, stream, "set", "dhi-counter", b"0")

    increments = max(1, args.concurrency)

    def increment(_):
        with connect(args.host, args.port) as concurrent_client:
            concurrent_stream = concurrent_client.makefile("rb")
            concurrent_client.sendall(b"incr dhi-counter 1\r\n")
            return int(memcached_line(concurrent_stream))

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(increments, 16)) as executor:
        increment_results = list(executor.map(increment, range(increments)))
    with connect(args.host, args.port) as client:
        stream = client.makefile("rb")
        counter_values = memcached_get(client, stream, "dhi-counter")
        final_value = counter_values.get("dhi-counter", (None, None))[0]
        client.sendall(b"delete dhi-primary\r\n")
        deleted = memcached_line(stream)
        missing_after_delete = memcached_get(client, stream, "dhi-primary")
    assert_that(
        "memcached.concurrent.exact-counter",
        len(set(increment_results)) == increments and final_value == str(increments).encode(),
        f"concurrent INCR results={increment_results!r}, final={final_value!r}",
    )
    assert_that(
        "memcached.delete",
        deleted == b"DELETED" and "dhi-primary" not in missing_after_delete,
        f"Memcached DELETE result={deleted!r}, subsequent get={missing_after_delete!r}",
    )
    with connect(args.host, args.port) as client:
        stream = client.makefile("rb")
        marker_stored = memcached_store(
            client, stream, "set", "dhi-restart-marker", b"must-disappear", exptime=0
        )
        marker_values = memcached_get(client, stream, "dhi-restart-marker")
        assert_that(
            "memcached.restart.marker-written",
            marker_stored == b"STORED"
            and marker_values.get("dhi-restart-marker", (None,))[0]
            == b"must-disappear",
            "Memcached restart marker could not be written and read back",
        )
    print("memcached application contract passed")


def rabbitmq_request(args, path, method="GET", payload=None):
    credentials = base64.b64encode(f"{args.username}:{args.password}".encode()).decode()
    headers = {"Authorization": f"Basic {credentials}", "Content-Type": "application/json"}
    body = None if payload is None else json.dumps(payload).encode()
    return http_request(f"http://{args.host}:{args.port}{path}", method=method, body=body, headers=headers)


def rabbitmq_roundtrip(args):
    queue = "dhi-contract"
    encoded_queue = urllib.parse.quote(queue, safe="")
    status, _ = rabbitmq_request(args, f"/api/queues/%2F/{encoded_queue}", method="PUT", payload={"durable": False, "auto_delete": True, "arguments": {}})
    assert_that("rabbitmq.queue.declare", status in (201, 204), f"RabbitMQ queue declaration returned HTTP {status}")
    status, body = rabbitmq_request(args, "/api/exchanges/%2F/amq.default/publish", method="POST", payload={"properties": {}, "routing_key": queue, "payload": "rabbitmq-ok", "payload_encoding": "string"})
    try:
        publish_result = json.loads(body)
    except json.JSONDecodeError as exc:
        assertion_failure("rabbitmq.publish.json", f"RabbitMQ publish returned invalid JSON: {body}: {exc}")
    assert_that("rabbitmq.publish.json", True, "RabbitMQ publish returned invalid JSON")
    assert_that("rabbitmq.publish.routed", status == 200 and publish_result.get("routed"), f"RabbitMQ publish failed: HTTP {status}: {body}")
    status, body = rabbitmq_request(args, f"/api/queues/%2F/{encoded_queue}/get", method="POST", payload={"count": 1, "ackmode": "ack_requeue_false", "encoding": "auto"})
    try:
        messages = json.loads(body)
    except json.JSONDecodeError as exc:
        assertion_failure("rabbitmq.consume.json", f"RabbitMQ consume returned invalid JSON: {body}: {exc}")
    assert_that("rabbitmq.consume.json", True, "RabbitMQ consume returned invalid JSON")
    assert_that("rabbitmq.consume.payload", status == 200 and messages and messages[0].get("payload") == "rabbitmq-ok", f"RabbitMQ consume failed: HTTP {status}: {body}")


def rabbitmq_ready(args):
    try:
        status, body = rabbitmq_request(args, "/api/overview")
    except (OSError, TimeoutError, urllib.error.URLError) as exc:
        raise ReadinessFailure(str(exc)) from exc
    if status != 200:
        raise ReadinessFailure(f"RabbitMQ overview returned HTTP {status}: {body}")


def command_rabbitmq(args):
    wait_until_ready(lambda: rabbitmq_ready(args), f"RabbitMQ management API at {args.host}:{args.port}", args.timeout)
    assert_that("rabbitmq.ready", True, "RabbitMQ did not become ready")
    try:
        rabbitmq_roundtrip(args)
    except (OSError, TimeoutError, urllib.error.URLError) as exc:
        raise AssertionFailure(f"RabbitMQ API failed during contract: {exc}") from exc
    print("rabbitmq application contract passed")


def php_request(base_url, path, method="GET", body=None, headers=None, opener=None):
    return http_exchange(url_at(base_url, path), method=method, body=body, headers=headers, opener=opener)


def command_php(args):
    def ready():
        try:
            status, headers, body = php_request(args.base_url, "/")
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            raise ReadinessFailure(str(exc)) from exc
        if status in (502, 503, 504):
            raise ReadinessFailure(f"PHP frontend returned transient HTTP {status}")
        return status, headers, body

    status, headers, body = wait_until_ready(ready, f"PHP application at {args.base_url}", args.timeout)
    assert_that("php.ready", True, "PHP application did not become ready")
    inventory = parse_json_response("php.inventory.json", body)
    assert_that("php.inventory.json", True, "PHP inventory was not JSON")
    expected_extensions = [item for item in args.extensions.split(",") if item]
    observed_extensions = inventory.get("extensions") if isinstance(inventory, dict) else None
    exact_extensions = (
        isinstance(observed_extensions, list)
        and all(isinstance(item, str) for item in observed_extensions)
        and len(observed_extensions) == len(set(observed_extensions))
        and set(observed_extensions) == set(expected_extensions)
    )
    assert_that(
        "php.inventory.extension-set",
        exact_extensions,
        f"PHP extensions {observed_extensions!r} did not match {expected_extensions!r}",
    )
    for extension in expected_extensions:
        extension_id = re.sub(r"[^a-z0-9]+", "-", extension.lower()).strip("-")
        assert_that(
            f"php.extension.{extension_id}",
            extension in observed_extensions,
            f"PHP extension {extension!r} was not reported",
        )
    assert_that(
        "php.inventory.runtime",
        status == 200
        and inventory.get("status") == "php-fpm-app-ok"
        and inventory.get("sapi") == "fpm-fcgi"
        and inventory.get("missingExtensions") == [],
        f"invalid PHP runtime inventory: {inventory!r}",
    )
    assert_that(
        "php.inventory.opcache",
        inventory.get("opcacheLoaded") is True,
        f"OPcache was not loaded: {inventory!r}",
    )

    autoload_status, _, autoload_body = php_request(args.base_url, "/api/autoload")
    autoload = parse_json_response("php.autoload.json", autoload_body)
    assert_that("php.autoload.json", True, "autoload response was not JSON")
    assert_that(
        "php.autoload.class",
        autoload_status == 200 and autoload.get("value") == "AUTOLOAD-OK",
        f"autoload endpoint returned HTTP {autoload_status}: {autoload!r}",
    )

    query_status, _, query_body = php_request(args.base_url, "/api/query?name=dhi%20runtime")
    query = parse_json_response("php.query.json", query_body)
    assert_that("php.query.json", True, "query response was not JSON")
    assert_that(
        "php.query.decoding",
        query_status == 200 and query.get("name") == "dhi runtime",
        f"query endpoint returned HTTP {query_status}: {query!r}",
    )

    echo_input = {"message": "php-json-ok", "count": 3}
    echo_status, echo_headers, echo_body = php_request(
        args.base_url,
        "/api/echo",
        method="POST",
        body=json.dumps(echo_input).encode(),
        headers={"Content-Type": "application/json"},
    )
    echo = parse_json_response("php.echo.json", echo_body)
    assert_that("php.echo.json", True, "echo response was not JSON")
    assert_that(
        "php.echo.roundtrip",
        echo_status == 200
        and echo.get("input") == echo_input
        and echo_headers.get("content-type", "").startswith("application/json"),
        f"JSON echo returned HTTP {echo_status}: {echo!r}",
    )

    cookie_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
    session_one_status, _, session_one_body = php_request(args.base_url, "/api/session", opener=opener)
    session_two_status, _, session_two_body = php_request(args.base_url, "/api/session", opener=opener)
    session_one = parse_json_response("php.session.first-json", session_one_body)
    assert_that("php.session.first-json", True, "first session response was not JSON")
    session_two = parse_json_response("php.session.second-json", session_two_body)
    assert_that("php.session.second-json", True, "second session response was not JSON")
    assert_that(
        "php.session.cookie-roundtrip",
        session_one_status == session_two_status == 200
        and session_one.get("count") == 1
        and session_two.get("count") == 2
        and len(cookie_jar) == 1,
        f"session did not persist: first={session_one!r}, second={session_two!r}, cookies={list(cookie_jar)!r}",
    )

    boundary = "dhi-functional-boundary"
    upload_value = b"real-php-upload\n"
    multipart = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"artifact\"; filename=\"artifact.txt\"\r\n"
        "Content-Type: text/plain\r\n\r\n"
    ).encode() + upload_value + f"\r\n--{boundary}--\r\n".encode()
    upload_status, _, upload_body = php_request(
        args.base_url,
        "/api/upload",
        method="POST",
        body=multipart,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    upload = parse_json_response("php.upload.json", upload_body)
    assert_that("php.upload.json", True, "upload response was not JSON")
    assert_that(
        "php.upload.checksum",
        upload_status == 200
        and upload.get("size") == len(upload_value)
        and upload.get("sha256") == hashlib.sha256(upload_value).hexdigest(),
        f"upload returned HTTP {upload_status}: {upload!r}",
    )

    error_status, _, error_body = php_request(args.base_url, "/api/controlled-error")
    controlled_error = parse_json_response("php.error.json", error_body)
    assert_that("php.error.json", True, "controlled error response was not JSON")
    assert_that(
        "php.error.controlled",
        error_status == 422 and controlled_error.get("error") == "controlled-error",
        f"controlled error returned HTTP {error_status}: {controlled_error!r}",
    )
    missing_status, _, _ = php_request(args.base_url, "/api/not-found")
    assert_that("php.missing.status", missing_status == 404, f"missing PHP route returned HTTP {missing_status}")

    def concurrent_query(index):
        result_status, _, result_body = php_request(args.base_url, f"/api/query?name=request-{index}")
        result = json.loads(result_body)
        return result_status, result.get("name")

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(args.concurrency, 8)) as executor:
        query_results = list(executor.map(concurrent_query, range(args.concurrency)))
    assert_that(
        "php.concurrent.correct",
        query_results == [(200, f"request-{index}") for index in range(args.concurrency)],
        f"concurrent PHP results were incorrect: {query_results!r}",
    )
    print("PHP-FPM application contract passed")


def command_haproxy(args):
    echo_url = url_at(args.base_url, "/echo")

    def proxy_echo(method="GET"):
        body = b'{"message":"haproxy-ok"}' if method == "POST" else None
        return http_exchange(
            echo_url,
            method=method,
            body=body,
            headers={"Content-Type": "application/json", "X-DHI-Request": "haproxy-request"},
        )

    def ready():
        try:
            result = proxy_echo()
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            raise ReadinessFailure(str(exc)) from exc
        if result[0] != 200:
            raise ReadinessFailure(f"HAProxy returned HTTP {result[0]}")
        return result

    wait_until_ready(ready, f"HAProxy at {args.base_url}", args.timeout)
    assert_that("haproxy.ready", True, "HAProxy did not become ready")
    post_status, post_headers, post_body = proxy_echo("POST")
    post_payload = parse_json_response("haproxy.forwarding.json", post_body)
    assert_that("haproxy.forwarding.json", True, "HAProxy response was not JSON")
    assert_that(
        "haproxy.forwarding.request",
        post_status == 200
        and post_payload.get("method") == "POST"
        and post_payload.get("path") == "/echo"
        and post_payload.get("body") == '{"message":"haproxy-ok"}'
        and post_payload.get("header") == "haproxy-request"
        and post_headers.get("x-dhi-backend") in {args.identity_a, args.identity_b},
        f"HAProxy did not preserve request semantics: HTTP {post_status}, {post_payload!r}",
    )

    def identity_request():
        status, _, body = proxy_echo()
        if status != 200:
            return status, None
        try:
            return status, json.loads(body).get("identity")
        except json.JSONDecodeError:
            return status, None

    identities = {identity_request()[1] for _ in range(8)}
    assert_that(
        "haproxy.balance.backends",
        identities == {args.identity_a, args.identity_b},
        f"HAProxy did not route to both healthy backends: {identities!r}",
    )

    def set_health(backend_url, healthy):
        status, _, body = http_exchange(
            url_at(backend_url, "/control"),
            method="POST",
            body=json.dumps({"healthy": healthy}).encode(),
            headers={"Content-Type": "application/json", "X-DHI-Control": args.control_token},
        )
        if status != 200:
            raise AssertionFailure(f"backend control returned HTTP {status}: {body!r}")

    def identity_sample(count=6):
        return [identity_request() for _ in range(count)]

    controls_changed = False
    try:
        set_health(args.backend_a, False)
        controls_changed = True
        isolated = poll_until(
            identity_sample,
            lambda results: all(result == (200, args.identity_b) for result in results),
            "HAProxy removal of unhealthy backend A",
            10,
        )
        assert_that(
            "haproxy.failover.available",
            all(result == (200, args.identity_b) for result in isolated),
            f"traffic did not stay on backend B after failover: {isolated!r}",
        )

        set_health(args.backend_a, True)
        poll_until(
            identity_sample,
            lambda results: any(result == (200, args.identity_a) for result in results),
            "HAProxy recovery of backend A",
            10,
        )
        assert_that("haproxy.failover.recovery", True, "backend A did not recover")

        set_health(args.backend_a, False)
        set_health(args.backend_b, False)
        def unavailable_sample():
            results = []
            for _ in range(6):
                result_status, result_headers, _ = proxy_echo()
                results.append((result_status, result_headers.get("x-dhi-backend")))
            return results

        unavailable = poll_until(
            unavailable_sample,
            lambda results: all(result == (503, None) for result in results),
            "HAProxy all-backends-unhealthy response",
            10,
        )
        assert_that(
            "haproxy.failover.all-unhealthy",
            all(result == (503, None) for result in unavailable),
            f"all-unhealthy responses were {unavailable!r}",
        )

        set_health(args.backend_a, True)
        set_health(args.backend_b, True)
        poll_until(
            identity_sample,
            lambda results: all(result[0] == 200 for result in results),
            "HAProxy final recovery",
            10,
        )
        assert_that("haproxy.failover.final-recovery", True, "HAProxy did not recover")
    finally:
        if controls_changed:
            for backend_url in (args.backend_a, args.backend_b):
                try:
                    set_health(backend_url, True)
                except Exception as exc:
                    print(f"warning: failed to restore {backend_url}: {exc}", file=sys.stderr)
    print("HAProxy application contract passed")


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
    http_parser.add_argument("--checks", default="")
    http_parser.add_argument("--timeout", type=int, default=90)
    http_parser.set_defaults(handler=command_http)

    web_parser = commands.add_parser("web")
    web_parser.add_argument("--base-url", required=True)
    web_parser.add_argument("--marker", required=True)
    web_parser.add_argument("--proxy-path")
    web_parser.add_argument("--proxy-identity")
    web_parser.add_argument("--concurrency", type=int, default=8)
    web_parser.add_argument("--timeout", type=int, default=90)
    web_parser.set_defaults(handler=command_web)

    serve_parser = commands.add_parser("serve")
    serve_parser.add_argument("--port", type=int, default=8080)
    serve_parser.add_argument("--body", required=True)
    serve_parser.add_argument("--identity", default="backend")
    serve_parser.add_argument("--control-token")
    serve_parser.set_defaults(handler=command_serve)

    redis_parser = commands.add_parser("redis")
    add_network_arguments(redis_parser, 6379)
    redis_parser.add_argument("--username")
    redis_parser.add_argument("--password")
    redis_parser.add_argument("--concurrency", type=int, default=32)
    redis_parser.set_defaults(handler=command_redis)

    memcached_parser = commands.add_parser("memcached")
    add_network_arguments(memcached_parser, 11211)
    memcached_parser.add_argument("--concurrency", type=int, default=32)
    memcached_parser.set_defaults(handler=command_memcached)

    rabbitmq_parser = commands.add_parser("rabbitmq")
    add_network_arguments(rabbitmq_parser, 15672)
    rabbitmq_parser.add_argument("--username", default="guest")
    rabbitmq_parser.add_argument("--password", default="guest")
    rabbitmq_parser.set_defaults(handler=command_rabbitmq)

    php_parser = commands.add_parser("php")
    php_parser.add_argument("--base-url", required=True)
    php_parser.add_argument("--extensions", required=True)
    php_parser.add_argument("--concurrency", type=int, default=8)
    php_parser.add_argument("--timeout", type=int, default=90)
    php_parser.set_defaults(handler=command_php)

    haproxy_parser = commands.add_parser("haproxy")
    haproxy_parser.add_argument("--base-url", required=True)
    haproxy_parser.add_argument("--backend-a", required=True)
    haproxy_parser.add_argument("--backend-b", required=True)
    haproxy_parser.add_argument("--identity-a", default="backend-a")
    haproxy_parser.add_argument("--identity-b", default="backend-b")
    haproxy_parser.add_argument("--control-token", required=True)
    haproxy_parser.add_argument("--timeout", type=int, default=90)
    haproxy_parser.set_defaults(handler=command_haproxy)

    return parser.parse_args()


def execute():
    global ASSERTIONS
    args = parse_args()
    ASSERTIONS = AssertionRecorder(args.command)
    outcome = "pass"
    error = None
    exit_code = 0
    try:
        args.handler(args)
    except AssertionFailure as exc:
        outcome = "fail"
        error = str(exc)
        exit_code = 10
        if not any(item["status"] == "fail" for item in ASSERTIONS.records):
            ASSERTIONS.record("contract.assertion", "fail", error)
        print(f"contract assertion failed: {exc}", file=sys.stderr)
    except ReadinessFailure as exc:
        outcome = "fail"
        error = str(exc)
        exit_code = 11
        ASSERTIONS.record("contract.readiness", "fail", error)
        print(f"contract readiness failed: {exc}", file=sys.stderr)
    except Exception as exc:
        outcome = "error"
        error = str(exc)
        exit_code = 14
        ASSERTIONS.record("contract.infrastructure", "fail", error)
        print(f"contract infrastructure failed: {exc}", file=sys.stderr)
    finally:
        ASSERTIONS.emit(outcome, error)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(execute())
