"""Bounded model calls, process-local admission, circuit breaking and audit."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import aclosing, asynccontextmanager
from dataclasses import dataclass
from functools import lru_cache
import logging
import time
from typing import Any, Protocol

from openai.types.chat import ChatCompletionMessageParam

from app.core.config import get_settings
from app.core.database import async_session_maker
from app.models.consultation import ConsultationLLMCall
from app.services.openai_client import OpenAIChatCompletion

logger = logging.getLogger(__name__)


class ModelUnavailable(Exception):
    pass


class ModelQueueTimeout(ModelUnavailable):
    """Local admission timeout, not a failure of the model provider."""


@dataclass(frozen=True)
class Prompt:
    org_id: str
    consultation_id: str
    turn_id: str
    attempt: int
    step_id: str
    prompt_version: str
    system_text: str
    user_text: str
    fixed_question: str = ""

    @property
    def messages(self) -> list[ChatCompletionMessageParam]:
        return [
            {"role": "system", "content": self.system_text},
            {"role": "user", "content": self.user_text},
        ]


@dataclass
class Usage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class ModelTransport(Protocol):
    model_name: str

    def stream(
        self, prompt: Prompt, purpose: str, timeout: float, usage: Usage
    ) -> AsyncGenerator[str, None]: ...


class OpenAITransport:
    def __init__(self, client: OpenAIChatCompletion):
        self.client = client
        self.model_name = client.model_name

    async def stream(self, prompt: Prompt, purpose: str, timeout: float, usage: Usage):
        options: dict[str, Any] = (
            {"max_tokens": 150, "extra_body": {"thinking": {"type": "disabled"}}}
            if purpose == "question"
            else {}
        )
        response = await self.client.async_client.with_options(
            max_retries=0, timeout=timeout
        ).chat.completions.create(
            model=self.model_name,
            messages=prompt.messages,
            stream=True,
            stream_options={"include_usage": True},
            **options,
        )
        try:
            async for chunk in response:
                if chunk.usage is not None:
                    usage.prompt_tokens = chunk.usage.prompt_tokens
                    usage.completion_tokens = chunk.usage.completion_tokens
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        finally:
            await response.close()

    async def close(self):
        await self.client.async_client.close()
        self.client.client.close()


@dataclass
class Limits:
    queue_wait: float = 10
    question_first: float = 10
    question_total: float = 30
    report_total: float = 150
    failure_threshold: int = 3
    circuit_seconds: float = 60


class ConsultationLLM:
    def __init__(
        self,
        transport: ModelTransport,
        session_maker=async_session_maker,
        *,
        concurrency: int = 8,
        limits: Limits | None = None,
    ):
        self.transport = transport
        self.session_maker = session_maker
        self.question_semaphore = asyncio.Semaphore(concurrency)
        self.report_semaphore = asyncio.Semaphore(concurrency)
        self.limits = limits or Limits()
        self.question_failures = 0
        self.open_until = 0.0

    async def stream_question(self, prompt: Prompt) -> AsyncGenerator[str, None]:
        if time.monotonic() < self.open_until:
            raise ModelUnavailable("circuit_open")
        async with self._slot(self.question_semaphore):
            # Other calls may have opened the circuit while this request was queued.
            if time.monotonic() < self.open_until:
                raise ModelUnavailable("circuit_open")
            try:
                async with aclosing(
                    self._attempt(prompt, "question", self.limits.question_total)
                ) as stream:
                    async for text in stream:
                        yield text
            except Exception as exc:
                self.question_failures += 1
                if self.question_failures >= self.limits.failure_threshold:
                    self.open_until = time.monotonic() + self.limits.circuit_seconds
                raise ModelUnavailable(type(exc).__name__) from None
            else:
                self.question_failures = 0
                self.open_until = 0

    async def stream_report(self, prompt: Prompt) -> AsyncGenerator[str, None]:
        async with self._slot(self.report_semaphore):
            deadline = asyncio.get_running_loop().time() + self.limits.report_total
            for retry in range(2):
                emitted = False
                try:
                    remaining = deadline - asyncio.get_running_loop().time()
                    async with aclosing(
                        self._attempt(prompt, "report", remaining)
                    ) as stream:
                        async for text in stream:
                            emitted = True
                            yield text
                    return
                except Exception as exc:
                    if (
                        emitted
                        or retry == 1
                        or asyncio.get_running_loop().time() >= deadline
                    ):
                        raise ModelUnavailable(type(exc).__name__) from None

    @asynccontextmanager
    async def _slot(self, semaphore: asyncio.Semaphore):
        try:
            async with asyncio.timeout(self.limits.queue_wait):
                await semaphore.acquire()
        except TimeoutError:
            raise ModelQueueTimeout("queue_timeout") from None
        try:
            yield
        finally:
            semaphore.release()

    async def _attempt(self, prompt: Prompt, purpose: str, total: float):
        started = time.monotonic()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + total
        first_deadline = (
            min(deadline, loop.time() + self.limits.question_first)
            if purpose == "question"
            else deadline
        )
        chunks: list[str] = []
        first_token_ms = None
        usage = Usage()
        status, error = "failed", None
        try:
            async with asyncio.timeout_at(first_deadline) as timer:
                stream = self.transport.stream(prompt, purpose, total, usage)
                try:
                    async for text in stream:
                        if not text:
                            continue
                        if first_token_ms is None:
                            first_token_ms = int((time.monotonic() - started) * 1000)
                            timer.reschedule(deadline)
                        chunks.append(text)
                        yield text
                finally:
                    await stream.aclose()
                if not "".join(chunks).strip():
                    raise ModelUnavailable("empty_output")
                status = "succeeded"
        except BaseException as exc:
            status = (
                "cancelled" if isinstance(exc, asyncio.CancelledError) else "failed"
            )
            error = type(exc).__name__
            raise
        finally:
            await self._audit(
                prompt,
                purpose,
                {
                    "response": "".join(chunks),
                    "status": status,
                    "error": error,
                    "latency_ms": int((time.monotonic() - started) * 1000),
                    "first_token_ms": first_token_ms,
                    "prompt_tokens": usage.prompt_tokens,
                    "completion_tokens": usage.completion_tokens,
                },
            )

    async def _audit(self, prompt: Prompt, purpose: str, result: dict):
        try:
            async with asyncio.timeout(2):
                async with self.session_maker() as session:
                    session.add(
                        ConsultationLLMCall(
                            org_id=prompt.org_id,
                            consultation_id=prompt.consultation_id,
                            turn_id=prompt.turn_id,
                            attempt=prompt.attempt,
                            purpose=purpose,
                            step_id=prompt.step_id,
                            model=self.transport.model_name,
                            prompt_version=prompt.prompt_version,
                            request={"messages": prompt.messages},
                            **result,
                        )
                    )
                    await session.commit()
        except Exception:
            # Never send prompt text, responses or provider exception strings to normal logs.
            logger.warning(
                "Consultation model audit could not be saved",
                extra={
                    "extra_data": {
                        "consultation_id": prompt.consultation_id,
                        "turn_id": prompt.turn_id,
                        "attempt": prompt.attempt,
                    }
                },
            )


@lru_cache(maxsize=1)
def get_llm() -> ConsultationLLM:
    settings = get_settings()
    transport: ModelTransport
    if settings.CONSULTATION_LLM_PROVIDER == "fake":
        from app.services.consultation.llm_fake import FakeTransport

        transport = FakeTransport()
    else:
        transport = OpenAITransport(
            OpenAIChatCompletion(
                settings.AI_API_KEY,
                settings.AI_BASE_URL,
                settings.AI_MODEL_NAME,
            )
        )
    return ConsultationLLM(transport, concurrency=settings.CONSULTATION_LLM_CONCURRENCY)


async def close_llm():
    if get_llm.cache_info().currsize:
        transport = get_llm().transport
        if hasattr(transport, "close"):
            await transport.close()
        get_llm.cache_clear()
