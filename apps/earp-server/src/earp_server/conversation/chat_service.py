"""chat_service — RAG 问答编排（P1 问答链路一期，设计 §4.3/§4.4/§4.6）。

POST /chat_apps/{app_id}/chat  SSE 流式编排：
  会话创建/续接 → 用户消息先 commit → 多轮 (user,assistant) 配对取 N 对
  → 检索（kb_scope 空=软路由 / 限定 KB 静默过滤）→ 拼提示词（app.system_prompt
  + 结构尾巴含 [N] 编号规则）→ LLM.chat_stream（模型三级解析）→ done 后落库
  助手消息 + citations。

模型三级解析（CP2）：chat_apps.model_config_id → system_model_settings(llm) → env。
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from earp_server.connector import ConnectorError, LLMConnector
from earp_server.knowledge.embedding_service import embed_query
from earp_server.knowledge.search_service import search_chunks

logger = logging.getLogger(__name__)

# 结构尾巴（代码内置不可改，CP3）：引用编号规则 + 内容边界 + 回答要求
_SYSTEM_TAIL = """

【回答规则】
1. 优先依据上方编号资料回答；资料未覆盖时明确说明「知识库中暂无相关内容」，不得编造。
2. 引用资料时在对应句末标注编号，如 [1]；同一资料多次引用可复用编号，编号与资料一一对应。
3. 回答使用中文，简洁清晰。"""

_TITLE_MAX = 30  # 会话标题 = 首问截断长度


class ChatError(Exception):
    """Chat 链路可预期失败（转 SSE error 事件，不产生 500）。"""


# ── 模型三级解析（Task 8 / CP2）───────────────────────────────────────────


async def resolve_model_override(engine: AsyncEngine, tenant_id: str, config_id: str | None) -> dict[str, Any] | None:
    """model_configs 单条解析 → model_override dict（provider/model_name + 解密 credentials）。

    节点级（Chatflow LLM 节点 model_config_id）与应用级（resolve_llm_override）共用。
    """
    if not config_id:
        return None
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        row = (
            await conn.execute(
                text(
                    "SELECT provider, model_name, credentials FROM model_configs "
                    "WHERE config_id = :cid AND tenant_id = :tid"
                ),
                {"cid": config_id, "tid": tenant_id},
            )
        ).first()
        if row is None:
            return None
        creds = row.credentials or {}
        if isinstance(creds, str):
            try:
                creds = json.loads(creds)
            except (TypeError, ValueError):
                creds = {}
        # model_configs.credentials 加密存储（credential_crypto）——解密后才是 base_url/api_key
        if creds and "ciphertext" in creds:
            from earp_server.infra.credential_crypto import decrypt

            try:
                creds = decrypt(creds)
            except Exception:
                logger.warning("resolve_model_override: credential decrypt failed, falling back empty")
                creds = {}
        return {"provider": row.provider, "model_name": row.model_name, **creds}


async def resolve_llm_override(engine: AsyncEngine, tenant_id: str, app: dict[str, Any]) -> dict[str, Any] | None:
    """chat_apps.model_config_id → system_model_settings(llm) → None(=env)。

    返回 model_override dict（provider/model_name/base_url/api_key…），或 None 表示 env。
    """
    config_id = app.get("model_config_id")
    if not config_id:
        async with engine.connect() as conn:
            await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
            row = (
                await conn.execute(
                    text(
                        "SELECT model_config_id FROM system_model_settings "
                        "WHERE tenant_id = :tid AND setting_type = 'llm'"
                    ),
                    {"tid": tenant_id},
                )
            ).first()
            config_id = row.model_config_id if row else None
    return await resolve_model_override(engine, tenant_id, config_id)


# ── 多轮历史配对（S1）─────────────────────────────────────────────────────


async def _recent_pairs(engine: AsyncEngine, tenant_id: str, conversation_id: str, turns: int) -> list[dict]:
    """按 (user, assistant) 配对取最近 N 对完整轮次；当前用户消息（末尾孤立 user）跳过。"""
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        rows = await conn.execute(
            text("SELECT role, content FROM messages WHERE conversation_id = :cid ORDER BY seq DESC LIMIT :lim"),
            {"cid": conversation_id, "lim": turns * 4 + 1},
        )
        msgs = list(reversed(rows.fetchall()))

    # 当前问题已落库（末尾 user）—— 不参与历史（chat_stream 会再拼当前 query）
    if msgs and msgs[-1].role == "user":
        msgs = msgs[:-1]

    pairs: list[list[dict]] = []
    i = len(msgs) - 1
    while i >= 1 and len(pairs) < turns:
        if msgs[i].role == "assistant" and msgs[i - 1].role == "user":
            pairs.append(
                [
                    {"role": "user", "content": msgs[i - 1].content},
                    {"role": "assistant", "content": msgs[i].content},
                ]
            )
            i -= 2
        else:
            i -= 1
    pairs.reverse()
    return [m for pair in pairs for m in pair]


# ── 检索与引用（§4.3 ⑤）───────────────────────────────────────────────────


async def _retrieve(
    engine: AsyncEngine,
    tenant_id: str,
    role_id: str,
    query: str,
    q_emb: list[float],
    app: dict[str, Any],
    embedding_dim: int,
    *,
    settings=None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """返回 (chunks, citations)。

    kb_scope 非空 → 限定 KB（search_chunks，一期不接 planner）。
    kb_scope 空 → 软路由走 planner（Phase D D1d：理解 → select_plan → 策略 →
    PlanResult → chunks/citations；AGGREGATION 走 capability 执行器）。
    检索保持原 top_k 语义（chunk 级）；引用去重在展示层做（前端按文档聚合）。
    """
    retrieval = app.get("retrieval") or {}
    top_k = retrieval.get("top_k", 5)
    threshold = retrieval.get("threshold") or 0.0
    mode = retrieval.get("mode", "hybrid")

    kb_scope = app.get("kb_scope") or []
    if kb_scope:
        chunks = await search_chunks(
            engine,
            tenant_id,
            q_emb,
            role_id,
            top_k=top_k,
            eventbus=None,
            embedding_dim=embedding_dim,
            knowledge_base_ids=kb_scope,
            threshold=threshold,
            query_text=query,
            mode=mode,
        )
    else:
        # Phase D D1d：软路由路径走 planner（理解 → select_plan → 策略 → PlanResult）
        from earp_server.ontology.planning import execute_plan
        from earp_server.ontology.understanding import build_structured_query, understand, upgrade_with_llm

        result = await understand(engine, tenant_id, query)
        # LLM 升级仅在 settings 完整（含 ollama 配置）时触发——测试/简化环境跳过（规则层结果）
        if settings is not None and hasattr(settings, "ollama_chat_model"):
            result = await upgrade_with_llm(engine, tenant_id, query, result, settings=settings)
        sq = build_structured_query(result)
        logger.info(
            "chat planner: query=%r intent=%s",
            query,
            sq.intent.value,
        )
        _, plan = await execute_plan(
            engine,
            tenant_id,
            role_id,
            query,
            sq,
            settings=settings,
            top_k=top_k,
        )
        chunks = []
        for ev in plan.evidence:
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
        return chunks, plan.citations

    citations = []
    for ch in chunks:
        src = ch.get("source")
        if src == "profile":
            citations.append(
                {
                    "source": "profile",
                    "entity_id": ch.get("entity_id"),
                    "entity_type": ch.get("entity_type"),
                    "title": ch.get("title") or "",
                    "key_facts": ch.get("key_facts", []),
                }
            )
        elif src == "graph":
            citations.append(
                {
                    "source": "graph",
                    "entity_id": ch.get("entity_id"),
                    "entity_type": ch.get("entity_type"),
                    "title": ch.get("title") or "",
                }
            )
        else:
            citations.append(
                {
                    "chunk_id": ch.get("chunk_id"),
                    "document_id": ch.get("document_id"),
                    "title": ch.get("title") or ch.get("doc_name") or "",
                    "kb_id": ch.get("kb_id"),
                    "kb_name": ch.get("kb_name"),
                    "metadata": ch.get("metadata"),
                    "similarity": ch.get("similarity"),
                }
            )
    return chunks, citations


def _build_context_block(chunks: list[dict[str, Any]]) -> str:
    """编号资料块（CP3：按返回顺序 [1]..[N]）。"""
    lines = ["【知识资料】"]
    for i, ch in enumerate(chunks, 1):
        src = ch.get("title") or ch.get("doc_name") or ch.get("document_id") or "未命名"
        kb = ch.get("kb_name") or ch.get("kb_id") or ""
        meta = ch.get("metadata") or {}
        meta_txt = ""
        for k in ("version", "year", "doc_type", "department"):
            v = meta.get(k)
            if v not in (None, ""):
                meta_txt += f" {k}={v}"
        lines.append(f"[{i}] 《{src}》（{kb}{meta_txt}）\n{ch.get('content', '')}")
    return "\n\n".join(lines)


# ── 落库 helper ───────────────────────────────────────────────────────────


async def _set_citations(engine: AsyncEngine, tenant_id: str, message_id: str, citations: list[dict]) -> None:
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        await conn.execute(
            text("UPDATE messages SET citations = :cits WHERE message_id = :mid"),
            {"cits": json.dumps(citations), "mid": message_id},
        )
        await conn.commit()


# ── SSE 主编排（§4.3）──────────────────────────────────────────────────────


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


async def chat_sse(
    engine: AsyncEngine,
    tenant_id: str,
    user_id: str,
    role_id: str,
    app: dict[str, Any],
    query: str,
    conversation_id: str | None,
    *,
    base_llm: LLMConnector,
    settings,
    rate_limiter=None,
    embedding_dim: int | None = None,
) -> AsyncGenerator[str, None]:
    """SSE 事件流：token* → done(message_id, citations) | error。"""
    from earp_server.conversation.conversation_service import add_message, create_conversation

    if not (query or "").strip():
        yield _sse({"type": "error", "message": "问题不能为空"})
        return

    try:
        # ② 会话创建/续接（chat_app_id 归属写入）
        if conversation_id:
            async with engine.connect() as conn:
                await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
                exists = (
                    await conn.execute(
                        text("SELECT 1 FROM conversations WHERE conversation_id = :cid"),
                        {"cid": conversation_id},
                    )
                ).first()
            if not exists:
                raise ChatError("会话不存在或不属于当前租户")
        else:
            conv = await create_conversation(
                engine, tenant_id, user_id, query.strip()[:_TITLE_MAX], chat_app_id=app["chat_app_id"]
            )
            conversation_id = conv["conversation_id"]

        # ③ 用户消息先 commit（CP4：SSE 开始前已可见）
        await add_message(engine, tenant_id, conversation_id, "user", query, user_id)

        # ④ 多轮历史（配对）
        turns = int(app.get("context_turns") or 6)
        history = await _recent_pairs(engine, tenant_id, conversation_id, turns)

        # ⑤ 检索
        if embedding_dim is None:
            embedding_dim = getattr(settings, "embedding_dim", 1024)
        q_emb = await embed_query(query)
        chunks, citations = await _retrieve(
            engine, tenant_id, role_id, query, q_emb, app, embedding_dim, settings=settings
        )

        # ⑥ 提示词 = app.system_prompt + 结构尾巴；上下文进 user 消息
        system = (app.get("system_prompt") or "").strip() + _SYSTEM_TAIL
        context_block = _build_context_block(chunks)
        user_content = f"{context_block}\n\n用户问题：{query}" if chunks else f"用户问题：{query}"

        # ⑦ LLM：模型三级解析
        override = await resolve_llm_override(engine, tenant_id, app)
        chat_llm = LLMConnector(settings, rate_limiter=rate_limiter, model_override=override) if override else base_llm

        # ⑧ 流式生成（应用级生成参数：temperature/top_p/max_tokens）
        gen = app.get("generation") or {}
        answer_parts: list[str] = []
        async for ev in chat_llm.chat_stream(
            system,
            history,
            user_content,
            temperature=gen.get("temperature", 0.7),
            top_p=gen.get("top_p", 0.9),
            max_tokens=gen.get("max_tokens"),
        ):
            tok = ev.token
            if tok:
                answer_parts.append(tok)
                yield _sse({"type": "token", "content": tok})

        # 落库助手消息 + citations
        answer = "".join(answer_parts)
        msg = await add_message(engine, tenant_id, conversation_id, "assistant", answer, user_id)
        await _set_citations(engine, tenant_id, msg["message_id"], citations)
        yield _sse(
            {
                "type": "done",
                "message_id": msg["message_id"],
                "conversation_id": conversation_id,
                "citations": citations,
            }
        )
    except (ConnectorError, ChatError) as e:
        logger.warning("chat failed (user msg persisted): %s", e)
        yield _sse({"type": "error", "message": f"回答生成失败：{e}"})
    except Exception:
        logger.exception("chat unexpected error")
        yield _sse({"type": "error", "message": "回答生成失败，请稍后重试"})


# ── Chatflow F2: flow 模式图执行（非流式）────────────────────────────────────


async def flow_chat(
    engine: AsyncEngine,
    tenant_id: str,
    user_id: str,
    role_id: str,
    app: dict[str, Any],
    query: str,
    conversation_id: str | None,
    *,
    base_llm: LLMConnector,
    settings,
    bus=None,
    on_event=None,  # 应用中心：flow 节点级 SSE 流式事件回调 async (event_type, data) -> None
) -> dict[str, Any]:
    """Chatflow F2/F4: orchestration='flow' 时走声明式图执行（设计稿 §2/§7）。

    会话创建/续接（chat_apps 归属 + 用户消息先落）→ compile_flow_schema →
    MultiStepExecutor（对话节点适配器注入）→ outputs → 助手消息 + citations 落库。
    非流式 JSON 响应；on_event 注入时透传节点级事件（node_start/token/node_end/branch/
    human_approval/done/error）——应用中心 flow SSE 流式。

    Chatflow F4: human_approval 挂起/恢复——同 conversation 的 waiting_human run 存在则
    恢复（用户下一句即答复），否则新建；挂起 → flow_runs(status=waiting_human) 落库 +
    assistant 消息 + 返回 waiting_human 状态（端点转 202）；完成/超时终态化。
    """
    from earp_server.conversation import flow_runs
    from earp_server.conversation.conversation_service import add_message, create_conversation
    from earp_server.orchestrator.multi_step import ExecutionStatus, MultiStepExecutor
    from earp_server.orchestrator.types import InvokeContext, Step
    from earp_server.orchestrator.workflow_dsl import CondExec, compile_flow_schema, deserialize_pool, serialize_pool

    async def _emit(ev: str, data: dict) -> None:
        if on_event is not None:
            try:
                await on_event(ev, data)
            except Exception:
                logger.warning("flow_chat on_event failed (ev=%s)", ev, exc_info=True)

    if not (query or "").strip():
        raise ChatError("问题不能为空")

    # 会话创建/续接（chat_app_id 归属写入，同 auto 模式）
    if conversation_id:
        async with engine.connect() as conn:
            await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
            exists = (
                await conn.execute(
                    text("SELECT 1 FROM conversations WHERE conversation_id = :cid"),
                    {"cid": conversation_id},
                )
            ).first()
        if not exists:
            raise ChatError("会话不存在或不属于当前租户")
    else:
        conv = await create_conversation(
            engine, tenant_id, user_id, query.strip()[:_TITLE_MAX], chat_app_id=app["chat_app_id"]
        )
        conversation_id = str(conv["conversation_id"])
    assert conversation_id is not None  # 上述分支必赋值
    await add_message(engine, tenant_id, conversation_id, "user", query, user_id)

    # 编译（发布门禁已保证合法；此处防御未发布/改库场景）
    plan = compile_flow_schema(app["flow_schema"])
    override = await resolve_llm_override(engine, tenant_id, app)
    llm = LLMConnector(settings, model_override=override) if override else base_llm
    # Chatflow F3: settings 注入执行器 → qu.answer 适配器（upgrade_with_llm 需要 ollama 配置）
    executor = MultiStepExecutor(engine, bus=bus, llm=llm, settings=settings)

    # F4: 同 conversation 的 waiting_human run → 恢复模式；否则新建（D6：唯一性）
    waiting = await flow_runs.get_waiting_run(engine, tenant_id, conversation_id)
    resume_failed = False
    resume_error = ""
    if waiting is not None and _approval_expired(waiting, _approval_ttl(settings)):
        # D4 惰性超时检查
        pending = waiting.get("pending_node_id")
        if pending and plan.result_branches.get(pending):
            # 应用中心：挂起点连了失败分支 → 超时未确认视为失败，走 error 分支继续执行
            resume_failed = True
            resume_error = "等待超时未确认"
            await add_message(engine, tenant_id, conversation_id, "assistant", "⏰ 等待超时，按失败分支处理", user_id)
        else:
            # 无失败分支：超时 → timeout 终态 + 消息，本轮按新建处理（维持现状）
            await flow_runs.finish_run(engine, tenant_id, waiting["execution_id"], status="timeout")
            await add_message(engine, tenant_id, conversation_id, "assistant", "⏰ 等待超时，流程终止", user_id)
            waiting = None

    flow_input = {"query": query, "conversation_id": conversation_id}
    if waiting is not None:
        # 恢复：用户下一句即答复；flow_input 用挂起时快照（{{query}} 仍是挂起时的问题）
        exec_id = waiting["execution_id"]
        ctx = InvokeContext(
            tenant_id=tenant_id,
            execution_id=exec_id,
            session_id=conversation_id,
            user_id=user_id,
            role_id=role_id,
            step=Step(step_id="start", capability_call={}),
        )
        pool = deserialize_pool(waiting.get("node_state"))
        exec_kwargs: dict[str, Any] = _flow_exec_kwargs(_emit) if on_event is not None else {}
        results, state = await executor.execute(
            plan.steps,
            ctx,
            layers=[],
            plan=plan,
            flow_input=waiting.get("flow_input") or flow_input,
            resume_pool=pool,
            resume_pending_node=waiting.get("pending_node_id"),
            resume_reply=query,
            resume_pending_failed=resume_failed,
            resume_error=resume_error,
            **exec_kwargs,
        )
        attempts = int(waiting.get("attempts") or 1) + 1
    else:
        exec_id = uuid.uuid4().hex
        await flow_runs.create_run(
            engine,
            tenant_id,
            execution_id=exec_id,
            chat_app_id=app["chat_app_id"],
            conversation_id=conversation_id,
            flow_input=flow_input,
        )
        ctx = InvokeContext(
            tenant_id=tenant_id,
            execution_id=exec_id,
            session_id=conversation_id,
            user_id=user_id,
            role_id=role_id,
            step=Step(step_id="start", capability_call={}),
        )
        exec_kwargs: dict[str, Any] = _flow_exec_kwargs(_emit) if on_event is not None else {}
        results, state = await executor.execute(
            plan.steps,
            ctx,
            layers=[],
            plan=plan,
            flow_input=flow_input,
            **exec_kwargs,
        )
        attempts = 1

    if state.status == ExecutionStatus.WAITING_HUMAN:
        # 挂起（D2）：pool 序列化落 flow_runs（复用 exec_id——conversation 的 waiting_human 唯一）
        node_state = serialize_pool({r.step_id: r for r in results if r.status == "completed"})
        await flow_runs.update_waiting(
            engine,
            tenant_id,
            exec_id,
            pending_node_id=state.pending_node_id,
            node_state=node_state,
            attempts=attempts,
        )
        question = state.pending_question or "请确认是否继续"
        await add_message(engine, tenant_id, conversation_id, "assistant", f"⏸ 等待确认：{question}", user_id)
        # 挂起节点补发 node_end（waiting_human）：否则前端节点保持 running 闪烁
        await _emit(
            "node_end",
            {
                "node_id": state.pending_node_id,
                "status": "waiting_human",
                "latency_ms": 0,
                "output_summary": None,
                "error": None,
            },
        )
        await _emit(
            "human_approval",
            {
                "execution_id": exec_id,
                "conversation_id": conversation_id,
                "question": question,
                "pending_node_id": state.pending_node_id,
            },
        )
        return {
            "execution_id": exec_id,
            "conversation_id": conversation_id,
            "status": ExecutionStatus.WAITING_HUMAN.value,
            "pending_node_id": state.pending_node_id,
            "question": question,
        }

    # 完成/失败（F4：终态化 flow_runs）
    await flow_runs.finish_run(engine, tenant_id, exec_id, status=state.status.value)

    completed = [r for r in results if r.status == "completed"]
    outputs = {r.step_id: r.output for r in results if r.status == "completed"}

    # Chatflow 调试 trace：按拓扑序输出每节点 status/input/output/branch——
    # 分支决策来自 state.chosen（执行器不落 results，outputs/answer 语义不变），
    # 节点实际输入（模板解析后）来自 StepResult.input（flow 执行捕获）。
    results_by_id = {r.step_id: r for r in results}
    trace: list[dict[str, Any]] = []
    for item in plan.sequence:
        if isinstance(item, CondExec):
            side = state.chosen.get(item.branch_id)
            if side is None:
                trace.append(
                    {
                        "node_id": item.node_id,
                        "status": "skipped",
                        "branch": None,
                        "input": None,
                        "output": None,
                        "error": None,
                    }
                )
            else:
                trace.append(
                    {
                        "node_id": item.node_id,
                        "status": "completed",
                        "branch": side,
                        "input": None,
                        "output": {"branch": side},
                        "error": None,
                    }
                )
        else:
            r = results_by_id.get(item.node_id)
            if r is None:
                continue  # 防御：resume/重启路径无结果记录的节点不输出
            trace.append(
                {
                    "node_id": r.step_id,
                    "status": r.status,
                    "branch": None,
                    "input": r.input,
                    "output": r.output,
                    "error": r.error,
                    "latency_ms": r.latency_ms,
                }
            )

    # 助手消息：最后 completed 节点输出（text 优先，否则 JSON 摘要）
    answer = ""
    if completed:
        last = completed[-1].output or {}
        answer = str(last.get("text") or json.dumps(last, ensure_ascii=False))
    msg = await add_message(engine, tenant_id, conversation_id, "assistant", answer, user_id)

    citations: list[dict[str, Any]] = []
    for r in completed:
        if isinstance(r.output, dict) and r.output.get("citations"):
            citations.extend(r.output["citations"])
    if citations:
        await _set_citations(engine, tenant_id, msg["message_id"], citations)

    await _emit(
        "done",
        {
            "execution_id": exec_id,
            "conversation_id": conversation_id,
            "status": state.status.value,
            "message_id": msg["message_id"],
            "answer": answer,
        },
    )

    return {
        "execution_id": exec_id,
        "conversation_id": conversation_id,
        "status": state.status.value,
        "outputs": outputs,
        "trace": trace,
        "message_id": msg["message_id"],
        "answer": answer,
    }


def _flow_exec_kwargs(emit: Callable[[str, dict], Awaitable[None]]) -> dict[str, Callable[..., Awaitable[None]]]:
    """应用中心：flow 节点级 SSE 流式回调注入（仅 on_event 存在时启用——
    避免非流式路径意外切换到 LLM stream()，保持既有 complete() 语义）。"""

    async def node_start(nid: str, at: str) -> None:
        await emit("node_start", {"node_id": nid, "node_type": at})

    async def node_end(nid: str, meta: dict) -> None:
        await emit("node_end", {"node_id": nid, **meta})

    async def token(tok: str) -> None:
        await emit("token", {"text": tok})

    async def branch(bid: str, side: str) -> None:
        await emit("branch", {"branch_id": bid, "side": side})

    return {
        "on_node_start": node_start,
        "on_node_end": node_end,
        "on_token": token,
        "on_branch": branch,
    }


def _approval_ttl(settings) -> int:
    """Chatflow F4: 超时阈值（EARP_APPROVAL_TTL，默认 3600s）。settings 注入或兜底。"""
    ttl = getattr(settings, "approval_ttl", 3600)
    return max(1, int(ttl or 3600))


def _approval_expired(run: dict[str, Any], ttl: int) -> bool:
    """Chatflow F4: waiting_human run 是否超时（updated_at 超过 ttl）。"""
    from datetime import UTC, datetime, timedelta

    updated = run.get("updated_at")
    if updated is None:
        return False
    if isinstance(updated, str):
        try:
            updated = datetime.fromisoformat(updated.replace("Z", "+00:00"))
        except ValueError:
            return False
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=UTC)
    return datetime.now(UTC) - updated > timedelta(seconds=ttl)
