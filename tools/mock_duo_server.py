from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    seen: set[str] = set()

    def do_POST(self) -> None:
        if self.path != "/api/ingest/articles":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length))
        except (ValueError, UnicodeDecodeError):
            self.send_error(400, "JSON invalido")
            return
        key = self.headers.get("Idempotency-Key")
        if not key or payload.get("idempotencyKey") != key:
            self.send_error(400, "Idempotency-Key faltante o inconsistente")
            return
        status = 200 if key in self.seen else 201
        self.seen.add(key)
        body = json.dumps({"ok": True, "duplicate": status == 200}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="Mock local del endpoint de ingesta")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost"}:
        raise SystemExit("Por seguridad, el mock solo puede escuchar en loopback")
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Mock escuchando en http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

