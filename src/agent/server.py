from __future__ import annotations

# JSON 解析与序列化
import json
# 读取端口环境变量
import os
# 内置 HTTP 服务
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
# 类型标注
from typing import Any


# 处理 HTTP 请求的最小 Handler
class _Handler(BaseHTTPRequestHandler):
    # 统一输出 JSON 响应
    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    # 处理 POST 请求
    def do_POST(self) -> None:  # noqa: N802
        # 只暴露 /invocations 入口
        if self.path != "/invocations":
            self._send_json(404, {"message": "not_found"})
            return

        # 读取请求体
        content_length = int(self.headers.get("Content-Length", "0"))
        body_raw = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            body_obj = json.loads(body_raw.decode("utf-8"))
        except Exception:
            self._send_json(400, {"message": "invalid_json"})
            return

        # 延迟导入业务入口，启动时更轻量，错误信息更直接
        try:
            from agent.app import invocations
        except Exception as exc:  # noqa: BLE001
            self._send_json(500, {"error": "startup_import_error", "detail": str(exc)})
            return

        # 将 HTTP body 交给业务入口处理
        response = invocations({"body": body_obj})
        status = int(response.get("statusCode", 200))
        body = response.get("body", "{}")

        # 兼容 body 为字符串/字典/其他类型
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

    # 处理健康检查请求
    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/", "/health", "/healthz", "/ready", "/readyz", "/ping"):
            self._send_json(200, {"ok": True})
            return
        self._send_json(404, {"message": "not_found"})

    # 关闭默认 access log，避免日志噪音
    def log_message(self, format: str, *args: object) -> None:
        return


# 进程入口：启动 HTTP 服务
def main() -> None:
    host = "0.0.0.0"
    port = int(os.getenv("PORT", "8080"))
    print(f"agent server starting on {host}:{port}", flush=True)
    server = ThreadingHTTPServer((host, port), _Handler)
    try:
        server.serve_forever()
    except Exception as exc:  # noqa: BLE001
        print(f"agent server crashed: {exc}", flush=True)
        raise


if __name__ == "__main__":
    main()
