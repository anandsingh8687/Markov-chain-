"""Local retrying relay in front of the RunPod HTTP proxy.

The RunPod proxy occasionally answers 404 and cuts requests at 100 s (524). The official harness
(LiteLLM + ModelRetryPlugin) does not retry those, and any model error there ends the session and
drops the patch, which would count test-infrastructure noise as agent failures. Point the harness at
http://127.0.0.1:PORT/v1 and this relay forwards each request, retrying transient failures.

usage: python gemma_agent/gpu/relay.py --upstream https://<pod>-8000.proxy.runpod.net --port 18000
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

RETRY = {404, 408, 429, 500, 502, 503, 504, 520, 522, 524}


def make_handler(upstream: str, attempts: int):
    class Relay(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):  # keep the harness output clean
            pass

        def _forward(self, method: str) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else None
            headers = {k: v for k, v in self.headers.items()
                       if k.lower() in ("authorization", "content-type", "accept")}
            headers["User-Agent"] = "gemma-agent-relay/1.0"
            status, data, ctype = 502, b'{"error": "relay: no attempt made"}', "application/json"
            for i in range(attempts):
                req = urllib.request.Request(upstream + self.path, data=body, method=method, headers=headers)
                try:
                    with urllib.request.urlopen(req, timeout=900) as resp:
                        status, data = resp.status, resp.read()
                        ctype = resp.headers.get("Content-Type", "application/json")
                    break
                except urllib.error.HTTPError as exc:
                    status, data = exc.code, exc.read()
                    ctype = exc.headers.get("Content-Type", "application/json") if exc.headers else ctype
                    if exc.code not in RETRY:
                        break
                except Exception as exc:  # noqa: BLE001 - timeouts, resets
                    status, data = 504, ('{"error": "relay: %s"}' % str(exc)[:200].replace('"', "'")).encode()
                sys.stderr.write("relay retry %d after %s\n" % (i + 1, status))
                time.sleep(min(30, 2 * (i + 1)))
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            self._forward("POST")

        def do_GET(self):
            self._forward("GET")

    return Relay


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--upstream", required=True, help="https://<pod>-8000.proxy.runpod.net (no /v1)")
    ap.add_argument("--port", type=int, default=18000)
    ap.add_argument("--attempts", type=int, default=10)
    a = ap.parse_args()
    ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(a.upstream.rstrip("/"), a.attempts)).serve_forever()


if __name__ == "__main__":
    main()
