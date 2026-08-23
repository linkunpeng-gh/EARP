"""Capability execution + LLM planning channels.

M1: Connector.execute (capability call)
M3/M8: LLMConnector.plan — structured output via Ollama + Redis cache
M11: Dynamic capability injection in system prompt + plan validation
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from earp_server.config import Settings
from earp_server.orchestrator.types import ApprovalPending

if TYPE_CHECKING:
    from earp_server.infra.langfuse_tracer import LangfuseTracer
    from earp_server.infra.llm_cache import LLMCache
    from earp_server.orchestrator.types import TokenEvent

logger = logging.getLogger(__name__)

# Chatflow F3: capability.call 可分派的已知 adapter（capability.domain.name 命中才执行）
_FLOW_ADAPTER_TYPES: frozenset[str] = frozenset(
    {"demo.echo", "llm.prompt", "knowledge.search", "chat.history", "qu.answer", "tool.fetch"}
)


def _evidence_to_chunks(evidence: list[Any]) -> list[dict[str, Any]]:
    """PlanResult evidence → chunks（镜像 chat_service._retrieve 三源转换，供 qu.answer 输出）。"""
    chunks: list[dict[str, Any]] = []
    for ev in evidence:
        p = ev.payload or {}
        if ev.channel.value == "chunk":
            chunks.append(
                {
                    "chunk_id": p.get("chunk_id"),
                    "document_id": ev.source_ref,
                    "title": ev.source,
                    "content": ev.content,
                    "kb_id": p.get("kb_id"),
                    "metadata": p.get("metadata"),
                    "similarity": p.get("similarity"),
                }
            )
        elif ev.channel.value == "profile":
            chunks.append(
                {
                    "source": "profile",
                    "entity_id": p.get("entity_id"),
                    "entity_type": p.get("entity_type"),
                    "title": ev.source,
                    "content": ev.content,
                    "key_facts": p.get("key_facts", []),
                }
            )
        elif ev.channel.value == "graph":
            chunks.append(
                {
                    "source": "graph",
                    "entity_id": p.get("target_entity_id"),
                    "entity_type": p.get("entity_type"),
                    "title": ev.source,
                    "content": ev.content,
                }
            )
        else:  # capability（AGGREGATION 结构化结果）
            chunks.append(
                {
                    "source": "capability",
                    "title": ev.source,
                    "content": f"结构化聚合：{ev.content}",
                    "aggregate": p.get("aggregate"),
                    "rows": p.get("rows"),
                }
            )
    return chunks


class ConnectorError(Exception):
    """Raised when a capability adapter fails after exhausting retries."""


class Connector:
    """Execute a capability call with retry. M1 demo: echo adapter only.

    Chatflow F2: 对话节点适配器（llm.prompt / knowledge.search / chat.history）——
    engine/llm 由 StepRunner 注入（flow 执行链路），ctx 在 execute 时传入。
    Chatflow F3: qu.answer（understand → execute_plan 包装）/ capability.call
    （注册表校验 + 权限门禁）/ tool.fetch（M3 连接体系取数）；settings 注入供
    qu.answer 的 LLM 升级（upgrade_with_llm 需要完整 ollama 配置）。
    """

    def __init__(
        self,
        eventbus=None,
        *,
        engine: AsyncEngine | None = None,
        llm=None,
        settings=None,
    ) -> None:
        self._bus = eventbus
        self._engine = engine
        self._llm = llm
        self._settings = settings

    @retry(
        retry=retry_if_exception_type(ConnectorError),
        wait=wait_exponential_jitter(),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def execute(
        self,
        capability_call: dict[str, Any],
        *,
        ctx: Any = None,
    ) -> dict[str, Any]:
        adapter_type = capability_call.get("adapter_type", "demo.echo")
        logger.debug("connector execute adapter=%s", adapter_type)
        if adapter_type == "demo.echo":
            return {"echo": capability_call.get("input", {})}
        if adapter_type == "llm.prompt":
            return await self._execute_llm_prompt(capability_call.get("input", {}), ctx)
        if adapter_type == "knowledge.search":
            return await self._execute_knowledge_search(capability_call.get("input", {}), ctx)
        if adapter_type == "chat.history":
            return await self._execute_chat_history(capability_call.get("input", {}), ctx)
        if adapter_type == "qu.answer":
            return await self._execute_qu_answer(capability_call.get("input", {}), ctx)
        if adapter_type == "capability.call":
            return await self._execute_capability_call(capability_call, ctx)
        if adapter_type == "tool.fetch":
            return await self._execute_tool_fetch(capability_call.get("input", {}), ctx)
        if adapter_type == "human.approval":
            return await self._execute_human_approval(capability_call.get("input", {}), ctx)
        raise ConnectorError(f"unknown adapter: {adapter_type}")

    async def _execute_llm_prompt(self, input_: dict[str, Any], ctx: Any) -> dict[str, Any]:
        """llm.prompt: 非流式文本生成 → {"text": ...}。

        节点可带 model_config_id（模型配置中心）——解析后构造独立 LLMConnector（provider/base_url/api_key 全量），
        否则用执行链路注入的应用默认 llm（现状）。配置不存在 → 明确报错（不静默回落）。
        """
        prompt = str(input_.get("prompt", ""))
        if not prompt.strip():
            raise ConnectorError("llm.prompt: input.prompt required")
        llm = self._llm
        model_config_id = str(input_.get("model_config_id") or "")
        if model_config_id:
            if self._engine is None or ctx is None:
                raise ConnectorError("llm.prompt: model_config_id 需要 engine + ctx（flow 执行）")
            if self._settings is None:
                raise ConnectorError("llm.prompt: model_config_id 需要 settings 注入（flow 执行）")
            from earp_server.conversation.chat_service import resolve_model_override

            override = await resolve_model_override(self._engine, ctx.tenant_id, model_config_id)
            if not override:
                raise ConnectorError(
                    f"llm.prompt: 模型配置 {model_config_id!r} 不存在或解密失败（tenant {ctx.tenant_id}）"
                )
            llm = LLMConnector(self._settings, model_override=override)
        if llm is None:
            raise ConnectorError("llm.prompt requires llm injection (flow executor)")
        text = await llm.complete(
            prompt,
            system=str(input_.get("system", "") or ""),
            temperature=float(input_.get("temperature", 0.7) or 0.7),
            max_tokens=int(input_["max_tokens"]) if input_.get("max_tokens") else None,
        )
        if text is None:
            raise ConnectorError("llm.prompt: LLM generation failed (provider unreachable or empty)")
        return {"text": text}

    async def _execute_knowledge_search(self, input_: dict[str, Any], ctx: Any) -> dict[str, Any]:
        """knowledge.search: query → embed → 三层检索 → {"chunks", "citations"}。"""
        if self._engine is None or ctx is None:
            raise ConnectorError("knowledge.search requires engine + ctx (flow executor)")
        query = str(input_.get("query", "") or "")
        if not query.strip():
            raise ConnectorError("knowledge.search: input.query required")
        from earp_server.knowledge.embedding_service import embed_query
        from earp_server.knowledge.search_service import search_chunks

        q_emb = await embed_query(query)
        chunks = await search_chunks(
            self._engine,
            ctx.tenant_id,
            q_emb,
            ctx.role_id,
            top_k=max(1, min(20, int(input_.get("top_k", 5) or 5))),
            data_domain_ids=input_.get("data_domain_ids"),
            knowledge_base_ids=input_.get("kb_ids"),
            query_text=query,
        )
        citations = [
            {
                "chunk_id": c.get("chunk_id"),
                "document_id": c.get("document_id"),
                "title": c.get("title"),
                "content": c.get("content"),
            }
            for c in chunks
        ]
        return {"chunks": chunks, "citations": citations}

    async def _execute_chat_history(self, input_: dict[str, Any], ctx: Any) -> dict[str, Any]:
        """chat.history: 会话最近 N 对 → {"messages": [...]}。"""
        if self._engine is None or ctx is None:
            raise ConnectorError("chat.history requires engine + ctx (flow executor)")
        from earp_server.conversation.chat_service import _recent_pairs

        messages = await _recent_pairs(
            self._engine,
            ctx.tenant_id,
            ctx.session_id,
            max(1, min(20, int(input_.get("turns", 6) or 6))),
        )
        return {"messages": messages}

    # ── Chatflow F3: qu/capability/tool 适配器 ──────────────────────────────────

    async def _execute_qu_answer(self, input_: dict[str, Any], ctx: Any) -> dict[str, Any]:
        """qu.answer: understand →（可选 upgrade_with_llm）→ select_plan → execute_plan。

        输出 {selection, evidence, citations, chunks}（D1）——citations 为三源引用结构，
        下游 LLM 节点可 {{#qu.citations#}} 直接引用。settings 由 flow 执行链路注入。
        """
        if self._engine is None or ctx is None:
            raise ConnectorError("qu.answer requires engine + ctx (flow executor)")
        from earp_server.ontology.planning import execute_plan
        from earp_server.ontology.understanding import build_structured_query, understand, upgrade_with_llm

        query = str(input_.get("query", "") or "")
        if not query.strip():
            raise ConnectorError("qu.answer: input.query required")
        result = await understand(self._engine, ctx.tenant_id, query, context={})
        settings = self._settings
        # 方案 C：use_llm=false → 纯规则理解，跳过 LLM 升级（快、确定性）；缺省启用升级
        if input_.get("use_llm") is not False and settings is not None and hasattr(settings, "ollama_chat_model"):
            result = await upgrade_with_llm(self._engine, ctx.tenant_id, query, result, settings=settings)
        sq = build_structured_query(result)
        sel, plan_result = await execute_plan(
            self._engine,
            ctx.tenant_id,
            ctx.role_id,
            query,
            sq,
            settings=settings,
            context={},
            top_k=5,
        )
        return {
            "selection": {"plan_name": sel.plan_name, "fallback_reason": sel.fallback_reason},
            "evidence": [e.model_dump() for e in plan_result.evidence],
            "citations": plan_result.citations,
            "chunks": _evidence_to_chunks(plan_result.evidence),
        }

    async def _execute_capability_call(self, capability_call: dict[str, Any], ctx: Any) -> dict[str, Any]:
        """capability.call: business_capabilities 注册表校验 + required_permissions 门禁 → 真实执行。

        执行分派（通用执行器任务书 D2）：
        - 读能力 execution 声明 → 有 adapter（白名单）→ 按声明分派（input = execution.params 默认
          < capability input 调用方覆写）；无声明 / 未知 adapter → 回退 f"{domain}.{name}" 猜测
          （兼容 demo.echo / 现有 seed 能力）；仍不中 → 明确报错「无执行 adapter（执行声明缺失或未实现）」
        - 能力不存在 → 「不存在」；已 deprecated → 「已停用」（能力中心 soft-disable 衔接）
        - 角色缺 required_permissions → ConnectorError（与 PolicyLayer 双保险）
        """
        if self._engine is None or ctx is None:
            raise ConnectorError("capability.call requires engine + ctx (flow executor)")
        input_ = capability_call.get("input", {}) if isinstance(capability_call.get("input"), dict) else {}
        capability_id = str(capability_call.get("capability_id") or input_.get("capability_id") or "")
        if not capability_id:
            raise ConnectorError("capability.call: capability_id required")
        if capability_call.get("capability_id"):
            # 编译产物形状：capability_id 在顶层，input 即参数（PolicyLayer 兼容）
            cap_input = input_
        else:
            # D4 嵌套形状：input = {capability_id, input: {...}}
            inner = input_.get("input")
            cap_input = inner if isinstance(inner, dict) else {}

        async with self._engine.connect() as conn:
            await conn.execute(text(f"SET LOCAL earp.tenant_id = '{ctx.tenant_id}'"))
            row = await conn.execute(
                text(
                    "SELECT domain, name, required_permissions, status, execution FROM business_capabilities "
                    "WHERE capability_id = :cid AND tenant_id = :tid"
                ),
                {"cid": capability_id, "tid": ctx.tenant_id},
            )
            cap = row.fetchone()
        if cap is None:
            raise ConnectorError(f"capability.call: capability {capability_id!r} 不存在")
        if cap.status != "active":
            raise ConnectorError(f"capability.call: capability {capability_id!r} 已停用（deprecated）")

        required = list(cap.required_permissions or [])
        if required:
            granted = await self._role_permissions(ctx)
            missing = [p for p in required if p not in granted]
            if missing:
                raise ConnectorError(
                    f"capability.call: 角色 {ctx.role_id} 缺少权限 {missing}（capability {capability_id!r}）"
                )

        # 执行声明分派（通用执行器任务书 D2）：声明优先于 domain.name 猜测
        execution: dict[str, Any] = cap.execution if cap.execution is not None else {}
        adapter = execution.get("adapter")
        if adapter:
            if adapter in _FLOW_ADAPTER_TYPES:
                # params 提供 adapter 固定默认（如 tool.fetch 的 connector_id），可被 capability input 覆写
                params = execution.get("params")
                if not isinstance(params, dict):
                    params = {}
                merged_input = {**params, **cap_input}
                return await self.execute(
                    {**capability_call, "adapter_type": adapter, "input": merged_input}, ctx=ctx
                )
            # 显式声明但 adapter 未知 → 明确报错（执行器任务书 D5：执行声明缺失或未实现）
            raise ConnectorError(
                f"capability.call: 能力 {capability_id!r} 执行声明 adapter {adapter!r} 未实现"
                f"（白名单：{sorted(_FLOW_ADAPTER_TYPES)}）"
            )

        # 无执行声明 → 回退 domain.name 猜测（兼容 demo.echo / 现有 seed 能力）
        adapter_type = f"{cap.domain}.{cap.name}"
        if adapter_type == "demo.echo":
            return {"echo": cap_input}
        if adapter_type in _FLOW_ADAPTER_TYPES:
            return await self.execute({**capability_call, "adapter_type": adapter_type, "input": cap_input}, ctx=ctx)
        raise ConnectorError(
            f"capability.call: 能力 {capability_id!r} 无执行 adapter（执行声明缺失或未实现，"
            f"请到能力中心配置 execution.adapter）"
        )

    async def _execute_tool_fetch(self, input_: dict[str, Any], ctx: Any) -> dict[str, Any]:
        """tool.fetch: M3 连接体系——decrypt_config（AES 解密）→ data_adapter.fetch（REST/DB）。

        输出 {rows, count, domain_filtered: False}——M3 review 教训：raw rows 未按角色域过滤，
        标注 domain_filtered=False 由上层/后续做域过滤。
        """
        if self._engine is None or ctx is None:
            raise ConnectorError("tool.fetch requires engine + ctx (flow executor)")
        from earp_server.ontology.connector_service import decrypt_config
        from earp_server.ontology.data_adapter import fetch as data_fetch

        connector_id = str(input_.get("connector_id", "") or "")
        if not connector_id:
            raise ConnectorError("tool.fetch: input.connector_id required")
        cfg = await decrypt_config(self._engine, ctx.tenant_id, connector_id)
        if not cfg:
            raise ConnectorError(f"tool.fetch: connector {connector_id!r} 不存在或配置解密失败")
        params = input_.get("params") if isinstance(input_.get("params"), dict) else {}
        rows = await data_fetch(cfg, params)
        return {"rows": rows, "count": len(rows), "domain_filtered": False}

    async def _execute_human_approval(self, input_: dict[str, Any], ctx: Any) -> dict[str, Any]:
        """human.approval: 挂起信号（D2）——抛 ApprovalPending 由执行器捕获转 waiting_human。

        节点 data: {question: 模板表达式（默认「请确认是否继续」）}；恢复时用户下一句即答复，
        答复注入 {{#node.output.reply#}}（简写 {{#node.reply#}}）供下游引用。
        """
        if ctx is None:
            raise ConnectorError("human.approval requires ctx (flow executor)")
        question = str(input_.get("question", "请确认是否继续") or "请确认是否继续")
        raise ApprovalPending(ctx.step.step_id, question)

    async def _role_permissions(self, ctx: Any) -> list[str]:
        """capability.call 权限门禁：查询角色 permissions（与 PolicyLayer._get_role_permissions 同构）。"""
        if self._engine is None:
            raise ConnectorError("capability.call requires engine (flow executor)")
        async with self._engine.connect() as conn:
            await conn.execute(text(f"SET LOCAL earp.tenant_id = '{ctx.tenant_id}'"))
            row = await conn.execute(
                text("SELECT permissions FROM roles WHERE role_id = :rid AND tenant_id = :tid"),
                {"rid": ctx.role_id, "tid": ctx.tenant_id},
            )
            r = row.fetchone()
            return list(r.permissions) if r and r.permissions else []

    def _on_retry(self, retry_state) -> None:
        if self._bus is not None:
            from earp_server.infra.eventbus import CloudEvent

            self._bus.publish(
                CloudEvent(
                    type="earp.connector.retrying",
                    source="earp-server/connector",
                    tenant_id="",
                    data={
                        "attempt": retry_state.attempt_number,
                        "exception": str(retry_state.outcome.exception()) if retry_state.outcome else "",
                    },
                )
            )


# ── LLMConnector (M3, Phase 2/3 enhanced) ────────────────────────────────────


def _build_plan_system_prompt(capabilities: list[dict[str, Any]] | None = None) -> str:
    """Build a system prompt dynamically from available capabilities.

    When capabilities are provided, lists them in the prompt.
    Falls back to a minimal default if none provided.
    """
    base = (
        "You are an intent-to-action planner. Given a user intent, output a JSON plan "
        'with exactly this structure: {"steps": [{"capability_id": "...", "input": {...}}]}. '
    )
    if capabilities:
        cap_list = ", ".join(f"{c['name']} ({c['capability_id']})" for c in capabilities)
        base += f"Available capabilities: {cap_list}. "
    else:
        base += (
            "Available capabilities: echo (cap-demo-echo), query users (cap-query-users), "
            "create alarm (cap-create-alarm), query alarms (cap-query-alarms). "
        )
    base += "Output ONLY valid JSON, no explanation."
    return base


class LLMConnector:
    """LLM integration with structured output + rate limiting + cache.

    Interface finalized in M3 (5 hooks).
    Phase 2: cache (Redis+memory) + real Ollama structured output.
    Phase 3 (M11): dynamic capability injection + plan validation.
    Remaining: bind_tools, stream toggle.
    """

    def __init__(
        self,
        settings: Settings,
        rate_limiter=None,
        model_override: dict | None = None,
        transport=None,
    ) -> None:
        """model_override: {provider, model_name, base_url, api_key, ...} from DB model_config
        (PRD-2026-031) — DB 优先，env 兜底。transport: httpx transport 注入（测试用 MockTransport）。"""
        self._settings = settings
        self._model_override = model_override or {}
        self._provider = self._model_override.get("provider") or "ollama"
        self._model = self._model_override.get("model_name") or settings.ollama_chat_model
        self._base_url = self._model_override.get("base_url") or settings.ollama_base_url
        self._api_key = self._model_override.get("api_key") or ""
        self._transport = transport
        self._rate_limiter = rate_limiter
        # Phase 2: wired
        self._cache: LLMCache | None = None  # set via .cache setter
        self._structured_output: bool = True
        # Phase 3: deferred
        self._bind_tools: bool = False
        self._stream_enabled: bool = False

    @property
    def cache(self):
        return self._cache

    @cache.setter
    def cache(self, c: LLMCache | None) -> None:
        self._cache = c

    # M15: Langfuse tracer — set by lifespan
    tracer: LangfuseTracer | None = None

    async def _call_ollama(
        self,
        prompt: str,
        *,
        capabilities: list[dict[str, Any]] | None = None,
        timeout: float = 30,  # noqa: ASYNC109 — 传给 httpx 调用级超时，非 asyncio.timeout 场景
    ) -> list[dict[str, Any]]:
        """Call Ollama /api/chat with JSON format, return parsed steps."""
        system = _build_plan_system_prompt(capabilities)
        url = f"{self._base_url}/api/chat"
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.1},
        }
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            logger.error("LLMConnector: Ollama chat failed: %s", exc)
            raise ConnectorError(f"Ollama chat call failed: {exc}") from exc

        content = data.get("message", {}).get("content", "")
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            logger.warning("LLMConnector: non-JSON response, attempting substring parse")
            start = content.find("{")
            if start != -1:
                depth = 0
                end = start
                for i in range(start, len(content)):
                    if content[i] == "{":
                        depth += 1
                    elif content[i] == "}":
                        depth -= 1
                        if depth == 0:
                            end = i + 1
                            break
                if depth == 0:
                    parsed = json.loads(content[start:end])
                else:
                    raise ConnectorError(f"LLM returned unbalanced JSON: {content[:200]}") from None
            else:
                raise ConnectorError(f"LLM returned non-JSON: {content[:200]}") from None

        steps = parsed.get("steps", [])
        if not steps:
            raise ConnectorError("LLM returned empty steps")
        return steps

    async def json_complete(
        self,
        system: str,
        user_prompt: str,
        *,
        model_override: dict | None = None,
        temperature: float = 0.3,
        timeout: float = 30,
    ) -> dict | None:
        """JSON 结构化单发（ollama /api/chat + openai /chat/completions）。

        Phase B 决策 D4 方案 A：**无 DB 依赖**——model_override 由调用方解析
        （同 resolve_llm_override 先例），None 时回退构造时 override/settings。
        provider 不可达/响应非 JSON → 返回 None（调用方回落），不抛异常。
        供 QU LLM 升级（understanding.upgrade_with_llm）与 suggest 系列共用。
        timeout: 调用级超时（T2 2026-08-18：120s → 30s，防 llm 跑分超时累积挂起）；
        超时回落 None，schema 合规不破。
        """
        override = model_override or self._model_override
        provider = override.get("provider") or "ollama"
        model_name = override.get("model_name") or self._model
        base_url = (override.get("base_url") or self._base_url).rstrip("/")
        api_key = override.get("api_key") or self._api_key
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ]
        try:
            async with httpx.AsyncClient(timeout=timeout, transport=self._transport) as client:
                if provider == "openai":
                    resp = await client.post(
                        f"{base_url}/chat/completions",
                        json={
                            "model": model_name,
                            "messages": messages,
                            "response_format": {"type": "json_object"},
                            "temperature": temperature,
                        },
                        headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
                    )
                    resp.raise_for_status()
                    content = resp.json()["choices"][0]["message"]["content"]
                else:  # ollama
                    resp = await client.post(
                        f"{base_url}/api/chat",
                        json={
                            "model": model_name,
                            "messages": messages,
                            "format": "json",
                            "stream": False,
                            "options": {"temperature": temperature},
                        },
                    )
                    resp.raise_for_status()
                    content = resp.json()["message"]["content"]
            data = json.loads(content)
            return data if isinstance(data, dict) else None
        except Exception as exc:
            logger.warning("LLMConnector.json_complete: %s/%s failed: %s", provider, model_name, exc)
            return None

    async def plan(
        self,
        prompt: str,
        *,
        tools: list[dict] | None = None,
        capabilities: list[dict[str, Any]] | None = None,
        timeout: float = 30,  # noqa: ASYNC109 — 传给 httpx 调用级超时，非 asyncio.timeout 场景
    ) -> list[dict[str, Any]]:
        """Generate a Plan via LLM with structured output + cache.

        Phase 2: real Ollama call with JSON mode + Redis/memory cache.
        Phase 3: dynamic capability injection + plan validation.
        Falls back to RuleIntentPlanner if Ollama is unreachable.
        timeout: 调用级超时（T2 2026-08-18：30s 默认，防上游挂起）。
        """
        # 1. Check cache
        cache_key = f"{self._model}||{prompt}||{json.dumps(capabilities or [])}"
        if self._cache:
            cached = await self._cache.get(self._model, cache_key)
            if cached is not None:
                logger.info("LLMConnector.plan: cache hit")
                return cached

        # 2. Try Ollama structured output (skip if capabilities list is explicitly empty)
        if capabilities is not None and len(capabilities) == 0:
            logger.info("LLMConnector.plan: empty capabilities list, skipping Ollama")
        else:
            try:
                import time

                t0 = time.monotonic()
                steps = await self._call_ollama(prompt, capabilities=capabilities, timeout=timeout)
                latency_ms = int((time.monotonic() - t0) * 1000)
                if self.tracer:
                    self.tracer.trace_llm(
                        "plan",
                        self._model,
                        prompt[:200],
                        output=json.dumps(steps)[:500],
                        latency_ms=latency_ms,
                        usage={"output_tokens": len(json.dumps(steps).split())},
                    )
                # Validate: capability_ids must exist in provided capabilities list
                if capabilities:
                    valid_ids = {c["capability_id"] for c in capabilities}
                    for s in steps:
                        cid = s.get("capability_id", "")
                        if cid not in valid_ids:
                            logger.warning(
                                "LLMConnector.plan: unknown capability_id %r, discarding step",
                                cid,
                            )
                    steps = [s for s in steps if s.get("capability_id", "") in valid_ids]
                    if not steps:
                        raise ConnectorError("LLM returned steps with no valid capability_ids")
                # Cache the result
                if self._cache:
                    await self._cache.set(self._model, cache_key, steps)
                return steps
            except ConnectorError:
                logger.warning("LLMConnector.plan: Ollama failed, falling back to RuleIntentPlanner")
                if self.tracer:
                    self.tracer.trace_llm(
                        "plan",
                        self._model,
                        prompt[:200],
                        error="Ollama failed — fell back to RuleIntentPlanner",
                        latency_ms=0,
                    )
            except Exception:
                logger.exception("LLMConnector.plan: unexpected error, falling back")
                if self.tracer:
                    self.tracer.trace_llm(
                        "plan",
                        self._model,
                        prompt[:200],
                        error="unexpected error",
                        latency_ms=0,
                    )

        # 3. Fallback: RuleIntentPlanner
        from earp_server.planner.business_dictionary import RuleIntentPlanner

        resolver = RuleIntentPlanner()
        match = resolver.resolve(prompt)
        if match is None:
            raise ConnectorError(f"LLMConnector.plan: no match for prompt '{prompt}'")
        return [{"capability_id": match.capability_id, "input": match.input}]

    async def plan_structured(self, prompt: str) -> list[dict[str, Any]]:
        """Phase 2: LLM call with JSON structured output enforced.

        Identical to plan() — the JSON format is enforced at the Ollama API level
        via ``format: "json"``. plan() and plan_structured() share the same path.
        """
        return await self.plan(prompt)

    async def _stream_messages(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        top_p: float = 0.9,
        max_tokens: int | None = None,
    ) -> AsyncGenerator[TokenEvent, None]:
        """Stream tokens for a full message list, provider-aware.

        - ollama: POST {base_url}/api/chat（NDJSON 流，options.temperature/top_p/num_predict）
        - openai 兼容（openai/deepseek 等）: POST {base_url}/chat/completions（SSE 流，
          data: 前缀 + [DONE]，顶层 temperature/top_p/max_tokens + Authorization header）

        Uses model_override (DB model_configs, PRD-2026-031) when configured:
        base_url/model/api_key from the override. 修复：旧实现固定 Ollama 协议，
        deepseek 等 provider 会打到 {base_url}/api/chat → 404。
        """
        from earp_server.orchestrator.types import TokenEvent

        is_ollama = self._provider == "ollama"
        base = self._base_url.rstrip("/")
        url = f"{base}/api/chat" if is_ollama else f"{base}/chat/completions"
        headers = {}
        if self._api_key and not is_ollama:
            headers["Authorization"] = f"Bearer {self._api_key}"

        if is_ollama:
            options: dict[str, Any] = {"temperature": temperature}
            if top_p is not None:
                options["top_p"] = top_p
            if max_tokens:
                options["num_predict"] = max_tokens  # Ollama num_predict = max_tokens
            payload: dict[str, Any] = {"model": self._model, "messages": messages, "stream": True, "options": options}
        else:
            payload = {
                "model": self._model,
                "messages": messages,
                "stream": True,
                "temperature": temperature,
                "top_p": top_p,
            }
            if max_tokens:
                payload["max_tokens"] = max_tokens

        index = 0
        try:
            client_kw: dict[str, Any] = {"timeout": 300}
            if self._transport is not None:
                client_kw["transport"] = self._transport
            async with httpx.AsyncClient(**client_kw) as client:
                async with client.stream("POST", url, json=payload, headers=headers) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        data = line
                        if not is_ollama:
                            # OpenAI 兼容 SSE："data: {...}" / "data: [DONE]"
                            if not data.startswith("data:"):
                                continue
                            data = data[5:].strip()
                            if data == "[DONE]":
                                break
                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        if is_ollama:
                            if chunk.get("done"):
                                break
                            content = chunk.get("message", {}).get("content", "")
                        else:
                            choices = chunk.get("choices") or []
                            if not choices:
                                continue
                            delta = choices[0].get("delta") or {}
                            content = delta.get("content", "")
                        if content:
                            yield TokenEvent(token=content, index=index)
                            index += 1
        except httpx.HTTPError as exc:
            logger.error("LLMConnector.stream: streaming failed (provider=%s url=%s): %s", self._provider, url, exc)
            raise ConnectorError(f"LLM streaming failed ({self._provider}): {exc}") from exc

    async def complete(
        self,
        prompt: str,
        *,
        system: str = "",
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str | None:
        """Chatflow F2: 非流式文本生成（llm.prompt 节点适配器用）。

        ollama /api/chat stream:false + openai 兼容 /chat/completions，provider-aware
        （与 _stream_messages 同构）；失败返回 None 不抛（调用方回落）。
        """
        is_ollama = self._provider == "ollama"
        base = self._base_url.rstrip("/")
        url = f"{base}/api/chat" if is_ollama else f"{base}/chat/completions"
        headers = {}
        if self._api_key and not is_ollama:
            headers["Authorization"] = f"Bearer {self._api_key}"
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        if is_ollama:
            payload: dict[str, Any] = {
                "model": self._model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": temperature},
            }
            if max_tokens:
                payload["options"]["num_predict"] = max_tokens
        else:
            payload = {"model": self._model, "messages": messages, "stream": False, "temperature": temperature}
            if max_tokens:
                payload["max_tokens"] = max_tokens
        try:
            client_kw: dict[str, Any] = {"timeout": 300}
            if self._transport is not None:
                client_kw["transport"] = self._transport
            async with httpx.AsyncClient(**client_kw) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
            if is_ollama:
                return (data.get("message") or {}).get("content") or None
            choices = data.get("choices") or []
            if not choices:
                return None
            return (choices[0].get("message") or {}).get("content") or None
        except httpx.HTTPError as exc:
            logger.error("LLMConnector.complete: failed (provider=%s url=%s): %s", self._provider, url, exc)
            return None

    async def stream(self, prompt: str, *, system: str = "") -> AsyncGenerator[TokenEvent, None]:
        """Stream tokens from Ollama /api/chat with stream=true.

        Yields TokenEvent for each token chunk from the LLM.
        Handles Ollama's NDJSON streaming format.
        """
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        async for ev in self._stream_messages(messages):
            yield ev

    async def chat_stream(
        self,
        system: str,
        history: list[dict[str, str]],
        query: str,
        *,
        temperature: float = 0.7,
        top_p: float = 0.9,
        max_tokens: int | None = None,
    ) -> AsyncGenerator[TokenEvent, None]:
        """RAG chat streaming — full message list (system + history + current query).

        history: [{"role": "user"|"assistant", "content": ...}]（最近 N 对，已配对）
        temperature/top_p/max_tokens: 应用级生成参数（chat_apps.generation）
        """
        messages = [{"role": "system", "content": system}]
        messages.extend(history)
        messages.append({"role": "user", "content": query})
        async for ev in self._stream_messages(messages, temperature=temperature, top_p=top_p, max_tokens=max_tokens):
            yield ev
