from datetime import date
import json

import pytest

from app.services.consultation.llm_fake import FakeTransport, Fault
from app.services.consultation.workflows.v1 import Ask, STEPS, WorkflowContext
from scripts.consultation_replay import (
    classify_question,
    load_samples,
    normalize_sample,
    parse_conversation,
    replay_sample,
    report_checks,
)


def sample(sex="男", birthday="2000-01-01"):
    from app.services.consultation.rendering import age_on

    context = WorkflowContext(sex, age_on(birthday, date(2026, 6, 1)))
    transcript = [
        "Status: connected",
        "AI: 开头介绍",
        "AI: [基本信息]\n- 性别: " + (sex or "未知"),
    ]
    for step in STEPS:
        if isinstance(step, Ask) and step.when(context):
            transcript += ["AI: " + step.fixed_question, "User: 这是合成回答"]
    transcript += [
        "AI: 感谢您的回答，请点击下方按钮，获取报告",
        "User: 获取报告",
        "AI: 后面的报告文本不应成为问题",
    ]
    return {
        "sample_id": "SYN001",
        "consultation_date": "2026-06-01",
        "inputs": {
            "patient": {"sex": sex, "birthday": birthday},
            "assessments": {
                "face": "合成面部摘要",
                "pulse": {"text": "合成脉象", "source": "client"},
            },
        },
        "coze_conversation_log": "\n".join(transcript),
        "coze_report": "合成的旧报告",
    }


def test_parse_multiline_and_ignore_unpaired_intro_status_and_report():
    pairs = parse_conversation(
        "User: 无前置问题的摘要\nAI: 介绍\nAI: 问题第一行\n第二行\nStatus: 等待\nUser: 回答第一行\n第二行\nAI: 无后续患者回答"
    )
    assert len(pairs) == 1
    assert pairs[0].question == "问题第一行\n第二行"
    assert pairs[0].answer == "回答第一行\n第二行"


@pytest.mark.parametrize("sex,expected", [("男", 11), ("女", 15), (None, 11)])
def test_parser_and_topic_classification_cover_v1_questions(sex, expected):
    pairs = parse_conversation(sample(sex)["coze_conversation_log"])
    assert len(pairs) == expected + 1
    assert pairs[-1].report_control
    assert all(classify_question(pair.question) for pair in pairs)


def test_topic_uses_current_question_instead_of_previous_answer_commentary():
    assert classify_question("父亲血脂需要关注。您最近工作压力大吗？") == "work_stress"
    assert classify_question("月经规律是好事！白带正常吗？") == "leukorrhea"


async def test_replay_runs_real_service_in_temporary_sqlite_and_writes_comparison(
    tmp_path,
):
    transport = FakeTransport()
    source = sample("女", "2011-06-01")
    result = await replay_sample(source, tmp_path, provider="fake", transport=transport)
    assert result["status"] == "completed"
    assert len(result["rows"]) == 14
    assert "children" not in [row["step"] for row in result["rows"]]
    assert result["version"] == 16
    assert result["model_calls"] == 15
    assert result["prompt_tokens"] > 0
    assert "- 年龄: 15" in transport.calls[0][1].user_text
    assert transport.calls[-1][0] == "report"
    assert "患者：获取报告" not in transport.calls[-1][1].user_text
    report = (tmp_path / "SYN001.md").read_text(encoding="utf-8")
    assert "合成的旧报告" in report and "【假报告】" in report
    assert "| Coze 已保存报告 | 新后端报告 |" in report
    assert not list(tmp_path.glob(".replay-*"))


async def test_replay_does_not_invent_missing_answers(tmp_path):
    source = sample()
    source["coze_conversation_log"] = "AI: 有没有高血压？\nUser: 合成回答"
    result = await replay_sample(source, tmp_path, provider="fake")
    assert result["status"] == "incomplete"
    assert result["report"] is None
    assert result["model_calls"] == 2
    assert any("没有编造" in flag for flag in result["flags"])


async def test_replay_marks_order_mismatch_and_fallback(tmp_path):
    source = sample()
    source["coze_conversation_log"] = "AI: 月经有没有血块？\nUser: 合成回答"
    result = await replay_sample(
        source,
        tmp_path,
        provider="fake",
        transport=FakeTransport([Fault(fail_after=0)]),
    )
    assert result["rows"][0]["coze_step"] == "menstruation_detail"
    assert result["rows"][0]["step"] == "core_history"
    assert result["fallbacks"] == 1
    assert any("主题/顺序不同" in flag for flag in result["flags"])


async def test_failed_report_still_writes_reviewable_result(tmp_path):
    faults = [Fault() for _ in range(11)] + [Fault(fail_after=0), Fault(fail_after=0)]
    result = await replay_sample(
        sample(), tmp_path, provider="fake", transport=FakeTransport(faults)
    )
    assert result["status"] == "failed" and result["report"] is None
    assert result["model_calls"] == 13
    assert (tmp_path / "SYN001.md").is_file()
    assert not list(tmp_path.glob(".replay-*"))


async def test_replay_checks_generated_text_not_only_step_metadata(tmp_path):
    source = sample()
    source["coze_conversation_log"] = "AI: 有没有高血压？\nUser: 合成回答"
    result = await replay_sample(
        source,
        tmp_path,
        provider="fake",
        transport=FakeTransport([Fault(text="您的月经周期正常吗？量多不多？")]),
    )
    assert result["rows"][0]["step"] == "core_history"
    assert result["rows"][0]["new_step"] == "menstruation"
    assert any("新模型疑似偏题" in flag for flag in result["flags"])


def test_input_requires_anonymous_sample_id_and_no_direct_identifiers(tmp_path):
    source = sample()
    source["sample_id"] = "../escape"
    with pytest.raises(ValueError):
        normalize_sample(source)
    source = sample()
    source["coze_report"] = "电话13800138000"
    with pytest.raises(ValueError):
        normalize_sample(source)
    source_path = tmp_path / "sample.jsonl"
    source_path.write_text(json.dumps(source, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="non-deidentified"):
        load_samples(source_path)


def test_report_checks_only_flag_for_human_review():
    assert report_checks("# 报告\n建议服用某药。")
    assert not report_checks("主证分析：合成内容。")
