"""聊天相关的Pydantic模型"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class ChatMessageCreate(BaseModel):
    """发送消息请求"""

    content: str = Field(..., min_length=1, max_length=10000, description="消息内容")


class ChatMessageResponse(BaseModel):
    """消息响应"""

    message_id: int
    role: str
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


class ConversationCreate(BaseModel):
    """创建会话请求"""

    system_prompt: Optional[str] = Field(
        None, description="系统提示词，不传则使用默认提示词"
    )
    patient_id: Optional[int] = Field(None, description="关联的患者ID")
    initial_context: Optional[str] = Field(
        None, description="初始上下文信息（如健康报告）"
    )


class ConversationResponse(BaseModel):
    """会话响应"""

    conversation_id: int
    session_id: str
    title: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ConversationDetailResponse(BaseModel):
    """会话详情响应（包含消息历史）"""

    conversation_id: int
    session_id: str
    title: Optional[str]
    system_prompt: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime
    messages: List[ChatMessageResponse]

    class Config:
        from_attributes = True


class ChatStreamRequest(BaseModel):
    """流式聊天请求"""

    session_id: str = Field(..., description="会话ID")
    content: str = Field(..., min_length=1, max_length=10000, description="消息内容")


class ChatRequest(BaseModel):
    """普通聊天请求（非流式）"""

    session_id: str = Field(..., description="会话ID")
    content: str = Field(..., min_length=1, max_length=10000, description="消息内容")
