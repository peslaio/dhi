#!/usr/bin/env python3
import concurrent.futures
import ctypes
import datetime
import gzip
import hashlib
import http.server
import json
import os
import pathlib
import shutil
import signal
import socket
import tempfile
import threading
import urllib.parse
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo


STATE = {"ready": False, "ready_event": threading.Event(), "checks": []}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def run_startup_checks():
    config_path = pathlib.Path(os.environ.get("DHI_CONFIG_PATH", "/app/app-config.json"))
    file_config = json.loads(config_path.read_text(encoding="utf-8"))
    config = {**file_config, "mode": os.environ.get("DHI_APP_MODE", file_config["mode"])}
    require(file_config["mode"] == "file", "file configuration was not loaded")
    require(config["mode"] == "environment", "environment did not override file configuration")
    require(config["label"] == "python-runtime", "unexpected configuration label")
    STATE["checks"].append("config-precedence")

    value = json.loads(json.dumps({"text": "Zażółć ☃", "count": 3}))
    require(value == {"text": "Zażółć ☃", "count": 3}, "JSON round trip failed")
    STATE["checks"].append("json")

    temporary_directory = pathlib.Path(tempfile.mkdtemp(prefix="dhi-python-", dir="/tmp"))
    try:
        temporary_file = temporary_directory / "probe.txt"
        temporary_file.write_text("python-filesystem-ok", encoding="utf-8")
        require(temporary_file.read_text(encoding="utf-8") == "python-filesystem-ok", "temporary file mismatch")
    finally:
        shutil.rmtree(temporary_directory)
    STATE["checks"].append("filesystem-tmp")

    addresses = socket.getaddrinfo("localhost", 8080, type=socket.SOCK_STREAM)
    require(bool(addresses), "localhost DNS lookup returned no addresses")
    STATE["checks"].append("dns")

    digest = hashlib.sha256(b"abc").hexdigest()
    require(digest == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", "SHA-256 mismatch")
    STATE["checks"].append("crypto")

    compressed = gzip.compress(b"python-compression-ok")
    require(gzip.decompress(compressed) == b"python-compression-ok", "gzip round trip failed")
    STATE["checks"].append("compression")

    text = "Zażółć"
    require(text.encode("utf-8").decode("utf-8") == text, "UTF-8 round trip failed")
    utc = datetime.datetime(2020, 1, 1, tzinfo=ZoneInfo("UTC"))
    require(utc.utcoffset() == datetime.timedelta(0), "UTC timezone offset mismatch")
    STATE["checks"].append("encoding-timezone")

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(lambda number: number * number, range(1, 6)))
    require(sum(results) == 55, "thread-pool computation failed")
    STATE["checks"].append("worker-threads")

    process_library = ctypes.CDLL(None)
    process_library.getpid.restype = ctypes.c_int
    require(process_library.getpid() == os.getpid(), "native libc getpid mismatch")
    STATE["checks"].append("native-libc")

    reflected_hash = getattr(hashlib, "sha256")
    require(reflected_hash(b"abc").hexdigest() == digest, "runtime reflection failed")
    STATE["checks"].append("reflection")


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        request_path = urllib.parse.urlsplit(self.path).path
        if request_path == "/internal":
            self.send_json(200, {"status": "python-internal-ok"})
            return
        if request_path != "/":
            self.send_json(404, {"status": "not-found"})
            return
        if not STATE["ready"]:
            STATE["ready_event"].wait(timeout=5)
            if not STATE["ready"]:
                self.send_json(503, {"status": "starting", "checks": STATE["checks"]})
                return
        self.send_json(200, {"status": "python-app-ok", "checks": STATE["checks"]})

    def send_json(self, status, value):
        body = json.dumps(value, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format_string, *values):
        print(format_string % values, flush=True)


def probe_local_http():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open("http://127.0.0.1:8080/internal", timeout=5) as response:
        body = json.loads(response.read().decode("utf-8"))
        require(response.status == 200, "local HTTP probe returned a non-200 status")
        require(body["status"] == "python-internal-ok", "local HTTP probe returned the wrong body")
    try:
        opener.open("http://127.0.0.1:8080/missing", timeout=5)
    except urllib.error.HTTPError as error:
        require(error.code == 404, "routing negative probe returned the wrong status")
    else:
        raise RuntimeError("routing negative probe did not return 404")


def main():
    run_startup_checks()
    server = http.server.ThreadingHTTPServer(("0.0.0.0", 8080), Handler)
    server.daemon_threads = True
    server_thread = threading.Thread(target=server.serve_forever, name="http-server", daemon=True)
    server_thread.start()

    try:
        probe_local_http()
        STATE["checks"].append("local-http")
        STATE["ready"] = True
        STATE["ready_event"].set()
        print("python startup checks passed: " + ",".join(STATE["checks"]), flush=True)

        stop_event = threading.Event()

        def request_stop(_signal_number, _frame):
            STATE["ready"] = False
            STATE["ready_event"].clear()
            stop_event.set()

        signal.signal(signal.SIGTERM, request_stop)
        signal.signal(signal.SIGINT, request_stop)
        stop_event.wait()
    finally:
        STATE["ready"] = False
        STATE["ready_event"].clear()
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)


if __name__ == "__main__":
    main()
