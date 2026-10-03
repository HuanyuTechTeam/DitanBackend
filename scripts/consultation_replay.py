"""Replay deidentified Coze answers through the real v1 service in disposable SQLite.

Examples:
  uv run python scripts/consultation_replay.py --samples .consultation-data/t9/samples.jsonl --output-dir .consultation-data/t9/replay
  Add --provider fake for offline verification. Real requests are never part of pytest.
"""

import argparse
import asyncio
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
import hashlib
import html
import json
import logging
import os
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class DialoguePair:
    question: str
    answer: str
    report_control: bool = False


def parse_conversation(log: str) -> list[DialoguePair]:
    starts = list(re.finditer(r"(?m)^(User|AI|Status):[ \t]*", log))
    previous_question = None
    pairs = []
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(log)
        content = log[match.end() : end].strip()
        role = match[1]
        if role == "AI":
            previous_question = content
        elif role == "User" and content and previous_question:
            if content.startswith("[基本信息]") or (
                content.startswith("{") and '"birthday"' in content
            ):
                continue
            control = classify_question(
                previous_question
            ) == "report_gate" and content in {"获取报告", "生成报告", "查看报告"}
            pairs.append(DialoguePair(previous_question, content, control))
    return pairs


STEP_CUES = (
    ("family_health", r"父母|家族|家里人|家人|直系亲属|父亲|母亲"),
    ("menstruation_detail", r"血块|痛经|经前|乳房.*(?:痛|胀)|小腹.*(?:痛|胀)"),
    ("leukorrhea", r"白带|外阴|分泌物|瘙痒"),
    ("children", r"孩子|生育|生过|宝宝"),
    ("menstruation", r"月经|经期|经量|周期"),
    ("core_history", r"高血压|糖尿病|脂肪肝|甲状腺|基础疾病|慢性病|长期.*(?:药|疾病)"),
    ("work_stress", r"工作|上班|压力|久坐|坐着"),
    ("sleep_quality", r"睡眠|失眠|多梦|打鼾|憋气|睡觉|入睡|睡得"),
    ("nocturia", r"起夜|夜尿|腰酸|怕冷|手脚.*(?:凉|冷)"),
    ("energy_mood", r"精力|情绪|疲劳|疲乏|烦躁|容易累|犯懒|精神"),
    ("diet_extra", r"零食|夜宵|饮料|喝酒|饮酒"),
    ("diet_core", r"三餐|饭量|饮食|油炸|甜食|面食"),
    ("digestion", r"腹胀|肚子胀|大便|排便|偏稀|偏干|便秘"),
    ("exercise_tolerance", r"气喘|喘|上气不接下气|活动.*呼吸"),
    ("exercise_habit", r"运动|每周|锻炼|健身"),
)


def classify_question(question: str) -> str | None:
    if re.search(r"获取报告|点击.*报告|生成报告", question):
        return "report_gate"
    # The closing question takes precedence over commentary about the preceding answer.
    fragments = [
        part.strip() for part in re.split(r"[。！？!?\n]", question) if part.strip()
    ]
    for fragment in reversed(fragments):
        for step, pattern in STEP_CUES:
            if re.search(pattern, fragment):
                return step
    return None


def normalize_sample(sample: dict) -> dict:
    from app.schemas.consultation import ConsultationInputs
    from scripts.consultation_export import Redactor

    if not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", str(sample.get("sample_id", ""))
    ):
        raise ValueError("sample_id must be an anonymous identifier")
    date.fromisoformat(sample["consultation_date"])
    if not isinstance(sample.get("coze_report"), str) or not isinstance(
        sample.get("coze_conversation_log"), str
    ):
        raise ValueError("Sample needs a Coze report and transcript")
    Redactor([]).verify(sample)
    inputs = sample["inputs"]
    assessments = {
        key: {"text": value, "source": "client"} if isinstance(value, str) else value
        for key, value in (inputs.get("assessments") or {}).items()
    }
    try:
        validated = ConsultationInputs.model_validate(
            {**inputs, "assessments": assessments}
        )
    except Exception:
        raise ValueError("Invalid structured replay inputs") from None
    pairs = parse_conversation(sample["coze_conversation_log"])
    if not pairs:
        raise ValueError("No paired patient answers in transcript")
    if any(len(pair.answer) > 2000 for pair in pairs if not pair.report_control):
        raise ValueError("An answer exceeds the v1 2000-character limit")
    return {**sample, "inputs": validated.model_dump(mode="json")}


