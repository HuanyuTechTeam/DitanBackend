"""OpenAI客户端服务"""

from typing import List, Optional, Any, cast, AsyncGenerator

import httpx
import openai
from openai.types.chat import (
    ChatCompletionMessageParam,
    ChatCompletionUserMessageParam,
    ChatCompletionSystemMessageParam,
)

from app.core import get_logger

logger = get_logger(__name__)

STREAM_TIMEOUT = httpx.Timeout(connect=30.0, read=120.0, write=30.0, pool=30.0)


class OpenAIChatCompletion:
    """OpenAI Chat Completion API 封装类"""

    def __init__(self, api_key: str, base_url: str, model_name: str):
        self.api_key = api_key
        self.base_url = base_url
        self.model_name = model_name

        self.client = openai.OpenAI(
            api_key=api_key, base_url=base_url, timeout=STREAM_TIMEOUT
        )
        self.async_client = openai.AsyncOpenAI(
            api_key=api_key, base_url=base_url, timeout=STREAM_TIMEOUT
        )
        logger.info(f"OpenAI客户端初始化: model={model_name}")

    def chat(
        self,
        messages: List[ChatCompletionMessageParam],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        **kwargs,
    ) -> Any:
        """发送聊天完成请求"""
        try:
            return self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=stream,
                **kwargs,
            )
        except Exception as e:
            logger.error(f"OpenAI API 调用失败: {e}")
            raise

    def simple_chat(
        self,
        user_message: str,
        system_message: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> str:
        """简单的单轮对话"""
        messages: List[ChatCompletionMessageParam] = []

        if system_message:
            messages.append(
                cast(
                    ChatCompletionSystemMessageParam,
                    {"role": "system", "content": system_message},
                )
            )

        messages.append(
            cast(
                ChatCompletionUserMessageParam,
                {"role": "user", "content": user_message},
            )
        )

        response = self.chat(
            messages=messages, temperature=temperature, max_tokens=max_tokens
        )
        return response.choices[0].message.content

    def stream_chat(
        self,
        messages: List[ChatCompletionMessageParam],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ):
        """流式聊天（同步）"""
        response = self.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            **kwargs,
        )

        for chunk in response:
            if chunk.choices[0].delta.content is not None:
                yield chunk.choices[0].delta.content

    async def async_stream_chat(
        self,
        messages: List[ChatCompletionMessageParam],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        """异步流式聊天"""
        try:
            response = await self.async_client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
                **kwargs,
            )

            async for chunk in response:
                if chunk.choices[0].delta.content is not None:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            logger.error(f"异步流式调用失败: {e}")
            raise

    def get_model_info(self) -> dict:
        """获取模型配置信息"""
        return {
            "model_name": self.model_name,
            "base_url": self.base_url,
            "api_key_preview": f"{self.api_key[:8]}...{self.api_key[-4:]}"
            if len(self.api_key) > 12
            else "***",
        }
