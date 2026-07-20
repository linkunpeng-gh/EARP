"""M12 Saga compensation tests — multi-step execution with rollback."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from earp_server.config import Settings
from earp_server.main import create_app
from earp_server.orchestrator.multi_step import ExecutionStatus, MultiStepExecutor
from earp_server.orchestrator.types import InvokeContext, Step


def _uid(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:8]}"


class TestSagaCompensation:
    """M12: multi-step execution with Saga rollback on failure."""

    async def test_saga_rollback_on_step_failure(self, migrated: str, app_url: str) -> None:
        """Step 1 succeeds → Step 2 fails → Step 1 gets compensated."""
        app = create_app(Settings(database_url=app_url, app_env="test"))
        with TestClient(app):
            executor = MultiStepExecutor(app.state.engine)

            step1 = Step(
                step_id=_uid("s"),
                capability_call={"adapter_type": "demo.echo", "input": {"msg": "hello"}},
                compensate_call={"adapter_type": "demo.echo", "input": {"msg": "undo-s1"}},
            )
            step2 = Step(
                step_id=_uid("s"),
                capability_call={"adapter_type": "nonexistent.fail", "input": {}},
                compensate_call={"adapter_type": "demo.echo", "input": {"msg": "undo-s2"}},
            )
            steps = [step1, step2]
            ctx = InvokeContext(
                tenant_id="t1", execution_id=_uid("exec-"), session_id=_uid("sess-"),
                user_id="u1", role_id="r1", step=step1,
            )

            results, state = await executor.execute(steps, ctx, layers=[])

            assert len(results) == 2
            assert results[0].status == "completed"
            assert results[1].status == "failed"
            assert state.status == ExecutionStatus.ROLLED_BACK
            assert len(state.rollback_results) == 1
            assert state.rollback_results[0]["step_id"] == step1.step_id
            assert state.rollback_results[0]["status"] == "rolled_back"

    async def test_saga_no_rollback_when_no_compensate(self, migrated: str, app_url: str) -> None:
        """Step fails but has no compensate_call → no rollback, just FAILED status."""
        app = create_app(Settings(database_url=app_url, app_env="test"))
        with TestClient(app):
            executor = MultiStepExecutor(app.state.engine)

            step1 = Step(
                step_id=_uid("s"),
                capability_call={"adapter_type": "nonexistent.fail", "input": {}},
            )
            ctx = InvokeContext(
                tenant_id="t1", execution_id=_uid("exec-"), session_id=_uid("sess-"),
                user_id="u1", role_id="r1", step=step1,
            )

            results, state = await executor.execute([step1], ctx, layers=[])

            assert results[0].status == "failed"
            assert state.status == ExecutionStatus.FAILED
            assert len(state.rollback_results) == 0

    async def test_saga_all_steps_succeed_no_rollback(self, migrated: str, app_url: str) -> None:
        """All steps succeed → no compensation triggered."""
        app = create_app(Settings(database_url=app_url, app_env="test"))
        with TestClient(app):
            executor = MultiStepExecutor(app.state.engine)

            step1 = Step(
                step_id=_uid("s"),
                capability_call={"adapter_type": "demo.echo", "input": {"msg": "a"}},
                compensate_call={"adapter_type": "demo.echo", "input": {"msg": "undo-a"}},
            )
            step2 = Step(
                step_id=_uid("s"),
                capability_call={"adapter_type": "demo.echo", "input": {"msg": "b"}},
                compensate_call={"adapter_type": "demo.echo", "input": {"msg": "undo-b"}},
            )
            ctx = InvokeContext(
                tenant_id="t1", execution_id=_uid("exec-"), session_id=_uid("sess-"),
                user_id="u1", role_id="r1", step=step1,
            )

            results, state = await executor.execute([step1, step2], ctx, layers=[])

            assert len(results) == 2
            assert results[0].status == "completed"
            assert results[1].status == "completed"
            assert state.status == ExecutionStatus.COMPLETED
            assert len(state.rollback_results) == 0


class TestNoCompensateCall:
    """M5 backward compatibility: steps without compensate_call still work."""

    async def test_existing_behavior_unchanged(self, migrated: str, app_url: str) -> None:
        """Steps without compensate_call execute normally (no rollback)."""
        app = create_app(Settings(database_url=app_url, app_env="test"))
        with TestClient(app):
            executor = MultiStepExecutor(app.state.engine)

            step = Step(
                step_id=_uid("s"),
                capability_call={"adapter_type": "demo.echo", "input": {"msg": "test"}},
            )
            ctx = InvokeContext(
                tenant_id="t1", execution_id=_uid("exec-"), session_id=_uid("sess-"),
                user_id="u1", role_id="r1", step=step,
            )

            results, state = await executor.execute([step], ctx, layers=[])

            assert len(results) == 1
            assert results[0].status == "completed"
            assert state.status == ExecutionStatus.COMPLETED