def load_samples(path: Path) -> list[dict]:
    samples = []
    seen = set()
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line.strip():
            continue
        try:
            sample = normalize_sample(json.loads(line))
        except Exception:
            raise ValueError(
                f"Invalid or non-deidentified sample on JSONL line {line_number}"
            ) from None
        if sample["sample_id"] in seen:
            raise ValueError("Duplicate anonymous sample_id")
        seen.add(sample["sample_id"])
        samples.append(sample)
    if not samples:
        raise ValueError("No samples")
    return samples


def report_checks(report: str) -> list[str]:
    flags = []
    if re.search(r"(?m)^\s*(?:#{1,6}\s|[-*]\s)|\*\*|```", report):
        flags.append("报告疑似含 Markdown，需业务复核")
    if re.search(
        r"治疗方案|温养建议|处方[:：]|建议[^。\n]{0,30}(?:服用|针灸|艾灸|温养|用药|治疗)",
        report,
    ):
        flags.append("报告疑似含治疗或温养建议，需业务复核")
    return flags


def compare_question(
    index: int, pair: DialoguePair, question: dict
) -> tuple[dict, list[str]]:
    coze_step = classify_question(pair.question)
    new_step = classify_question(question["content"])
    notes = []
    if coze_step is None:
        notes.append("Coze 主题无法自动识别，需复核")
    elif coze_step != question["step_id"]:
        notes.append(f"主题/顺序不同：{coze_step} → {question['step_id']}")
    if new_step is None:
        notes.append("新问题正文主题无法自动识别，需复核")
    elif new_step != question["step_id"]:
        notes.append(f"新模型疑似偏题：步骤 {question['step_id']}，正文主题 {new_step}")
    flags = [f"第 {index} 轮：{note}" for note in notes]
    if question.get("meta", {}).get("fallback"):
        notes.append("新后端使用固定问题降级")
    return {
        "index": index,
        "coze_step": coze_step or "未知",
        "step": question["step_id"],
        "new_step": new_step or "未知",
        "coze_question": pair.question,
        "new_question": question["content"],
        "answer": pair.answer,
        "note": "；".join(notes) if notes else "主题匹配（自动识别）",
    }, flags


def cell(value) -> str:
    return (
        html.escape(str(value or ""), quote=False)
        .replace("|", "&#124;")
        .replace("\n", "<br>")
    )


