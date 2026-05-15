import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, cast
from typing import Tuple, Optional

import random
import openai
import pandas as pd
from dotenv import load_dotenv
from openai.types.chat import (
    ChatCompletionMessageParam,
    ChatCompletionUserMessageParam,
    ChatCompletionSystemMessageParam,
)

load_dotenv()

DIAGNOSIS_PROMPT_1 = """"
你是一名经验丰富的中医专家，擅长根据给定的患者病史和四诊信息给出对应的证型。

# 诊断依据指导
依托于中医学八纲辨证，是：阴、阳、表、里、寒、热、虚、实
在临床上，八纲证候很少单独出现，通常是相互交织、组合的，因此需要统筹考虑

# 患者病史
{medical_record}

# 患者四诊信息
{tcm_sizhen_record}

# 输出格式要求（请务必按照下面的要求输出，不同的标签对应不同的内容）
<think>
你的诊断思考过程。
</think>
<answer>
你的判断证型。
</answer> 

注意，<answer>中的内容需要严格遵守以下规则：
1-脾虚湿阻 2-胃热脾虚 3-肝郁气滞 4-脾肾阳虚 如果为兼证请回答主次，而且**仅仅只需要输出数字，主次症状用逗号分隔**。
比如说，如果要输出“脾虚湿阻”，那么你只需要输出“1”，不要输出“脾虚湿阻”。如果要输出“脾虚湿阻为主，兼有胃热脾虚”，那么你只需要输出“1,2”，不要输出“脾虚湿阻，胃热脾虚”。

请你根据患者病历信息，给出对应的证型。
"""

DIAGNOSIS_PROMPT_2 = """"
你是一名经验丰富的中医专家，擅长根据给定的患者病史和四诊信息给出对应的证型。

# 诊断依据指导
依托于中医学八纲辨证，是：阴、阳、表、里、寒、热、虚、实
在临床上，八纲证候很少单独出现，通常是相互交织、组合的，因此需要统筹考虑

# 患者病史
{medical_record}

# 患者四诊信息
{tcm_sizhen_record}

# 输出格式要求（请务必按照下面的要求输出，不同的标签对应不同的内容）
<think>
你的诊断思考过程。
</think>
<answer>
你的判断证型。
</answer> 

注意，<answer>中的内容需要严格遵守以下规则：
1-脾虚湿阻 2-胃热脾虚 3-肝郁气滞 4-脾肾阳虚 如果为兼证请回答主次，而且**仅仅只需要输出数字，主次症状用逗号分隔**。
比如说，如果要输出“脾虚湿阻”，那么你只需要输出“1”，不要输出“脾虚湿阻”。如果要输出“脾虚湿阻为主，兼有胃热脾虚”，那么你只需要输出“1,2”，不要输出“脾虚湿阻，胃热脾虚”。

请你根据患者病历信息，给出对应的证型。
"""

DIAGNOSIS_PROMPT_3 = """
你是一名经验丰富的中医专家，擅长根据给定的患者病历信息给出对应的证型。

# 患者病史
{medical_record}

# 患者四诊信息
{tcm_sizhen_record}

# 输出格式要求（请务必按照下面的要求输出，不同的标签对应不同的内容）
<think>
你的诊断思考过程。
</think>
<answer>
你的判断证型。
</answer> 

注意，<answer>中的内容需要严格遵守以下规则：
1-脾虚湿阻 2-胃热脾虚 3-肝郁气滞 4-脾肾阳虚 如果为兼证请回答主次，而且**仅仅只需要输出数字，主次症状用逗号分隔**。
比如说，如果要输出“脾虚湿阻”，那么你只需要输出“1”，不要输出“脾虚湿阻”。如果要输出“脾虚湿阻为主，兼有胃热脾虚”，那么你只需要输出“1,2”，不要输出“脾虚湿阻，胃热脾虚”。

请你根据患者病历信息，给出对应的证型。
"""


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


ANSWER_RE = re.compile(r"<answer>\s*(.*?)\s*</answer>", re.DOTALL | re.IGNORECASE)


def extract_answer(text: str) -> str:
    if not text:
        return ""
    m = ANSWER_RE.search(text)
    return m.group(1).strip() if m else ""


PROMPTS = {
    "p1": DIAGNOSIS_PROMPT_1,
    "p2": DIAGNOSIS_PROMPT_2,
    "p3": DIAGNOSIS_PROMPT_3,
}


def build_prompt(
    template: str,
    basic_info: str,
    chief_complaint: str,
    present_illness: str,
    four_diagnosis: str,
) -> str:
    medical_record = (
        f"基本信息（脱敏）: {basic_info}\n"
        f"主诉: {chief_complaint}\n"
        f"现病史: {present_illness}\n"
    )
    tcm_sizhen_record = f"{four_diagnosis}"
    return template.format(
        medical_record=medical_record, tcm_sizhen_record=tcm_sizhen_record
    )


