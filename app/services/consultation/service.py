"""Organization-scoped turn admission and atomic, attempt-fenced completion."""

import asyncio
from contextlib import aclosing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import logging

from sqlalchemy import func, or_, and_, select, update
from sqlalchemy.exc import IntegrityError

from app.core.database import async_session_maker
from app.core.exceptions import ConsultationError
from app.models.consultation import (
    Consultation,
    ConsultationMessage,
    ConsultationTurn,
    utcnow,
)
from app.services.consultation.llm import Prompt, get_llm
from app.services.consultation.rendering import (
    BEIJING,
    age_on,
    format_messages,
    render_patient,
    render_prompt,
)
from app.services.consultation.runner import Buffer, Event, TurnRunner, runner
from app.services.consultation.workflows import get_workflow

logger = logging.getLogger(__name__)
CLOSED = {"completed", "abandoned"}


def aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def message_data(message: ConsultationMessage) -> dict:
    return {
        key: getattr(message, key)
        for key in ("seq", "role", "kind", "step_id", "content", "turn_id", "meta")
    }


@dataclass(frozen=True)
class TurnHandle:
    org_id: str
    consultation_id: str
    turn_id: str
    attempt: int
    kind: str
    result: dict | None = None


@dataclass
class TurnLimits:
    question_deadline: float = 60
    question_task: float = 45
    report_deadline: float = 200
    report_task: float = 180


