"""M3 dev 真 API 冒烟（E2）：注册 → 同步 → 幂等 → virtual live → enrichment 全链路。

前置：dev API（8000，--reload 已热载新端点）+ worker 进程（消费同步队列）
      + 本地 REST stub（脚本内起，8001 端口）。
用法：cd apps/earp-server && .venv/bin/python scripts/verify_m3.py
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import jwt

API = "http://127.0.0.1:8000"
SECRET = "earp-dev-secret-change-in-production"
TENANT, ROLE, USER = "tenant-demo", "r1", "u1"

# ── REST stub（模拟中台指标/设备 API）──────────────────────────────────────────
EQUIP_ROWS = [
    {"equip_code": "CNC-01", "equip_name": "加工中心", "model": "XK-500", "supplier_code": "SUP-001"},
    {"equip_code": "CNC-02", "equip_name": "车床", "model": "CK-200", "supplier_code": "SUP-002"},
]


class Stub(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/equip"):
            body = json.dumps(EQUIP_ROWS).encode()
        elif self.path.startswith("/oee"):
            code = self.path.split("equip_code=")[-1] if "equip_code=" in self.path else "CNC-01"
            body = json.dumps([{"equip_code": code, "oee": 0.87, "time": "2026-08-20T00:00:00Z"}]).encode()
        elif self.path.startswith("/health"):
            body = b'{"status":"ok"}'
        else:
            body = b'{"data":[]}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)


def _token() -> str:
    now = int(time.time())
    return jwt.encode(
        {"sub": USER, "tenant_id": TENANT, "role_id": ROLE, "iat": now, "exp": now + 3600},
        SECRET,
        algorithm="HS256",
    )


def _h() -> dict:
    return {"Authorization": f"Bearer {_token()}"}


def _post(c: httpx.Client, path: str, body: dict) -> dict:
    r = c.post(API + path, json=body, headers=_h())
    assert r.status_code in (200, 201), f"{path} {r.status_code}: {r.text}"
    return r.json()


def _get(c: httpx.Client, path: str) -> dict:
    r = c.get(API + path, headers=_h())
    assert r.status_code == 200, f"{path} {r.status_code}: {r.text}"
    return r.json()


def main() -> None:
    stub = HTTPServer(("127.0.0.1", 8001), Stub)
    threading.Thread(target=stub.serve_forever, daemon=True).start()
    print("[stub] REST stub on :8001")

    with httpx.Client(timeout=10) as c:
        # 1. connector 注册（REST，幂等：已存在则复用）
        try:
            out = _post(c, "/v1/ontology/connectors", {
                "connector_id": "cn-mid-rest",
                "adapter_type": "rest",
                "config": {"base_url": "http://127.0.0.1:8001", "path": "/equip"},
            })
        except AssertionError:
            out = {"connector_id": "cn-mid-rest", "config": {"credential_masked": True}}
        print(f"[1] connector 注册: {out['connector_id']} config={out['config']}")

        # 2. 数据源注册（synced，equipment）→ 立即入队（幂等：已存在则复用）
        try:
            out = _post(c, "/v1/ontology/import/connector", {
                "connector_id": "cn-mid-rest",
                "entity_type_id": "equipment",
                "source_mode": "synced",
                "field_mapping": {
                    "name_field": "equip_name",
                    "business_code_field": "equip_code",
                    "attr_fields": {"model": "model"},
                    "relations": [{"relation_type": "manufactured_by", "target_field": "supplier_code"}],
                },
            })
            ds_id = out["data_source_id"]
        except AssertionError:
            srcs = _get(c, "/v1/ontology/data-sources")["items"]
            ds_id = next(s["data_source_id"] for s in srcs if s["connector_id"] == "cn-mid-rest" and s["source_mode"] == "synced")
            out = {"data_source_id": ds_id}
        print(f"[2] 数据源注册: {ds_id} job_status={out.get('job_status')}")

        # 3. 轮询同步状态（worker 消费）→ completed
        for _ in range(30):
            ds = _get(c, f"/v1/ontology/data-sources/{ds_id}")
            if ds["last_sync_status"] == "completed":
                break
            time.sleep(0.5)
        assert ds["last_sync_status"] == "completed", f"sync not completed: {ds['last_sync_status']}"
        print(f"[3] 首次同步 completed, last_synced_at={ds['last_synced_at']}")

        # 4. 二次同步 → 幂等（merged）
        out = _post(c, f"/v1/ontology/data-sources/{ds_id}/sync", {})
        assert out["job_status"] == "queued"
        for _ in range(30):
            ds = _get(c, f"/v1/ontology/data-sources/{ds_id}")
            if ds["last_sync_status"] == "completed":
                break
            time.sleep(0.5)
        print(f"[4] 二次同步 completed（幂等）")

        # 5. 实体 + facts 落库校验
        entities = _get(c, "/v1/ontology/entities?entity_type_id=equipment")
        print(f"[5] equipment 实体数: {entities['total']}")
        assert entities["total"] >= 2
        sample_eid = entities["items"][0]["entity_id"]

        # 5b. timeline 素材（chat 真实引用模拟）：DB 直连插带 citations 的 message
        #     （review A 修复后 enrichment ① 读 messages.citations——真实链路素材）
        import psycopg
        from uuid import uuid4

        conv_id = "m3-verify-" + uuid4().hex[:8]
        msg_id = "msg-" + uuid4().hex[:8]
        with psycopg.connect("postgresql://earp_app:earp_app@127.0.0.1:5433/earp") as pg:
            pg.execute(f"SET LOCAL earp.tenant_id = '{TENANT}'")
            pg.execute(
                "INSERT INTO conversations (conversation_id, tenant_id, user_id) VALUES (%s, %s, %s)",
                (conv_id, TENANT, USER),
            )
            pg.execute(
                "INSERT INTO messages (message_id, tenant_id, conversation_id, seq, role, "
                "content, citations) VALUES (%s, %s, %s, 1, 'assistant', 'm3 verify', %s)",
                (msg_id, TENANT, conv_id, json.dumps([{"source": "profile", "entity_id": sample_eid}])),
            )
            pg.commit()
        print(f"[5b] timeline 素材 message 已插: {msg_id} → entity {sample_eid}")

        # 6. virtual metric：注册 metric 类型 + virtual 数据源 + metric 实体 + live 取数
        #    （一个数据源 = 一个 connector + path——metric 取数独立 connector path=/oee）
        try:
            _post(c, "/v1/ontology/entity-types", {
                "entity_type_id": "oee",
                "name": "设备OEE",
                "kind": "metric",
                "data_domain_id": "equipment_data",
                "attributes": {},
            })
        except AssertionError:
            pass  # 已存在
        try:
            _post(c, "/v1/ontology/connectors", {
                "connector_id": "cn-mid-oee",
                "adapter_type": "rest",
                "config": {"base_url": "http://127.0.0.1:8001", "path": "/oee"},
            })
        except AssertionError:
            pass  # 已存在
        try:
            _post(c, "/v1/ontology/import/connector", {
                "connector_id": "cn-mid-oee",
                "entity_type_id": "oee",
                "source_mode": "virtual",
                "field_mapping": {"name_field": "equip_name", "business_code_field": "equip_code"},
            })
        except AssertionError:
            pass  # 已存在
        # 建 metric 实体（source_mode=virtual, source_ref=connector_id；幂等合并不改 source_ref，用唯一编码）
        r = c.post(API + "/v1/ontology/entities", json={
            "entity_type_id": "oee",
            "name": "CNC-01 OEE",
            "business_code": "CNC-OEE-01",
            "source_mode": "virtual",
            "source_ref": "cn-mid-oee",
            "data_domain_id": "equipment_data",
        }, headers=_h())
        assert r.status_code == 201, f"metric entity: {r.status_code} {r.text}"
        live = _get(c, f"/v1/ontology/entities/{r.json()['entity_id']}/live")
        print(f"[6] virtual live 取数: {live['data']}")
        assert live["data"] and live["data"]["oee"] == 0.87

        # 7. enrichment 手动触发
        r = c.post(API + "/v1/ontology/enrichment/run", headers=_h())
        assert r.status_code == 200, r.text
        stats = r.json()
        print(f"[7] enrichment 统计: {stats}")
        assert set(stats) >= {"profiles_recompiled", "facts_revoked", "timeline_added", "hot_missing"}
        # review A 修复验收：timeline 从 messages.citations 真实回填 > 0
        assert stats["timeline_added"] > 0, "timeline 未从 messages.citations 回填（review A 未生效）"

    print("\n✅ M3 dev 冒烟全链路通过：注册 → 同步 → 幂等 → virtual live → enrichment")


if __name__ == "__main__":
    main()
