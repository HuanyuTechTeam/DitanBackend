from collections import Counter
from datetime import date, datetime, timezone
import json
from pathlib import Path
import re

import pytest

from app.services.consultation import rendering
from app.services.consultation.workflows.v1 import (
    Ask,
    ReportGate,
    WorkflowContext,
    STEPS,
    first_step,
    next_step,
)

MAIN = [
    "core_history",
    "family_health",
    "work_stress",
    "sleep_quality",
    "nocturia",
    "energy_mood",
    "diet_core",
    "diet_extra",
    "digestion",
    "exercise_habit",
    "exercise_tolerance",
]


@pytest.mark.parametrize("sex", ["男", "女", None])
@pytest.mark.parametrize("age", [9, 10, 11, 19, 20, 21, None])
def test_branch_matrix(sex, age):
    ctx = WorkflowContext(sex, age)
    step = first_step(ctx)
    sequence = []
    while isinstance(step, Ask):
        sequence.append(step.id)
        step = next_step(step.id, ctx)
    assert isinstance(step, ReportGate)
    extra = []
    if sex == "女" and (age is None or age >= 10):
        if age is not None and age >= 20:
            extra.append("children")
        extra += ["menstruation", "menstruation_detail", "leukorrhea"]
    assert sequence == MAIN + extra


@pytest.mark.parametrize("prompt_id", [f"L{i:02}" for i in range(3, 19)])
def test_original_prompts_and_message_split(prompt_id):
    source = (Path(__file__).parent / "fixtures/coze_prompts_v1.txt").read_text(
        encoding="utf-8"
    )
    blocks = dict(
        re.findall(r"^### (L\d{2})[^\n]*\n.*?^```text\n(.*?)\n```", source, re.M | re.S)
    )
    raw = blocks[prompt_id].replace("{{USER\\_INPUT}}", "{{USER_INPUT}}") + "\n"
    assert rendering.load_prompt(prompt_id) == raw
    system, user = rendering.split_prompt(prompt_id)
    assert "{{" not in system

    def nonempty(text):
        return [line for line in text.splitlines() if line.strip()]

    assert Counter(nonempty(system) + nonempty(user)) == Counter(nonempty(raw))
    # Both portions retain the original relative order (L14 has two system segments).
    for portion in (system, user):
        remaining = iter(nonempty(raw))
        assert all(
            any(line == original for original in remaining)
            for line in nonempty(portion)
        )
    a = rendering.render_prompt(
        prompt_id,
        user_input="甲",
        input_text="一",
        output="旧问",
        message_list="对话甲",
    )
    b = rendering.render_prompt(
        prompt_id,
        user_input="乙",
        input_text="二",
        output="新问",
        message_list="对话乙",
    )
    assert a[0] == b[0] == system
    assert a[1] != b[1]


def test_fixed_questions():
    expected = {
        "L03": "有没有高血压、糖尿病、脂肪肝、甲状腺这类问题？或者其他需要长期吃药的疾病？",
        "L04": "家里人（特别是父母）有肥胖或“三高”的情况吗",
        "L05": "您的工作主要是坐着吗？最近工作或生活上有没有让您感觉压力特别大的事？",
        "L06": "平时感觉精力怎么样，是容易累、犯懒，还是精神很好？情绪容易烦躁吗？",
        "L07": "晚上睡眠好吗？比如会不会失眠、多梦，或者睡觉打鼾、憋气？",
        "L08": "您的一日三餐。饭量大吗？有没有偏爱油炸、甜食或面食之类的习惯？",
        "L09": "平时有吃零食，夜宵，或者喝饮料、喝酒的习惯吗？",
        "L10": "饭后容易肚子胀吗？大便是否规律，是偏稀还是偏干？",
        "L11": "晚上起夜多吗？平时会不会觉得腰酸、怕冷或者手脚发凉？",
        "L12": "平时有主动运动的习惯吗？主要做什么运动，每周大概能坚持多长时间？",
        "L13": "稍微活动一下会不会感觉特别喘，上气不接下气？",
        "L15": "您是否有孩子？",
        "L16": "您月经周期准吗，量怎么样，颜色深不深。",
        "L17": "您月经有没有血块？有无月经前乳房小腹胀痛和痛经的现象？",
        "L18": "您白带正常吗？有无发黄、量多或瘙痒。",
    }
    assert {
        step.prompt_id: step.fixed_question for step in STEPS if isinstance(step, Ask)
    } == expected


