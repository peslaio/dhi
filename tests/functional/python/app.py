#!/usr/bin/env python3
import http.server
import json


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"status": "python-app-ok"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format_string, *values):
        print(format_string % values)


http.server.ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
