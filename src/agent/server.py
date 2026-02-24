from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class _Handler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/invocations":
            self._send_json(404, {"message": "not_found"})
            return
        content_length = int(self.headers.get("Content-Length", "0"))
        body_raw = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            body_obj = json.loads(body_raw.decode("utf-8"))
        except Exception:
            self._send_json(400, {"message": "invalid_json"})
            return

        try:
            from agent.app import invocations
        except Exception as exc:  # noqa: BLE001
            self._send_json(500, {"error": "startup_import_error", "detail": str(exc)})
            return

        response = invocations({"body": body_obj})
        status = int(response.get("statusCode", 200))
        body = response.get("body", "{}")
        if isinstance(body, str):
            try:
                payload = json.loads(body)
            except Exception:
                payload = {"raw": body}
        elif isinstance(body, dict):
            payload = body
        else:
            payload = {"raw": str(body)}
        self._send_json(status, payload)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._send_json(200, {"ok": True})
            return
        self._send_json(404, {"message": "not_found"})

    def log_message(self, format: str, *args: object) -> None:
        # Keep logs minimal; runtime platform already captures stdout/stderr.
        return


def main() -> None:
    host = "0.0.0.0"
    port = int(os.getenv("PORT", "8080"))
    print(f"agent server starting on {host}:{port}", flush=True)
    server = ThreadingHTTPServer((host, port), _Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
