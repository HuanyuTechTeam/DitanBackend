"""Deterministic local/test transport with per-call fault injection."""

import asyncio
from collections import deque
from dataclasses import dataclass

from app.services.consultation.llm import Prompt, Usage


@dataclass
class Fault:
    fail_after: int | None = None
    delay_before: float = 0
    delay_between: float = 0
    text: str | None = None
    chunk_size: int = 6


class FakeTransport:
    model_name = "consultation-fake"

    def __init__(self, faults=()):
        self.faults = deque(faults)
        self.calls: list[tuple[str, Prompt]] = []

    async def stream(self, prompt: Prompt, purpose: str, timeout: float, usage: Usage):
        self.calls.append((purpose, prompt))
        fault = self.faults.popleft() if self.faults else Fault()
        await asyncio.sleep(fault.delay_before)
        if fault.fail_after == 0:
            raise RuntimeError("synthetic_before_first_token")
        text = (
            fault.text
            if fault.text is not None
            else (
                "【假问题】" + prompt.fixed_question
                if purpose == "question"
                else "【假报告】问诊资料已保存。"
            )
        )
        for number, start in enumerate(range(0, len(text), fault.chunk_size), 1):
            if start:
                await asyncio.sleep(fault.delay_between)
            yield text[start : start + fault.chunk_size]
            if fault.fail_after == number:
                raise RuntimeError("synthetic_mid_stream")
        usage.prompt_tokens = len(prompt.system_text) + len(prompt.user_text)
        usage.completion_tokens = len(text)
