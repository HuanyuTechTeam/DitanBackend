"""Consultation REST and SSE endpoints, authenticated before streaming begins."""

from contextlib import aclosing
import json
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.deps import RequestContext, get_consultation_context
from app.schemas.common import APIResponse
from app.schemas.consultation import ConsultationCreate, TurnSubmit
from app.services.consultation.runner import Event
from app.services.consultation.service import ConsultationService, get_service

router = APIRouter()


def encode_event(event: Event) -> str:
    if event.name == "heartbeat":
        return ": heartbeat\n\n"
    return f"event: {event.name}\ndata: {json.dumps(event.data, ensure_ascii=False, separators=(',', ':'))}\n\n"


@router.post("", response_model=APIResponse)
async def create_consultation(
    payload: ConsultationCreate,
    ctx: RequestContext = Depends(get_consultation_context),
    service: ConsultationService = Depends(get_service),
):
    return APIResponse(
        success=True,
        message="问诊已就绪",
        data=await service.create_or_get(ctx, payload.model_dump(mode="json")),
    )


@router.get("/{consultation_id}", response_model=APIResponse)
async def get_consultation(
    consultation_id: UUID,
    ctx: RequestContext = Depends(get_consultation_context),
    service: ConsultationService = Depends(get_service),
):
    return APIResponse(
        success=True,
        message="查询成功",
        data=await service.get_snapshot(ctx, str(consultation_id)),
    )


@router.post("/{consultation_id}/turns")
async def submit_turn(
    consultation_id: UUID,
    payload: TurnSubmit,
    ctx: RequestContext = Depends(get_consultation_context),
    service: ConsultationService = Depends(get_service),
):
    # Admission may raise a normal JSON error before any SSE response headers are sent.
    handle = await service.submit_turn(
        ctx, str(consultation_id), payload.model_dump(mode="json")
    )

    async def stream():
        # Closing this subscription does not cancel the runner's independently owned task.
        async with aclosing(service.events(handle)) as events:
            async for event in events:
                yield encode_event(event)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{consultation_id}/turns/{turn_id}", response_model=APIResponse)
async def get_turn(
    consultation_id: UUID,
    turn_id: UUID,
    ctx: RequestContext = Depends(get_consultation_context),
    service: ConsultationService = Depends(get_service),
):
    return APIResponse(
        success=True,
        message="查询成功",
        data=await service.get_turn(ctx, str(consultation_id), str(turn_id)),
    )


@router.post("/{consultation_id}/abandon", response_model=APIResponse)
async def abandon(
    consultation_id: UUID,
    ctx: RequestContext = Depends(get_consultation_context),
    service: ConsultationService = Depends(get_service),
):
    return APIResponse(
        success=True,
        message="问诊已放弃",
        data=await service.abandon(ctx, str(consultation_id)),
    )


@router.get("/{consultation_id}/archive", response_model=APIResponse)
async def archive(
    consultation_id: UUID,
    ctx: RequestContext = Depends(get_consultation_context),
    service: ConsultationService = Depends(get_service),
):
    return APIResponse(
        success=True,
        message="归档读取成功",
        data=await service.archive(ctx, str(consultation_id)),
    )