def render_report(sample: dict, result: dict) -> str:
    lines = [
        f"# 问诊回放对照：{sample['sample_id']}",
        "",
        f"模型提供方：{result['provider']}；模型：{result['model']}；执行状态：{result['status']}。",
        "样本中的姓名、电话、链接等已脱敏；日期已平移且周岁保持不变。输入仅供迁移对照，不含原始记录标识。",
        "",
        "## 自动检查",
        "",
    ]
    flags = result["flags"]
    lines.extend(
        ["- " + flag for flag in flags]
        if flags
        else ["- 未发现可自动识别的步骤/分支差异；问法与报告仍需业务审阅。"]
    )
    lines += [
        "",
        "问题主题由关键词推测，未知主题不自动判定为一致；回放保持原回答顺序，不重排、不改写或补造回答。",
        "若新问题偏题，原回答仍来自 Coze 问题语境，后续报告可能受问答错位影响，模型质量以业务审阅为准。",
        "服务端固定问题降级会单独标记；报告触发按钮转为显式 report 命令。",
        "",
        "## 逐轮问题与原回答",
        "",
        "| 轮次 | Coze 主题推测 | v1 步骤 | 新文本主题推测 | Coze 问题 | 新后端问题 | 原患者回答 | 检查 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in result["rows"]:
        lines.append(
            "| "
            + " | ".join(
                cell(row[key])
                for key in (
                    "index",
                    "coze_step",
                    "step",
                    "new_step",
                    "coze_question",
                    "new_question",
                    "answer",
                    "note",
                )
            )
            + " |"
        )
    lines += [
        "",
        "## 报告并排对照",
        "",
        "| Coze 已保存报告 | 新后端报告 |",
        "| --- | --- |",
        f"| {cell(sample['coze_report'])} | {cell(result.get('report') or '未生成：见执行状态与检查说明')} |",
        "",
        "## 回放统计",
        "",
        f"- 已保存版本：{result.get('version', 0)}",
        f"- 模型调用次数：{result['model_calls']}；问题降级次数：{result['fallbacks']}",
        f"- token：输入 {result['prompt_tokens']}，输出 {result['completion_tokens']}（以供应商返回的 usage 为准）",
        "- 临时 SQLite 中保存轮次与调用审计，导出统计后删除；没有写入生产数据库。",
        "",
    ]
    return "\n".join(lines)


async def replay_sample(
    sample: dict,
    output_dir: Path,
    *,
    provider: str = "openai",
    transport=None,
    progress=None,
) -> dict:
    from sqlalchemy import select, update
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.core.config import get_settings
    from app.core.database import Base
    from app.core.organization import OrganizationContext
    from app.core.upload_auth import UploadPrincipal
    from app.models.consultation import Consultation, ConsultationLLMCall
    from app.services.consultation.llm import ConsultationLLM, OpenAITransport
    from app.services.consultation.llm_fake import FakeTransport
    from app.services.consultation.runner import TurnRunner
    from app.services.consultation.service import ConsultationService
    from app.services.openai_client import OpenAIChatCompletion

    sample = normalize_sample(sample)
    output_dir.mkdir(parents=True, exist_ok=True)
    pairs = parse_conversation(sample["coze_conversation_log"])
    owned_transport = transport is None
    if transport is None:
        if provider == "fake":
            transport = FakeTransport()
        else:
            settings = get_settings()
            transport = OpenAITransport(
                OpenAIChatCompletion(
                    settings.AI_API_KEY, settings.AI_BASE_URL, settings.AI_MODEL_NAME
                )
            )
    result: dict[str, Any] = {
        "sample_id": sample["sample_id"],
        "provider": provider,
        "model": transport.model_name,
        "status": "incomplete",
        "rows": [],
        "flags": [],
        "report": None,
        "version": 0,
        "fallbacks": 0,
        "model_calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
    }
    if provider == "fake":
        result["flags"].append(
            "本报告由假模型生成，仅验证回放工具，不能作为问法或报告质量对照"
        )
    from scripts.consultation_export import age_on

    derived_age = age_on(
        sample["inputs"]["patient"].get("birthday"),
        date.fromisoformat(sample["consultation_date"]),
    )
    mentioned_ages = {
        int(value)
        for value in re.findall(
            r"(?:显示|年龄(?:为|是)?)[^。\n]{0,8}?(\d{1,3})岁",
            sample["coze_conversation_log"],
        )
    }
    if derived_age is not None and any(
        value != derived_age for value in mentioned_ages
    ):
        result["flags"].append(
            f"Coze 文本提及年龄 {sorted(mentioned_ages)}，按样本就诊日期计算为 {derived_age}；原开场时间/年龄计算可能不同，需复核"
        )
    with TemporaryDirectory(prefix=".replay-", dir=output_dir) as directory:
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{Path(directory) / 'replay.db'}", hide_parameters=True
        )
        runner = TurnRunner()
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        identity = UploadPrincipal(
            OrganizationContext("replay"), "replay", "replay", "replay", None
        )
        ctx = SimpleNamespace(
            organization=identity.organization, current_consultation=identity
        )
        service = ConsultationService(
            sessions, llm=ConsultationLLM(transport, sessions), task_runner=runner
        )
        snapshot: dict | None = None

        async def notify(stage, **extra):
            if progress:
                progress({"sample_id": sample["sample_id"], "stage": stage, **extra})

        async def submit(kind, text=None):
            assert snapshot is not None
            body = {
                "turn_id": str(uuid4()),
                "kind": kind,
                "base_version": snapshot["version"],
                "text": text,
            }
            handle = await service.submit_turn(ctx, snapshot["consultation_id"], body)
            complete = None
            async for event in service.events(handle):
                if event.name == "completed":
                    complete = event.data
                elif event.name == "error":
                    raise RuntimeError(event.data.get("code", "TURN_FAILED"))
            if complete is None:
                raise RuntimeError("TURN_NOT_COMPLETED")
            return await service.get_snapshot(ctx, snapshot["consultation_id"])

        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            snapshot = await service.create_or_get(
                ctx,
                {
                    "encounter_uuid": str(uuid4()),
                    "pre_diagnosis_uuid": str(uuid4()),
                    "inputs": sample["inputs"],
                },
            )
            basis = datetime.combine(
                date.fromisoformat(sample["consultation_date"]),
                time(12),
                tzinfo=timezone.utc,
            )
            async with sessions() as session, session.begin():
                await session.execute(
                    update(Consultation)
                    .where(
                        Consultation.org_id == "replay",
                        Consultation.id == snapshot["consultation_id"],
                    )
                    .values(created_at=basis)
                )
            await notify("start")
            snapshot = await submit("start")
            answer_index = 0
            for pair in pairs:
                if pair.report_control:
                    if snapshot["status"] != "ready_for_report":
                        result["flags"].append(
                            "Coze 已触发报告，但新后端尚未问完：原记录可能缺少回答或分支不同"
                        )
                    continue
                answer_index += 1
                question = next(
                    message
                    for message in reversed(snapshot["messages"])
                    if message["role"] == "assistant"
                )
                row, flags = compare_question(answer_index, pair, question)
                result["flags"].extend(flags)
                if question.get("meta", {}).get("fallback"):
                    result["fallbacks"] += 1
                result["rows"].append(row)
                await notify("answer", turn=answer_index, step=question["step_id"])
                snapshot = await submit("answer", pair.answer)
            if snapshot["status"] == "ready_for_report":
                await notify("report")
                snapshot = await submit("report")
                archive = await service.archive(ctx, snapshot["consultation_id"])
                result["report"] = archive["diagnosis_result"]
                result["status"] = "completed"
                result["flags"].extend(report_checks(result["report"]))
            else:
                result["flags"].append(
                    "日志回答不足以完成当前 v1 流程；没有编造后续回答或强行生成报告"
                )
            result["version"] = snapshot["version"]
        except Exception as exc:
            # Errors may contain clinical values; store only the exception type.
            result["status"] = "failed"
            result["flags"].append(
                f"回放失败：{type(exc).__name__}；未输出异常中的请求内容"
            )
        finally:
            await runner.shutdown(timeout=1)
            try:
                async with sessions() as session:
                    calls = (
                        await session.scalars(
                            select(ConsultationLLMCall).where(
                                ConsultationLLMCall.org_id == "replay"
                            )
                        )
                    ).all()
                    result["model_calls"] = len(calls)
                    result["prompt_tokens"] = sum(
                        call.prompt_tokens or 0 for call in calls
                    )
                    result["completion_tokens"] = sum(
                        call.completion_tokens or 0 for call in calls
                    )
            finally:
                await engine.dispose()
                if owned_transport and hasattr(transport, "close"):
                    await transport.close()
    report_path = output_dir / f"{sample['sample_id']}.md"
    report_path.write_text(render_report(sample, result), encoding="utf-8")
    result["report_path"] = str(report_path)
    await notify(
        "finished",
        status=result["status"],
        flags=len(result["flags"]),
        model_calls=result["model_calls"],
    )
    return result


