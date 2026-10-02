"""聊天服务 - 处理AI对话和上下文管理"""

import json
import uuid
from typing import Optional, List, AsyncGenerator, cast

from openai.types.chat import (
    ChatCompletionMessageParam,
    ChatCompletionUserMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionAssistantMessageParam,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core import get_logger
from app.core.organization import OrganizationContext
from app.core.exceptions import NotFoundException
from app.repositories.patient_repository import PatientRepository
from app.models.chat import ChatConversation, ChatMessage, MessageRole
from app.services.openai_client import OpenAIChatCompletion

logger = get_logger(__name__)

DEFAULT_SYSTEM_PROMPT = """你是一位专业的中医健康顾问，名叫"小康"。你的职责是：
1. 根据患者提供的健康信息，进行专业的中医健康分析
2. 以亲切、专业的方式与患者交流
3. 询问必要的问诊信息以完善诊断
4. 提供基于中医理论的健康建议

注意事项：
- 使用通俗易懂的语言解释专业术语
- 保持回答简洁明了，每次回复控制在200字以内
- 询问患者时一次只问1-2个问题
- 当收集到足够信息时，提示用户可以获取详细报告"""

MAX_CONTEXT_MESSAGES = 20


class ChatService:
    """聊天服务类"""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model_name: str,
        organization: OrganizationContext,
    ):
        self.organization = organization
        self._ai_config = {
            "api_key": api_key,
            "base_url": base_url,
            "model_name": model_name,
        }
        self._ai_client: Optional[OpenAIChatCompletion] = None
        logger.info(f"ChatService初始化: model={model_name}")

    @property
    def ai_client(self) -> OpenAIChatCompletion:
        if self._ai_client is None:
            self._ai_client = OpenAIChatCompletion(**self._ai_config)
        return self._ai_client

    async def create_conversation(
        self,
        db: AsyncSession,
        system_prompt: Optional[str] = None,
        patient_id: Optional[int] = None,
        initial_context: Optional[str] = None,
    ) -> ChatConversation:
        """创建新的聊天会话"""
        if patient_id is not None:
            patient = await PatientRepository(db, self.organization).get_by_patient_id(
                patient_id
            )
            if patient is None:
                raise NotFoundException("未找到患者")
        session_id = str(uuid.uuid4())

        final_system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
        if initial_context:
            final_system_prompt = (
                f"{final_system_prompt}\n\n## 患者健康信息\n{initial_context}"
            )

        conversation = ChatConversation(
            org_id=self.organization.org_id,
            session_id=session_id,
            patient_id=patient_id,
            system_prompt=final_system_prompt,
            is_active=True,
        )
        db.add(conversation)
        await db.flush()
        await db.refresh(conversation)

        logger.info(
            f"创建会话: conversation_id={conversation.conversation_id}, session_id={session_id}"
        )
        return conversation

    async def get_conversation(
        self,
        db: AsyncSession,
        session_id: str,
        load_messages: bool = True,
    ) -> Optional[ChatConversation]:
        """获取会话"""
        query = select(ChatConversation).where(
            ChatConversation.session_id == session_id,
            ChatConversation.org_id == self.organization.org_id,
        )
        if load_messages:
            query = query.options(
                selectinload(ChatConversation.messages)
            ).execution_options(populate_existing=True)

        result = await db.execute(query)
        return result.scalar_one_or_none()

    async def add_message(
        self,
        db: AsyncSession,
        conversation_id: int,
        role: MessageRole,
        content: str,
        tokens: Optional[int] = None,
    ) -> ChatMessage:
        """添加消息到会话"""
        parent = await db.scalar(
            select(ChatConversation.conversation_id).where(
                ChatConversation.conversation_id == conversation_id,
                ChatConversation.org_id == self.organization.org_id,
            )
        )
        if parent is None:
            raise NotFoundException("会话不存在")
        message = ChatMessage(
            conversation_id=conversation_id,
            role=role,
            content=content,
            tokens=tokens,
        )
        db.add(message)
        await db.flush()
        await db.refresh(message)
        return message

    def _build_messages(
        self,
        conversation: ChatConversation,
        user_message: str,
    ) -> List[ChatCompletionMessageParam]:
        """构建发送给AI的消息列表"""
        messages: List[ChatCompletionMessageParam] = []

        if conversation.system_prompt:
            messages.append(
                cast(
                    ChatCompletionSystemMessageParam,
                    {"role": "system", "content": conversation.system_prompt},
                )
            )

        history_messages = (
            conversation.messages[-MAX_CONTEXT_MESSAGES:]
            if conversation.messages
            else []
        )
        for msg in history_messages:
            if msg.role == MessageRole.USER:
                messages.append(
                    cast(
                        ChatCompletionUserMessageParam,
                        {"role": "user", "content": msg.content},
                    )
                )
            elif msg.role == MessageRole.ASSISTANT:
                messages.append(
                    cast(
                        ChatCompletionAssistantMessageParam,
                        {"role": "assistant", "content": msg.content},
                    )
                )

        messages.append(
            cast(
                ChatCompletionUserMessageParam,
                {"role": "user", "content": user_message},
            )
        )

        return messages

    async def chat(
        self,
        db: AsyncSession,
        session_id: str,
        user_message: str,
    ) -> str:
        """非流式聊天"""
        conversation = await self.get_conversation(db, session_id, load_messages=True)
        if not conversation:
            raise NotFoundException("会话不存在")

        if not conversation.is_active:
            raise ValueError(f"会话已关闭: {session_id}")

        await self.add_message(
            db, conversation.conversation_id, MessageRole.USER, user_message
        )

        messages = self._build_messages(conversation, user_message)

        response_obj = self.ai_client.client.chat.completions.create(
            model=self.ai_client.model_name,
            messages=messages,
            temperature=0.7,
        )
        ai_response = response_obj.choices[0].message.content or ""

        await self.add_message(
            db, conversation.conversation_id, MessageRole.ASSISTANT, ai_response
        )

        if len(conversation.messages) <= 2 and not conversation.title:
            conversation.title = user_message[:50] + (
                "..." if len(user_message) > 50 else ""
            )

        await db.commit()
        return ai_response

    async def chat_stream(
        self,
        db: AsyncSession,
        session_id: str,
        user_message: str,
    ) -> AsyncGenerator[str, None]:
        """流式聊天"""
        conversation = await self.get_conversation(db, session_id, load_messages=True)
        if not conversation:
            raise NotFoundException("会话不存在")

        if not conversation.is_active:
            raise ValueError(f"会话已关闭: {session_id}")

        await self.add_message(
            db, conversation.conversation_id, MessageRole.USER, user_message
        )
        await db.commit()

        messages = self._build_messages(conversation, user_message)

        full_response = ""
        try:
            async for chunk in self.ai_client.async_stream_chat(
                messages, temperature=0.7
            ):
                full_response += chunk
                yield f"data: {json.dumps({'content': chunk}, ensure_ascii=False)}\n\n"

            await self.add_message(
                db, conversation.conversation_id, MessageRole.ASSISTANT, full_response
            )

            if len(conversation.messages) <= 2 and not conversation.title:
                conversation.title = user_message[:50] + (
                    "..." if len(user_message) > 50 else ""
                )

            await db.commit()

            yield f"event: done\ndata: {json.dumps({'message': 'completed'}, ensure_ascii=False)}\n\n"

        except Exception as e:
            logger.error(f"流式聊天出错: {e}")
            yield f"event: error\ndata: {json.dumps({'message': str(e)}, ensure_ascii=False)}\n\n"
            raise

    async def close_conversation(
        self,
        db: AsyncSession,
        session_id: str,
    ) -> bool:
        """关闭会话"""
        conversation = await self.get_conversation(db, session_id, load_messages=False)
        if not conversation:
            return False

        conversation.is_active = False
        await db.commit()
        logger.info(f"关闭会话: session_id={session_id}")
        return True

    async def get_conversation_history(
        self,
        db: AsyncSession,
        session_id: str,
    ) -> Optional[ChatConversation]:
        """获取会话历史"""
        return await self.get_conversation(db, session_id, load_messages=True)
