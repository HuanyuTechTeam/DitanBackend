"""聊天会话与消息数据库模型"""

from datetime import datetime
from typing import Optional, List
from enum import Enum as PyEnum

from sqlalchemy import String, Text, DateTime, Integer, ForeignKey, Enum, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class MessageRole(str, PyEnum):
    """消息角色"""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class ChatConversation(Base):
    """聊天会话"""

    __tablename__ = "chat_conversations"

    conversation_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    # 会话唯一标识，用于客户端标识会话
    session_id: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    # 可选关联患者
    patient_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("patients.patient_id"), nullable=True, index=True
    )
    # 会话标题（可选，可由第一条消息生成）
    title: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    # 系统提示词
    system_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 是否活跃
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # 时间戳
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # 关联
    messages: Mapped[List["ChatMessage"]] = relationship(
        "ChatMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ChatMessage.created_at",
    )

    def __repr__(self) -> str:
        return f"<ChatConversation(conversation_id={self.conversation_id}, session_id={self.session_id})>"


class ChatMessage(Base):
    """聊天消息"""

    __tablename__ = "chat_messages"

    message_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    conversation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("chat_conversations.conversation_id"),
        nullable=False,
        index=True,
    )
    # 消息角色
    role: Mapped[MessageRole] = mapped_column(Enum(MessageRole), nullable=False)
    # 消息内容
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # 消息元数据（可选，存储token数量等信息）
    tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # 时间戳
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    # 关联
    conversation: Mapped["ChatConversation"] = relationship(
        "ChatConversation", back_populates="messages"
    )

    def __repr__(self) -> str:
        return f"<ChatMessage(message_id={self.message_id}, role={self.role})>"