def configure_cli(provider: str, config_path: Path):
    from dotenv import dotenv_values

    config = dotenv_values(config_path)
    key = os.environ.get("AI_API_KEY") or config.get("AI_API_KEY")
    base = (
        os.environ.get("AI_BASE_URL")
        or config.get("AI_BASE_URL")
        or config.get("AI_OPENAI_BASE_URL")
    )
    model = (
        os.environ.get("AI_MODEL_NAME")
        or config.get("AI_MODEL_NAME")
        or "deepseek-chat"
    )
    if provider == "openai" and (not key or not base):
        raise ValueError(
            "Provide AI_API_KEY and AI_BASE_URL (or AI_OPENAI_BASE_URL) locally"
        )
    os.environ.update(
        {
            "DATABASE_HOST": "127.0.0.1",
            "DATABASE_PORT": "9",
            "DATABASE_USER": "unused_replay",
            "DATABASE_PASSWORD": "unused_replay",
            "DATABASE_NAME": "unused_replay",
            "AI_API_KEY": key or "fake",
            "AI_BASE_URL": base or "https://invalid.test",
            "AI_MODEL_NAME": model,
            "CONSULTATION_LLM_PROVIDER": provider,
        }
    )
    logging.basicConfig(level=logging.WARNING)


def main():
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--provider", choices=["openai", "fake"], default="openai")
    parser.add_argument("--config", type=Path, default=root / ".env")
    parser.add_argument("--limit", type=int, default=1)
    args = parser.parse_args()
    if args.limit < 1 or args.limit > 20:
        parser.error("Use 1-20 samples per batch")
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        parser.error("Output directory must be empty or new")
    try:
        configure_cli(args.provider, args.config)
        samples = load_samples(args.samples)[: args.limit]
    except (ValueError, OSError) as exc:
        parser.error(str(exc))

    def progress(event):
        print(json.dumps(event, ensure_ascii=False), flush=True)

    async def run():
        summaries = []
        for sample in samples:
            result = await replay_sample(
                sample, args.output_dir, provider=args.provider, progress=progress
            )
            summaries.append(
                {
                    key: value
                    for key, value in result.items()
                    if key not in {"rows", "report"}
                }
            )
        summary = {
            "provider": args.provider,
            "source_sha256": hashlib.sha256(args.samples.read_bytes()).hexdigest(),
            "samples": summaries,
        }
        (args.output_dir / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return 0 if all(item["status"] == "completed" for item in summaries) else 1

    raise SystemExit(asyncio.run(run()))


if __name__ == "__main__":
    main()
