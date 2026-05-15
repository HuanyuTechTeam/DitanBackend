from typing import List, Dict, Any, Optional, cast

import openai
from openai.types.chat import (
    ChatCompletionMessageParam,
    ChatCompletionUserMessageParam,
    ChatCompletionSystemMessageParam,
)


class OpenAIChatCompletion:
    """
    OpenAI Chat Completion API的简单封装类

    用于方便地调用OpenAI的聊天完成API，支持自定义API密钥、基础URL和模型名称。
    """

    def __init__(self, api_key: str, base_url: str, model_name: str):
        """
        初始化OpenAI Chat Completion客户端

        Args:
            api_key (str): OpenAI API密钥
            base_url (str): API基础URL
            model_name (str): 要使用的模型名称
        """
        self.api_key = api_key
        self.base_url = base_url
        self.model_name = model_name

        # 初始化OpenAI客户端
        self.client = openai.OpenAI(api_key=self.api_key, base_url=self.base_url)

    def chat(
        self,
        messages: List[ChatCompletionMessageParam],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        **kwargs,
    ) -> Any:
        """
        发送聊天完成请求

        Args:
            messages (List[ChatCompletionMessageParam]): 消息列表，格式为[{"role": "user", "content": "消息内容"}]
            temperature (float): 温度参数，控制输出的随机性 (0-2)
            max_tokens (Optional[int]): 最大token数量
            stream (bool): 是否使用流式输出
            **kwargs: 其他OpenAI API参数

        Returns:
            OpenAI API响应对象
        """
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=stream,
                **kwargs,
            )
            return response
        except Exception as e:
            print(f"调用OpenAI API时发生错误: {e}")
            raise e

    def simple_chat(
        self,
        user_message: str,
        system_message: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> str:
        """
        简单的单轮对话方法

        Args:
            user_message (str): 用户消息
            system_message (Optional[str]): 系统消息（可选）
            temperature (float): 温度参数
            max_tokens (Optional[int]): 最大token数量

        Returns:
            str: AI的回复内容
        """
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
        """
        流式聊天方法

        Args:
            messages (List[ChatCompletionMessageParam]): 消息列表
            temperature (float): 温度参数
            max_tokens (Optional[int]): 最大token数量
            **kwargs: 其他OpenAI API参数

        Yields:
            流式响应的每个chunk
        """
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

    def get_model_info(self) -> Dict[str, str]:
        """
        获取当前配置的模型信息

        Returns:
            Dict[str, str]: 包含模型配置信息的字典
        """
        return {
            "model_name": self.model_name,
            "base_url": self.base_url,
            "api_key_preview": f"{self.api_key[:8]}...{self.api_key[-4:]}"
            if len(self.api_key) > 12
            else "***",
        }
