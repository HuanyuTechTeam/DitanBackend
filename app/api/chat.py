"""聊天 API 路由"""
import json

from fastapi import APIRouter, Depends, Path
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import RequestContext, get_request_context
from app.core import get_settings
from app.core.exceptions import NotFoundException, ValidationException
from app.models.chat import ChatConversation
from app.schemas import APIResponse
from app.schemas.chat import (
    ConversationCreate,
    ConversationResponse,
    ConversationDetailResponse,
    ChatMessageResponse,
    ChatRequest,
    ChatStreamRequest,
)
from app.services import ChatService

router = APIRouter()
settings = get_settings()


def get_chat_service() -> ChatService:
    """获取聊天服务实例"""
    return ChatService(
        api_key=settings.AI_API_KEY,
        base_url=settings.AI_BASE_URL,
        model_name=settings.AI_MODEL_NAME,
    )


@router.post("/conversation", response_model=APIResponse, status_code=201)
async def create_conversation(
    data: ConversationCreate,
    ctx: RequestContext = Depends(get_request_context),
):
    """创建新的聊天会话"""
    try:
        ctx.log_info("创建聊天会话")

        chat_service = get_chat_service()
        conversation = await chat_service.create_conversation(
            db=ctx.db,
            system_prompt=data.system_prompt,
            patient_id=data.patient_id,
            initial_context=data.initial_context,
        )

        await ctx.db.commit()

        ctx.log_info(f"会话创建成功: session_id={conversation.session_id}")
        return APIResponse(
            success=True,
            message="会话创建成功",
            data=ConversationResponse.model_validate(conversation).model_dump(),
        )
    except Exception as e:
        ctx.log_error("创建会话失败", e)
        raise ValidationException("创建会话失败", str(e))


@router.get("/conversation/{session_id}", response_model=APIResponse, status_code=200)
async def get_conversation(
    session_id: str = Path(..., description="会话ID"),
    ctx: RequestContext = Depends(get_request_context),
):
    """获取会话详情（包含消息历史）"""
    try:
        ctx.log_info(f"获取会话: session_id={session_id}")

        result = await ctx.db.execute(
            select(ChatConversation)
            .options(selectinload(ChatConversation.messages))
            .where(ChatConversation.session_id == session_id)
        )
        conversation = result.scalar_one_or_none()

        if not conversation:
            raise NotFoundException(f"会话不存在: {session_id}")

        ctx.log_info(f"获取成功: messages={len(conversation.messages)}")
        return APIResponse(
            success=True,
            message="获取会话成功",
            data=ConversationDetailResponse(
                conversation_id=conversation.conversation_id,
                session_id=conversation.session_id,
                title=conversation.title,
                system_prompt=conversation.system_prompt,
                is_active=conversation.is_active,
                created_at=conversation.created_at,
                updated_at=conversation.updated_at,
                messages=[
                    ChatMessageResponse(
                        message_id=msg.message_id,
                        role=msg.role.value,
                        content=msg.content,
                        created_at=msg.created_at,
                    )
                    for msg in conversation.messages
                ],
            ).model_dump(),
        )
    except NotFoundException:
        raise
    except Exception as e:
        ctx.log_error("获取会话失败", e)
        raise ValidationException("获取会话失败", str(e))


@router.post("/chat", response_model=APIResponse, status_code=200)
async def chat(
    data: ChatRequest,
    ctx: RequestContext = Depends(get_request_context),
):
    """发送消息（非流式）"""
    try:
        ctx.log_info(f"发送消息: session_id={data.session_id}")

        chat_service = get_chat_service()
        response = await chat_service.chat(
            db=ctx.db,
            session_id=data.session_id,
            user_message=data.content,
        )

        ctx.log_info(f"回复成功: response_length={len(response)}")
        return APIResponse(
            success=True,
            message="发送成功",
            data={"response": response},
        )
    except ValueError as e:
        raise NotFoundException(str(e))
    except Exception as e:
        ctx.log_error("发送消息失败", e)
        raise ValidationException("发送消息失败", str(e))


@router.post("/chat/stream", status_code=200)
async def chat_stream(
    data: ChatStreamRequest,
    ctx: RequestContext = Depends(get_request_context),
):
    """发送消息（流式返回）"""
    ctx.log_info(f"流式聊天: session_id={data.session_id}")

    chat_service = get_chat_service()

    # 检查会话是否存在
    conversation = await chat_service.get_conversation(ctx.db, data.session_id, load_messages=False)
    if not conversation:
        raise NotFoundException(f"会话不存在: {data.session_id}")

    if not conversation.is_active:
        raise ValidationException("会话已关闭", f"session_id={data.session_id}")

    async def generate():
        try:
            async for chunk in chat_service.chat_stream(
                db=ctx.db,
                session_id=data.session_id,
                user_message=data.content,
            ):
                yield chunk
        except Exception as e:
            ctx.log_error("流式聊天出错", e)
            yield f"event: error\ndata: {json.dumps({'message': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.delete("/conversation/{session_id}", response_model=APIResponse, status_code=200)
async def close_conversation(
    session_id: str = Path(..., description="会话ID"),
    ctx: RequestContext = Depends(get_request_context),
):
    """关闭会话"""
    try:
        ctx.log_info(f"关闭会话: session_id={session_id}")

        chat_service = get_chat_service()
        success = await chat_service.close_conversation(ctx.db, session_id)

        if not success:
            raise NotFoundException(f"会话不存在: {session_id}")

        ctx.log_info(f"会话已关闭: session_id={session_id}")
        return APIResponse(
            success=True,
            message="会话已关闭",
            data={"session_id": session_id},
        )
    except NotFoundException:
        raise
    except Exception as e:
        ctx.log_error("关闭会话失败", e)
        raise ValidationException("关闭会话失败", str(e))