def tcm_diagnosis(
    llm: "OpenAIChatCompletion",
    prompt_key: str,
    basic_info: str,
    chief_complaint: str,
    present_illness: str,
    four_diagnosis: str,
    temperature: float = 0.2,
    max_tokens: int = 8096,
    max_retries: int = 3,
) -> Tuple[str, str, Dict[str, Any]]:
    """
    返回: (answer, raw_output, meta)
    meta 包含: attempts, total_seconds, last_finish_reason, last_usage, error
    """
    template = PROMPTS[prompt_key]
    prompt = build_prompt(
        template, basic_info, chief_complaint, present_illness, four_diagnosis
    )

    meta: Dict[str, Any] = {
        "attempts": 0,
        "total_seconds": 0.0,
        "last_finish_reason": None,
        "last_usage": None,
        "error": None,
    }

    last_raw = ""
    start_total = time.perf_counter()

    for attempt in range(max_retries + 1):
        meta["attempts"] = attempt + 1
        t0 = time.perf_counter()

        try:
            response = llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
            )

            dt = time.perf_counter() - t0
            content = response.choices[0].message.content or ""
            finish_reason = getattr(response.choices[0], "finish_reason", None)
            usage = getattr(response, "usage", None)

            meta["last_finish_reason"] = finish_reason
            if usage is None:
                meta["last_usage"] = None
            elif hasattr(usage, "model_dump"):
                meta["last_usage"] = cast(Any, usage).model_dump()
            else:
                meta["last_usage"] = dict(usage)

            last_raw = content
            answer = extract_answer(content)

            has_open_answer = "<answer" in content.lower()
            has_close_answer = "</answer>" in content.lower()
            answer_tag_incomplete = has_open_answer and (not has_close_answer)

            # 成功条件：必须抽到 answer，并且不是 length 截断，并且标签不是不完整
            if answer and (finish_reason != "length") and (not answer_tag_incomplete):
                meta["total_seconds"] = time.perf_counter() - start_total
                meta["last_attempt_seconds"] = dt
                meta["error"] = None
                return answer, content, meta

            meta["last_attempt_seconds"] = dt
            meta["error"] = (
                "incomplete_output("
                f"answer_empty={not bool(answer)}, "
                f"answer_tag_incomplete={answer_tag_incomplete}, "
                f"finish_reason={finish_reason}"
                ")"
            )

        except Exception as e:
            dt = time.perf_counter() - t0
            meta["last_attempt_seconds"] = dt
            meta["error"] = f"{type(e).__name__}: {e}"

        if attempt < max_retries:
            backoff = (0.8 * (2**attempt)) + random.uniform(0, 0.3)
            time.sleep(backoff)

    meta["total_seconds"] = time.perf_counter() - start_total
    return "", last_raw, meta


def main():
    input_file = "./data.xlsx"
    output_file = "./output_comparison.xlsx"

    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL")
    model_name = os.getenv("OPENAI_MODEL")

    if not api_key:
        raise RuntimeError("未检测到 OPENAI_API_KEY，请先设置环境变量。")

    print(base_url)
    print(model_name)

    if not base_url or not model_name:
        raise RuntimeError("base_url 和 model_name 没有配置好")

    llm = OpenAIChatCompletion(
        api_key=api_key, base_url=base_url, model_name=model_name
    )

    df = pd.read_excel(input_file)

    # the result file
    for k in PROMPTS.keys():
        df[f"中医辩证_{k}"] = ""
        df[f"大模型输出_{k}"] = ""
        df[f"尝试次数_{k}"] = 0
        df[f"总耗时秒_{k}"] = 0.0
        df[f"最后一次耗时秒_{k}"] = 0.0
        df[f"finish_reason_{k}"] = ""
        df[f"usage_{k}"] = ""
        df[f"error_{k}"] = ""

    max_workers = 16
    futures = {}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for idx, row in df.iterrows():
            basic_info = str(row.get("基本信息（脱敏）", "") or "")
            chief_complaint = str(row.get("主诉", "") or "")
            present_illness = str(row.get("现病史", "") or "")
            four_diagnosis = str(row.get("四诊信息", "") or "")

            for k in PROMPTS.keys():
                fut = executor.submit(
                    tcm_diagnosis,
                    llm,
                    k,  # 新增：传 prompt key
                    basic_info,
                    chief_complaint,
                    present_illness,
                    four_diagnosis,
                )
                futures[fut] = (idx, k)

        for fut in as_completed(futures):
            idx, k = futures[fut]
            try:
                answer, raw, meta = fut.result()
            except Exception as e:
                answer, raw, meta = (
                    "",
                    "",
                    {
                        "attempts": 0,
                        "total_seconds": 0.0,
                        "last_attempt_seconds": 0.0,
                        "last_finish_reason": "",
                        "last_usage": None,
                        "error": f"{type(e).__name__}: {e}",
                    },
                )

            df.at[idx, f"中医辩证_{k}"] = answer
            df.at[idx, f"大模型输出_{k}"] = raw
            df.at[idx, f"尝试次数_{k}"] = meta.get("attempts", 0)
            df.at[idx, f"总耗时秒_{k}"] = float(meta.get("total_seconds", 0.0) or 0.0)
            df.at[idx, f"最后一次耗时秒_{k}"] = float(
                meta.get("last_attempt_seconds", 0.0) or 0.0
            )
            df.at[idx, f"finish_reason_{k}"] = str(
                meta.get("last_finish_reason", "") or ""
            )
            df.at[idx, f"usage_{k}"] = str(meta.get("last_usage", "") or "")
            df.at[idx, f"error_{k}"] = str(meta.get("error", "") or "")

    df.to_excel(output_file, index=False)
    print("处理完成，结果已写入：", output_file)


if __name__ == "__main__":
    main()