class ConsultationService:
    def __init__(
        self,
        session_maker=async_session_maker,
        *,
        llm=None,
        task_runner: TurnRunner = runner,
        limits: TurnLimits | None = None,
        poll_interval: float = 1,
        heartbeat: float = 15,
    ):
        self.sessions = session_maker
        self.llm = llm
        self.runner = task_runner
        self.limits = limits or TurnLimits()
        self.poll_interval = poll_interval
        self.heartbeat = heartbeat

    async def _consultation(self, db, org_id, consultation_id, *, lock=True):
        query = select(Consultation).where(
            Consultation.org_id == org_id, Consultation.id == consultation_id
        )
        if lock:
            query = query.with_for_update()
        value = await db.scalar(query.execution_options(populate_existing=True))
        if value is None:
            raise ConsultationError("NOT_FOUND", 404)
        return value

    async def _turn(self, db, org_id, consultation_id, turn_id):
        return await db.scalar(
            select(ConsultationTurn)
            .where(
                ConsultationTurn.org_id == org_id,
                ConsultationTurn.consultation_id == consultation_id,
                ConsultationTurn.turn_id == turn_id,
            )
            .execution_options(populate_existing=True)
        )

    async def _messages(self, db, consultation, turn_id=None):
        query = (
            select(ConsultationMessage)
            .where(
                ConsultationMessage.org_id == consultation.org_id,
                ConsultationMessage.consultation_id == consultation.id,
            )
            .order_by(ConsultationMessage.seq)
        )
        if turn_id is not None:
            query = query.where(ConsultationMessage.turn_id == turn_id)
        return [message_data(message) for message in (await db.scalars(query)).all()]

    def _turn_data(self, turn, consultation):
        expired = turn.status == "processing" and aware(turn.deadline_at) <= utcnow()
        status = "failed" if expired else turn.status
        retryable = (
            status == "failed"
            and consultation.version == turn.base_version
            and consultation.status not in CLOSED
        )
        return {
            "turn_id": turn.turn_id,
            "kind": turn.kind,
            "status": status,
            "input_text": turn.input_text,
            "base_version": turn.base_version,
            "attempt": turn.attempt,
            "retryable": retryable,
            "error_code": "TURN_TIMEOUT" if expired else turn.error_code,
        }

    async def _snapshot(self, db, consultation):
        turns = (
            await db.scalars(
                select(ConsultationTurn)
                .where(
                    ConsultationTurn.org_id == consultation.org_id,
                    ConsultationTurn.consultation_id == consultation.id,
                    ConsultationTurn.status.in_(["processing", "failed"]),
                )
                .order_by(ConsultationTurn.id.desc())
            )
        ).all()
        pending = None
        for turn in turns:
            candidate = self._turn_data(turn, consultation)
            if candidate["status"] == "processing":
                pending = candidate
                break
            if pending is None and candidate["retryable"]:
                pending = candidate
        return {
            "consultation_id": consultation.id,
            "encounter_uuid": consultation.encounter_uuid,
            "workflow_version": consultation.workflow_version,
            "status": consultation.status,
            "version": consultation.version,
            "can_report": consultation.status == "ready_for_report"
            and not (pending and pending["status"] == "processing"),
            "messages": await self._messages(db, consultation),
            "pending_turn": pending,
            "report": consultation.report_text,
        }

    async def _result(self, db, consultation, turn):
        messages = await self._messages(db, consultation, turn.turn_id)
        last = messages[-1]
        status = (
            "completed"
            if turn.kind == "report"
            else (
                "ready_for_report" if last["step_id"] == "report_gate" else "collecting"
            )
        )
        return {
            "turn_id": turn.turn_id,
            "messages": messages,
            "consultation": {
                "version": turn.base_version + 1,
                "status": status,
                "can_report": status == "ready_for_report",
            },
        }

    async def create_or_get(self, ctx, payload):
        principal = ctx.current_consultation
        org_id = principal.organization.org_id
        # A concurrent create can win the partial unique index; reload it in a new transaction.
        for retry in range(2):
            try:
                async with self.sessions() as db, db.begin():
                    existing = await db.scalar(
                        select(Consultation)
                        .where(
                            Consultation.org_id == org_id,
                            Consultation.encounter_uuid == payload["encounter_uuid"],
                            Consultation.status != "abandoned",
                        )
                        .with_for_update()
                    )
                    if existing is None:
                        existing = Consultation(
                            org_id=org_id,
                            encounter_uuid=payload["encounter_uuid"],
                            pre_diagnosis_uuid=payload.get("pre_diagnosis_uuid"),
                            inputs=payload["inputs"],
                            created_by_user_id=principal.user_id,
                            created_by_device_id=principal.device_id,
                        )
                        db.add(existing)
                    elif existing.version == 0:
                        existing.inputs = payload["inputs"]
                    await db.flush()
                    return await self._snapshot(db, existing)
            except IntegrityError:
                if retry:
                    raise

    async def get_snapshot(self, ctx, consultation_id):
        async with self.sessions() as db, db.begin():
            consultation = await self._consultation(
                db, ctx.organization.org_id, consultation_id
            )
            return await self._snapshot(db, consultation)

    async def get_turn(self, ctx, consultation_id, turn_id):
        return await self._get_turn(ctx.organization.org_id, consultation_id, turn_id)

    async def _get_turn(self, org_id, consultation_id, turn_id):
        async with self.sessions() as db, db.begin():
            consultation = await self._consultation(db, org_id, consultation_id)
            turn = await self._turn(db, org_id, consultation_id, turn_id)
            if turn is None:
                raise ConsultationError("NOT_FOUND", 404)
            result = self._turn_data(turn, consultation)
            if turn.status == "completed":
                result["result"] = await self._result(db, consultation, turn)
            return result

    async def _active(self, db, consultation):
        return await db.scalar(
            select(ConsultationTurn).where(
                ConsultationTurn.org_id == consultation.org_id,
                ConsultationTurn.consultation_id == consultation.id,
                ConsultationTurn.status == "processing",
            )
        )

    async def _expire_other(self, db, consultation, turn_id):
        active = await self._active(db, consultation)
        if active is None or active.turn_id == turn_id:
            return
        if aware(active.deadline_at) > utcnow():
            raise ConsultationError("SESSION_BUSY", turn_id=active.turn_id)
        await db.execute(
            update(ConsultationTurn)
            .where(
                ConsultationTurn.org_id == consultation.org_id,
                ConsultationTurn.id == active.id,
                ConsultationTurn.attempt == active.attempt,
                ConsultationTurn.status == "processing",
                ConsultationTurn.deadline_at <= utcnow(),
            )
            .values(status="failed", error_code="TURN_TIMEOUT")
        )

    def _validate_kind(self, consultation, kind, text):
        if consultation.status in CLOSED:
            raise ConsultationError("CONSULTATION_CLOSED")
        if kind == "report":
            if consultation.status != "ready_for_report":
                raise ConsultationError("REPORT_NOT_READY")
        elif kind == "start":
            if consultation.version != 0 or consultation.status != "collecting":
                raise ConsultationError("INVALID_TURN", 409)
        elif kind == "answer":
            if consultation.version < 1 or not text or len(text) > 2000:
                raise ConsultationError("INVALID_TURN", 400)
        else:
            raise ConsultationError("INVALID_TURN", 400)

    async def submit_turn(self, ctx, consultation_id, payload) -> TurnHandle:
        principal = ctx.current_consultation
        org_id = principal.organization.org_id
        kind, turn_id = payload["kind"], payload["turn_id"]
        text = payload.get("text") or ""
        if not isinstance(text, str):
            raise ConsultationError("INVALID_TURN", 400)
        text = text.strip()
        launch = False
        result = None
        async with self.sessions() as db, db.begin():
            consultation = await self._consultation(db, org_id, consultation_id)
            turn = await self._turn(db, org_id, consultation_id, turn_id)
            if turn is not None:
                if turn.kind != kind or (turn.input_text or "").strip() != text:
                    raise ConsultationError("TURN_ID_CONFLICT")
                if turn.status == "completed":
                    result = await self._result(db, consultation, turn)
                elif turn.status == "processing" and aware(turn.deadline_at) > utcnow():
                    pass
                else:
                    self._validate_kind(consultation, kind, text)
                    if (
                        consultation.version != payload["base_version"]
                        or turn.base_version != consultation.version
                    ):
                        raise ConsultationError(
                            "VERSION_CONFLICT",
                            snapshot=await self._snapshot(db, consultation),
                        )
                    await self._expire_other(db, consultation, turn_id)
                    previous_attempt = turn.attempt
                    changed = await db.execute(
                        update(ConsultationTurn)
                        .where(
                            ConsultationTurn.org_id == org_id,
                            ConsultationTurn.id == turn.id,
                            ConsultationTurn.attempt == previous_attempt,
                            or_(
                                ConsultationTurn.status == "failed",
                                and_(
                                    ConsultationTurn.status == "processing",
                                    ConsultationTurn.deadline_at <= utcnow(),
                                ),
                            ),
                        )
                        .values(
                            attempt=previous_attempt + 1,
                            status="processing",
                            error_code=None,
                            completed_at=None,
                            deadline_at=self._deadline(kind),
                        )
                    )
                    launch = changed.rowcount == 1
                    await db.refresh(turn)
            else:
                self._validate_kind(consultation, kind, text)
                if consultation.version != payload["base_version"]:
                    raise ConsultationError(
                        "VERSION_CONFLICT",
                        snapshot=await self._snapshot(db, consultation),
                    )
                await self._expire_other(db, consultation, turn_id)
                turn = ConsultationTurn(
                    org_id=org_id,
                    consultation_id=consultation_id,
                    turn_id=turn_id,
                    kind=kind,
                    input_text=text,
                    base_version=consultation.version,
                    actor_user_id=principal.user_id,
                    actor_device_id=principal.device_id,
                    deadline_at=self._deadline(kind),
                )
                db.add(turn)
                await db.flush()
                launch = True
            handle = TurnHandle(
                org_id, consultation_id, turn_id, turn.attempt, kind, result
            )
        if launch:
            self.runner.start(
                (consultation_id, turn_id, handle.attempt),
                lambda buffer: self._run(handle, buffer),
            )
        return handle

    def _deadline(self, kind):
        return utcnow() + timedelta(
            seconds=self.limits.report_deadline
            if kind == "report"
            else self.limits.question_deadline
        )

    async def events(self, handle: TurnHandle):
        yield Event("accepted", {"turn_id": handle.turn_id, "attempt": handle.attempt})
        if handle.result is not None:
            yield Event("completed", handle.result)
            return
        buffer = self.runner.entries.get(
            (handle.consultation_id, handle.turn_id, handle.attempt)
        )
        if buffer is not None:
            async with aclosing(buffer.subscribe(self.heartbeat)) as stream:
                async for event in stream:
                    yield event
            return
        # Another worker owns this attempt. Its committed result remains discoverable.
        attempt = handle.attempt
        if attempt > 1:
            yield Event("reset", {"attempt": attempt})
        last_heartbeat = asyncio.get_running_loop().time()
        while True:
            turn = await self._get_turn(
                handle.org_id, handle.consultation_id, handle.turn_id
            )
            if turn["attempt"] != attempt:
                attempt = turn["attempt"]
                yield Event("reset", {"attempt": attempt})
            if turn["status"] == "completed":
                yield Event("completed", turn["result"])
                return
            if turn["status"] != "processing":
                yield Event(
                    "error",
                    {
                        "code": turn["error_code"] or "TURN_CANCELLED",
                        "retryable": turn["retryable"],
                    },
                )
                return
            if asyncio.get_running_loop().time() - last_heartbeat >= self.heartbeat:
                yield Event("heartbeat", {})
                last_heartbeat = asyncio.get_running_loop().time()
            await asyncio.sleep(self.poll_interval)

    async def _load_execution(self, handle):
        async with self.sessions() as db, db.begin():
            consultation = await self._consultation(
                db, handle.org_id, handle.consultation_id
            )
            turn = await self._turn(
                db, handle.org_id, handle.consultation_id, handle.turn_id
            )
            if (
                turn.attempt != handle.attempt
                or turn.status != "processing"
                or consultation.status in CLOSED
            ):
                return None
            return {
                "kind": turn.kind,
                "text": turn.input_text,
                "base_version": turn.base_version,
                "inputs": consultation.inputs,
                "user_input": consultation.user_input_text,
                "state": consultation.workflow_state,
                "status": consultation.status,
                "workflow_version": consultation.workflow_version,
                "created_at": aware(consultation.created_at),
                "messages": await self._messages(db, consultation),
            }

    async def _run(self, handle, buffer):
        try:
            total = (
                self.limits.report_task
                if handle.kind == "report"
                else self.limits.question_task
            )
            async with asyncio.timeout(total):
                execution = await self._load_execution(handle)
                if execution is None:
                    await buffer.publish(
                        "error", {"code": "TURN_SUPERSEDED", "retryable": False}
                    )
                    return
                if handle.attempt > 1:
                    await buffer.publish("reset", {"attempt": handle.attempt})
                output = await self._generate(handle, execution, buffer)
                result = await self._commit(handle, execution, output)
            if result is not None:
                await buffer.publish("completed", result)
            else:
                await buffer.publish(
                    "error", {"code": "TURN_SUPERSEDED", "retryable": False}
                )
        except Exception as exc:
            await self._fail(
                handle,
                exc.code if isinstance(exc, ConsultationError) else "MODEL_UNAVAILABLE",
            )
            turn = await self._get_turn(
                handle.org_id, handle.consultation_id, handle.turn_id
            )
            if turn["status"] == "completed":
                await buffer.publish("completed", turn["result"])
            else:
                await buffer.publish(
                    "error",
                    {
                        "code": turn["error_code"] or "MODEL_UNAVAILABLE",
                        "retryable": turn["retryable"],
                    },
                )

    async def _generate(self, handle, execution, buffer):
        workflow = get_workflow(execution["workflow_version"])
        state = dict(execution["state"])
        user_input = execution["user_input"]
        kind = execution["kind"]
        if kind == "start":
            basis = execution["created_at"].astimezone(BEIJING).date()
            patient = execution["inputs"].get("patient") or {}
            state = {
                "sex": patient.get("sex"),
                "age": age_on(patient.get("birthday"), basis),
                "age_basis_date": basis.isoformat(),
            }
            user_input = render_patient(execution["inputs"], basis)
            step = workflow.first_step(
                workflow.WorkflowContext(state["sex"], state["age"])
            )
        elif kind == "report":
            step = None
        elif execution["status"] == "ready_for_report":
            step = workflow.ReportGate()
        else:
            step = workflow.next_step(
                state["current_step"],
                workflow.WorkflowContext(state["sex"], state["age"]),
            )
        step_id = "report" if step is None else step.id
        if step is not None:
            state["current_step"] = step.id
        offset = 0
        chunks = []
        fallback = False

        async def emit(text):
            nonlocal offset
            await buffer.publish(
                "delta", {"attempt": handle.attempt, "offset": offset, "text": text}
            )
            offset += len(text)
            chunks.append(text)

        if isinstance(step, workflow.ReportGate):
            await emit(step.text)
            status = "ready_for_report"
        else:
            prompt_id = workflow.REPORT_PROMPT if step is None else step.prompt_id
            previous = next(
                (
                    m["content"]
                    for m in reversed(execution["messages"])
                    if m["role"] == "assistant"
                ),
                "",
            )
            system, user = render_prompt(
                prompt_id,
                user_input=user_input,
                output=previous,
                input_text=execution["text"] or "",
                message_list=format_messages(execution["messages"]),
            )
            prompt = Prompt(
                handle.org_id,
                handle.consultation_id,
                handle.turn_id,
                handle.attempt,
                step_id,
                f"{execution['workflow_version']}:{prompt_id}",
                system,
                user,
                "" if step is None else step.fixed_question,
            )
            llm = self.llm or get_llm()
            stream = (
                llm.stream_report(prompt)
                if kind == "report"
                else llm.stream_question(prompt)
            )
            try:
                async with aclosing(stream):
                    async for text in stream:
                        await emit(text)
            except Exception:
                if kind == "report":
                    raise
                fallback = True
                if offset:
                    await buffer.publish(
                        "reset", {"attempt": handle.attempt, "reason": "fixed_question"}
                    )
                offset = 0
                chunks.clear()
                await emit(step.fixed_question)
            status = "completed" if kind == "report" else "collecting"
        return {
            "content": "".join(chunks),
            "step_id": step_id,
            "state": state,
            "user_input": user_input,
            "status": status,
            "fallback": fallback,
        }

    async def _commit(self, handle, execution, output):
        async with self.sessions() as db, db.begin():
            consultation = await self._consultation(
                db, handle.org_id, handle.consultation_id
            )
            if (
                consultation.status in CLOSED
                or consultation.version != execution["base_version"]
            ):
                return None
            # If editable pre-start inputs changed during generation, retry with the new inputs.
            if (
                execution["kind"] == "start"
                and consultation.inputs != execution["inputs"]
            ):
                raise ConsultationError("INPUTS_CHANGED")
            changed = await db.execute(
                update(ConsultationTurn)
                .where(
                    ConsultationTurn.org_id == handle.org_id,
                    ConsultationTurn.consultation_id == handle.consultation_id,
                    ConsultationTurn.turn_id == handle.turn_id,
                    ConsultationTurn.attempt == handle.attempt,
                    ConsultationTurn.status == "processing",
                )
                .values(status="completed", completed_at=utcnow(), error_code=None)
            )
            if changed.rowcount == 0:
                return None
            seq = await db.scalar(
                select(func.coalesce(func.max(ConsultationMessage.seq), 0)).where(
                    ConsultationMessage.org_id == handle.org_id,
                    ConsultationMessage.consultation_id == handle.consultation_id,
                )
            )
            if execution["kind"] == "answer":
                seq += 1
                db.add(
                    ConsultationMessage(
                        org_id=handle.org_id,
                        consultation_id=handle.consultation_id,
                        seq=seq,
                        role="user",
                        kind="answer",
                        step_id=execution["state"]["current_step"],
                        content=execution["text"],
                        turn_id=handle.turn_id,
                    )
                )
            db.add(
                ConsultationMessage(
                    org_id=handle.org_id,
                    consultation_id=handle.consultation_id,
                    seq=seq + 1,
                    role="assistant",
                    kind=execution["kind"],
                    step_id=output["step_id"],
                    content=output["content"],
                    turn_id=handle.turn_id,
                    meta={
                        "prompt_version": execution["workflow_version"],
                        "fallback": output["fallback"],
                    },
                )
            )
            consultation.version += 1
            consultation.status = output["status"]
            consultation.workflow_state = output["state"]
            consultation.user_input_text = output["user_input"]
            if execution["kind"] == "report":
                consultation.report_text = output["content"]
                consultation.completed_at = utcnow()
            await db.flush()
            turn = await self._turn(
                db, handle.org_id, handle.consultation_id, handle.turn_id
            )
            return await self._result(db, consultation, turn)

    async def _fail(self, handle, code="MODEL_UNAVAILABLE"):
        async with self.sessions() as db, db.begin():
            await self._consultation(db, handle.org_id, handle.consultation_id)
            await db.execute(
                update(ConsultationTurn)
                .where(
                    ConsultationTurn.org_id == handle.org_id,
                    ConsultationTurn.consultation_id == handle.consultation_id,
                    ConsultationTurn.turn_id == handle.turn_id,
                    ConsultationTurn.attempt == handle.attempt,
                    ConsultationTurn.status == "processing",
                )
                .values(status="failed", error_code=code)
            )

    async def abandon(self, ctx, consultation_id):
        async with self.sessions() as db, db.begin():
            consultation = await self._consultation(
                db, ctx.organization.org_id, consultation_id
            )
            if consultation.status == "completed":
                raise ConsultationError("CONSULTATION_CLOSED")
            if consultation.status != "abandoned":
                active = await self._active(db, consultation)
                if active is not None:
                    await db.execute(
                        update(ConsultationTurn)
                        .where(
                            ConsultationTurn.org_id == ctx.organization.org_id,
                            ConsultationTurn.id == active.id,
                            ConsultationTurn.attempt == active.attempt,
                            ConsultationTurn.status == "processing",
                        )
                        .values(status="cancelled", error_code="CONSULTATION_CLOSED")
                    )
                consultation.status = "abandoned"
                await db.flush()
            return await self._snapshot(db, consultation)

    async def archive(self, ctx, consultation_id):
        async with self.sessions() as db, db.begin():
            consultation = await self._consultation(
                db, ctx.organization.org_id, consultation_id
            )
            if consultation.status != "completed":
                raise ConsultationError("REPORT_NOT_READY")
            return {
                "diagnosis_result": consultation.report_text,
                "conversation_log": format_messages(
                    await self._messages(db, consultation), archive=True
                ),
            }


@lru_cache(maxsize=1)
def get_service():
    return ConsultationService()
