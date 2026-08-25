#!/usr/bin/env python3
"""Chatflow F6 评估素材 — 本地 REST mock 服务（设备维修单 / 客户投诉分流）。

仅评估用（任务书 D1）：不依赖真实外部系统，`python scripts/f6_mock_server.py` 起 8001。
生产环境请接真实系统（见 docs/fde-guide.md「演示用 mock，生产接真实系统」）。

端点（供 REST 能力指向，全部响应 {data: [...]} 数组契约——data_adapter.fetch_rest 兼容）：
  GET  /health                    → 存活检查
  GET  /equipment/status?equipment_id=<code|名称子串>   → 设备状态（faulty/ok + 温度）
  POST /maintenance-orders        → 开维修单（body: {equipment_id, reason}）→ {order_no}
  POST /notify                    → 通知（body: {channel, recipient, message}）→ {ack, notify_id}
  POST /complaints                → 投诉归档（body: {customer, category, vip}）→ {record_id}
控制 / 验证端点（不进 flow，仅脚本/人工用）：
  POST /_control/cancel-order     → 撤单（Saga 补偿：body: {order_no}，幂等）→ {cancelled}
  POST /_control/cancel-notify    → 撤回通知（Saga 补偿：body: {notify_id}，幂等）→ {cancelled}
  POST /_control/equipment        → 设置设备状态（body: {equipment_id, status, temperature}）
  GET  /_state                    → 设备状态 + 调用日志 dump（verify 断言用）
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

HOST = "127.0.0.1"
PORT = 8001

# 默认设备台账（评估素材）：CNC-01 初始故障态，CNC-02 正常
_DEFAULT_EQUIPMENT: dict[str, dict[str, Any]] = {
    "CNC-01": {"status": "faulty", "temperature": 78.5},
    "CNC-02": {"status": "ok", "temperature": 42.0},
}

_LOCK = threading.Lock()


class MockState:
    """线程安全的内存态：设备状态 + 调用日志（验证断言数据源）。"""

    def __init__(self) -> None:
        self.equipment: dict[str, dict[str, Any]] = {
            code: dict(s) for code, s in _DEFAULT_EQUIPMENT.items()
        }
        self.orders: list[dict[str, Any]] = []
        self.notifications: list[dict[str, Any]] = []
        self.complaints: list[dict[str, Any]] = []
        self.cancelled: list[dict[str, Any]] = []  # Saga 补偿日志（撤单/撤通知，验证断言数据源）
        self._seq = 0

    def _next(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}-{self._seq:04d}"

    def resolve_equipment(self, ref: str) -> str | None:
        """按业务编码或名称子串匹配设备（mock 自有台账，评估语义 = 外部系统解析）。"""
        if not ref:
            return None
        for code in self.equipment:
            if code == ref or code in ref or ref in code:
                return code
        return None

    def set_equipment(self, code: str, status: str, temperature: float) -> dict[str, Any]:
        self.equipment[code] = {"status": status, "temperature": float(temperature)}
        return self.equipment[code]

    def status_of(self, code: str) -> dict[str, Any] | None:
        s = self.equipment.get(code)
        return {"equipment_id": code, **s} if s else None

    def create_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        # 设备引用归一化（与 status 端点一致）：外部系统按业务编码建单
        code = self.resolve_equipment(str(payload.get("equipment_id", ""))) or payload.get("equipment_id", "")
        order = {
            "order_no": self._next("WO"),
            "equipment_id": code,
            "reason": payload.get("reason", ""),
            "status": "created",
        }
        self.orders.append(order)
        return order

    def notify(self, payload: dict[str, Any]) -> dict[str, Any]:
        note = {
            "notify_id": self._next("NT"),
            "channel": payload.get("channel", "sms"),
            "recipient": payload.get("recipient", ""),
            "message": payload.get("message", ""),
            "ack": True,
        }
        self.notifications.append(note)
        return note

    def archive_complaint(self, payload: dict[str, Any]) -> dict[str, Any]:
        # vip 兼容字符串形式（模板渲染的 "True"/"False"）与布尔
        vip_raw = payload.get("vip", False)
        if isinstance(vip_raw, str):
            vip = vip_raw.strip().lower() in ("true", "1", "yes")
        else:
            vip = bool(vip_raw)
        rec = {
            "record_id": self._next("CP"),
            "customer": payload.get("customer", ""),
            "category": payload.get("category", "投诉"),
            "vip": vip,
            "status": "archived",
        }
        self.complaints.append(rec)
        return rec

    def cancel_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Saga 补偿端点：按 order_no 撤单（幂等），记录到 cancelled 日志供验证断言。"""
        order_no = str(payload.get("order_no") or "")
        for o in self.orders:
            if o.get("order_no") == order_no:
                o["status"] = "cancelled"
        rec = {"order_no": order_no, "cancelled": True}
        self.cancelled.append(rec)
        return rec

    def cancel_notification(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Saga 补偿端点：按 notify_id 撤回通知（幂等），记录到 cancelled 日志供验证断言。"""
        notify_id = str(payload.get("notify_id") or "")
        for n in self.notifications:
            if n.get("notify_id") == notify_id:
                n["ack"] = False
        rec = {"notify_id": notify_id, "cancelled": True}
        self.cancelled.append(rec)
        return rec

    def dump(self) -> dict[str, Any]:
        return {
            "equipment": {k: dict(v) for k, v in self.equipment.items()},
            "orders": list(self.orders),
            "notifications": list(self.notifications),
            "complaints": list(self.complaints),
            "cancelled": list(self.cancelled),
        }

    def reset(self) -> dict[str, Any]:
        """重置到默认台账 + 清空调用日志（评估脚本每次 setup 前调用，保证断言基线干净）。"""
        self.equipment = {code: dict(s) for code, s in _DEFAULT_EQUIPMENT.items()}
        self.orders = []
        self.notifications = []
        self.complaints = []
        self.cancelled = []
        self._seq = 0
        return self.dump()


STATE = MockState()


def _read_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length") or 0)
    raw = handler.rfile.read(length) if length else b""
    try:
        data = json.loads(raw.decode("utf-8")) if raw else {}
    except json.JSONDecodeError:
        data = {}
    return data if isinstance(data, dict) else {}


def _send(handler: BaseHTTPRequestHandler, code: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _ok(handler: BaseHTTPRequestHandler, data: Any) -> None:
    _send(handler, 200, {"data": data})


class F6Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:  # 安静模式（评估脚本不打日志噪音）
        pass

    # ── GET ─────────────────────────────────────────────────────────────
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        if path == "/health":
            _send(self, 200, {"status": "ok"})
            return
        if path == "/_state":
            _ok(self, STATE.dump())
            return
        if path == "/equipment/status":
            ref = params.get("equipment_id") or params.get("query") or ""
            code = STATE.resolve_equipment(ref)
            if code is None:
                _send(self, 404, {"error": f"equipment not found: {ref!r}"})
                return
            st = STATE.status_of(code)
            _ok(self, [st] if st else [])
            return
        _send(self, 404, {"error": f"unknown path: {path}"})

    # ── POST ────────────────────────────────────────────────────────────
    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        payload = _read_body(self)
        if path == "/_control/reset":
            _ok(self, [STATE.reset()])
            return
        if path == "/_control/equipment":
            code = str(payload.get("equipment_id") or "")
            status = str(payload.get("status") or "ok")
            temp = float(payload.get("temperature") or 0)
            if code not in STATE.equipment:
                _send(self, 404, {"error": f"equipment not found: {code!r}"})
                return
            st = STATE.set_equipment(code, status, temp)
            _ok(self, [st])
            return
        if path == "/_control/cancel-order":
            _ok(self, [STATE.cancel_order(payload)])
            return
        if path == "/_control/cancel-notify":
            _ok(self, [STATE.cancel_notification(payload)])
            return
        if path == "/maintenance-orders":
            order = STATE.create_order(payload)
            _ok(self, [order])
            return
        if path == "/notify":
            note = STATE.notify(payload)
            _ok(self, [note])
            return
        if path == "/complaints":
            rec = STATE.archive_complaint(payload)
            _ok(self, [rec])
            return
        _send(self, 404, {"error": f"unknown path: {path}"})


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), F6Handler)
    print(f"F6 mock server on http://{HOST}:{PORT} (Ctrl-C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("stopped", flush=True)
        server.shutdown()


if __name__ == "__main__":
    main()
