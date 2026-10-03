"""Pure rendering of the original v1 prompts and structured patient inputs."""

from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
import re

BEIJING = timezone(timedelta(hours=8))
PLACEHOLDER = re.compile(r"\{\{(.*?)\}\}", re.DOTALL)
DECLARED = {"USER_INPUT", "output", "input", "messageList"}


@lru_cache(maxsize=16)
def load_prompt(prompt_id: str) -> str:
    if prompt_id not in {f"L{i:02}" for i in range(3, 19)}:
        raise ValueError("Unknown prompt")
    paths = list((Path(__file__).parent / "prompts" / "v1").glob(f"{prompt_id}_*.txt"))
    if len(paths) != 1:
        raise ValueError("Expected exactly one versioned prompt")
    return paths[0].read_text(encoding="utf-8")


def fixed_question(prompt_id: str) -> str:
    tail = load_prompt(prompt_id).split("以下为你要提问的问题。", 1)[1]
    return next(line.strip() for line in tail.splitlines() if line.strip())


def split_prompt(prompt_id: str) -> tuple[str, str]:
    raw = load_prompt(prompt_id)
    if prompt_id == "L14":
        start = raw.index("以下为患者和医生的所有对话记录：")
        end = raw.index("{{USER_INPUT}}", start) + len("{{USER_INPUT}}")
        system = raw[:start].rstrip() + "\n\n" + raw[end:].lstrip("\n")
        user = raw[start:end]
    else:
        start = raw.index("患者信息{{USER_INPUT}}")
        system, user = raw[:start].rstrip(), raw[start:]
    if PLACEHOLDER.search(system):
        raise ValueError("System prompts must be independent of patient input")
    unknown = set(PLACEHOLDER.findall(user)) - DECLARED
    if unknown:
        raise ValueError(f"Undeclared placeholders: {sorted(unknown)}")
    return system, user


def render_prompt(
    prompt_id: str,
    *,
    user_input: str,
    output: str = "",
    input_text: str = "",
    message_list: str = "",
) -> tuple[str, str]:
    system, user = split_prompt(prompt_id)
    values = {
        "USER_INPUT": user_input,
        "output": output,
        "input": input_text,
        "messageList": message_list,
    }
    # One substitution pass: replacement text is never interpreted as a template.
    return system, PLACEHOLDER.sub(lambda match: values[match.group(1)], user)


def age_on(birthday: str | None, basis: date) -> int | None:
    if not birthday:
        return None
    patterns = (
        (r"\d{4}-\d{2}-\d{2}", "%Y-%m-%d"),
        (r"\d{4}/\d{2}/\d{2}", "%Y/%m/%d"),
        (r"\d{8}", "%Y%m%d"),
    )
    for pattern, fmt in patterns:
        if re.fullmatch(pattern, birthday):
            try:
                born = datetime.strptime(birthday, fmt).date()
            except ValueError:
                return None
            if born > basis:
                return None
            return (
                basis.year
                - born.year
                - ((basis.month, basis.day) < (born.month, born.day))
            )
    return None


def render_patient(inputs: dict, basis: date) -> str:
    patient = inputs.get("patient") or {}
    age = age_on(patient.get("birthday"), basis)
    values = (
        ("性别", patient.get("sex"), ""),
        ("年龄", age, ""),
        ("生日", patient.get("birthday"), ""),
        ("身高", patient.get("height_cm"), "cm"),
        ("体重", patient.get("weight_kg"), "kg"),
        ("目标体重", patient.get("target_weight_kg"), "kg"),
    )
    lines = ["[基本信息]"]
    for label, value, unit in values:
        if value is not None and value != "":
            value = format(value, "g") if isinstance(value, (int, float)) else value
            lines.append(f"- {label}: {value}{unit}")
    sections = ["\n".join(lines)]
    assessments = inputs.get("assessments") or {}
    for key, title in (
        ("face", "面部情况分析"),
        ("tongue", "舌象（正面）分析"),
        ("tongue_down", "舌象（舌下）分析"),
        ("pulse", "脉象情况分析"),
    ):
        assessment = assessments.get(key) or {}
        value = assessment.get("text") or ""
        if value.strip():
            sections.append(f"[{title}]\n{value.strip()}")
    return "\n\n".join(sections)


def format_messages(messages, *, archive: bool = False) -> str:
    labels = {
        "assistant": "AI" if archive else "医生",
        "user": "User" if archive else "患者",
    }
    separator = ": " if archive else "："
    ordered = sorted(messages, key=lambda message: message["seq"])
    return "\n".join(f"{labels[m['role']]}{separator}{m['content']}" for m in ordered)