def test_replacement_is_single_pass_and_rejects_unknown_placeholders(monkeypatch):
    _, user = rendering.render_prompt(
        "L04", user_input="资料{{input}}", output="问题", input_text="回答{{output}}"
    )
    assert "资料{{input}}" in user and "回答{{output}}" in user
    original = rendering.load_prompt("L04")
    monkeypatch.setattr(rendering, "load_prompt", lambda _: original + "{{unknown}}")
    with pytest.raises(ValueError, match="Undeclared"):
        rendering.render_prompt("L04", user_input="资料")


@pytest.mark.parametrize(
    "birthday,basis,expected",
    [
        ("2000-05-01", date(2026, 5, 1), 26),
        ("2000/05/01", date(2026, 4, 30), 25),
        ("20000501", date(2026, 5, 1), 26),
        ("2000-02-29", date(2025, 2, 28), 24),
        ("2000-02-29", date(2025, 3, 1), 25),
        ("2001-02-29", date(2026, 5, 1), None),
        ("2027-05-01", date(2026, 5, 1), None),
        (None, date(2026, 5, 1), None),
        ("nonsense", date(2026, 5, 1), None),
    ],
)
def test_age(birthday, basis, expected):
    assert rendering.age_on(birthday, basis) == expected


def test_patient_rendering_and_beijing_basis():
    basis = (
        datetime(2026, 4, 30, 16, tzinfo=timezone.utc)
        .astimezone(rendering.BEIJING)
        .date()
    )
    result = rendering.render_patient(
        {
            "patient": {
                "sex": "女",
                "birthday": "2000-05-01",
                "height_cm": 162.0,
                "weight_kg": 70,
                "target_weight_kg": 60,
                "name": "PRIVATE_NAME",
                "phone": "PRIVATE_PHONE",
            },
            "assessments": {
                "face": {"text": "面部"},
                "tongue": {"text": " "},
                "tongue_down": {"text": "舌下"},
                "pulse": {"text": "脉象"},
            },
        },
        basis,
    )
    assert result == (
        "[基本信息]\n- 性别: 女\n- 年龄: 26\n- 生日: 2000-05-01\n- 身高: 162cm\n"
        "- 体重: 70kg\n- 目标体重: 60kg\n\n[面部情况分析]\n面部\n\n"
        "[舌象（舌下）分析]\n舌下\n\n[脉象情况分析]\n脉象"
    )


def test_raw_device_series_are_removed_from_patient_input():
    wave = str(list(range(1700, 1500, -1)))
    pulse = json.dumps(
        {
            "chenfu_right": {"chenfu_ychi": ["沉脉"]},
            "Filtered_data": {"youchimid": wave, "youcunmid": wave},
            "pulse_rate": "60",
            "xushi_right": {"xushi_ychi": ["实脉"]},
            "scores": [0.5, 0.2, 0.3],
            "native_series": list(range(40)),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    stripped = rendering.strip_raw_series(pulse)
    assert json.loads(stripped) == {
        "chenfu_right": {"chenfu_ychi": ["沉脉"]},
        "pulse_rate": "60",
        "xushi_right": {"xushi_ychi": ["实脉"]},
        "scores": [0.5, 0.2, 0.3],
    }
    assert len(stripped) < len(pulse) // 4
    tongue = '{"code":88,"data":{"tizhi":{"qixu":0.39},"char":"舌质淡红"}}'
    for unchanged in ("脉象平和", tongue, '"text"', "[1, 2, 3]"):
        assert rendering.strip_raw_series(unchanged) == unchanged
    rendered = rendering.render_patient(
        {"patient": {}, "assessments": {"pulse": {"text": pulse}}}, date(2026, 1, 1)
    )
    assert "Filtered_data" not in rendered and "沉脉" in rendered


def test_transcript_order_and_archive_format():
    messages = [
        {"seq": 2, "role": "user", "content": "回答"},
        {"seq": 1, "role": "assistant", "content": "问题"},
    ]
    assert rendering.format_messages(messages) == "医生：问题\n患者：回答"
    assert rendering.format_messages(messages, archive=True) == "AI: 问题\nUser: 回答"
