from datetime import date
import json
from types import SimpleNamespace

import pytest

from scripts.consultation_export import (
    Redactor,
    age_on,
    anonymous_dates,
    anonymize_row,
    remote_export,
    select_rows,
)


def source_row():
    return {
        "patient_name": "李小夏",
        "patient_phone": "13800138000",
        "sex": "FEMALE",
        "birthday": "1990-05-01",
        "consultation_date": "2026-04-30",
        "height": 162,
        "weight": 65,
        "face": "面色正常",
        "tongue_front": "舌苔薄白",
        "tongue_bottom": "舌下络脉",
        "pulse": "脉象",
        "coze_conversation_log": "AI: 李女士您好，睡眠好吗？\nUser: 睡眠还好。",
        "coze_report": "李小夏，出生于1990年5月1日，联系电话13800138000。四诊摘要。",
    }


@pytest.mark.parametrize(
    "birthday,basis",
    [
        ("1990-01-01", "2026-07-01"),
        ("1990-05-01", "2026-04-30"),
        ("2000-02-29", "2025-02-28"),
        ("2000-02-29", "2025-03-01"),
        (None, "2026-01-01"),
        ("2030-01-01", "2026-01-01"),
    ],
)
def test_shifted_dates_preserve_age_without_original_birthday(birthday, basis):
    shifted_basis, shifted_birthday = anonymous_dates(birthday, basis)
    assert age_on(birthday, date.fromisoformat(basis)) == age_on(
        shifted_birthday, date.fromisoformat(shifted_basis)
    )
    assert shifted_basis != basis
    assert shifted_birthday is None or shifted_birthday != birthday


def test_deidentification_covers_summary_dialogue_report_and_other_identifiers():
    row = source_row()
    row["coze_conversation_log"] += (
        "\nUser: 姓名:李小夏，手机号:+86 138-0013-8000，电话１３８００１３８０００。"
        "邮箱:person@example.test 身份证:110101199005010020\n"
        "我家住示例市示例路123号。我在示例科技公司上班。\n"
        "https://example.test/patient/private.png 550e8400-e29b-41d4-a716-446655440000"
    )
    sample = anonymize_row(row, Redactor([row]), "S001")
    text = json.dumps(sample, ensure_ascii=False)
    for value in (
        "李小夏",
        "李女士",
        "13800138000",
        "person@example",
        "110101199005010020",
        "示例市",
        "示例科技",
        "https://",
        "550e8400",
        "1990年5月1日",
    ):
        assert value not in text
    assert sample["inputs"]["patient"]["sex"] == "女"
    assert "睡眠还好" in sample["coze_conversation_log"]
    assert "舌苔薄白" in sample["inputs"]["assessments"]["tongue"]
    assert set(sample) == {
        "sample_id",
        "consultation_date",
        "inputs",
        "coze_conversation_log",
        "coze_report",
    }


def test_cross_record_names_are_removed_and_known_identity_fails_closed():
    row = source_row()
    other = {**row, "patient_name": "陈明秋", "patient_phone": "13900139000"}
    row["face"] = "李小夏及陈明秋的摘要"
    redactor = Redactor([row, other])
    assert (
        "陈明秋"
        not in anonymize_row(row, redactor, "S001")["inputs"]["assessments"]["face"]
    )
    with pytest.raises(ValueError, match="Known identity"):
        redactor.verify({"coze_report": "陈明秋"})


def test_selection_covers_available_sex_branches():
    female = source_row()
    male = {**female, "sex": "MALE"}
    selected = select_rows([female, {**female}, male], 2)
    assert {row["sex"] for row in selected} == {"MALE", "FEMALE"}


def test_salutation_redaction_keeps_generic_age_description():
    text = Redactor([]).scrub("牛女士您好，看您是位30多岁的女士。")
    assert "牛女士" not in text
    assert "30多岁的女士" in text


def test_technical_timestamps_are_redacted_but_clinical_years_are_kept():
    text = Redactor([]).scrub("采集时间2025-10-01 13:12:15.123+08:00；2010年开始不适。")
    assert "2025-10-01" not in text
    assert "2010年开始不适" in text


@pytest.mark.parametrize(
    "name,mention", [("Ａｌｉｃｅ", "alice"), ("李\u200b小夏", "李小夏")]
)
def test_known_identities_are_normalized_consistently(name, mention):
    redactor = Redactor([{"patient_name": name}])
    value = redactor.scrub("患者说：" + mention)
    assert mention not in value
    redactor.verify({"text": value})


def test_remote_worker_is_read_only_and_only_returns_anonymous_rows(monkeypatch):
    row = source_row()

    def query(command, **kwargs):
        assert command[:4] == ["docker", "exec", "-i", "ditan_db"]
        sql = kwargs["input"]
        assert "BEGIN TRANSACTION READ ONLY" in sql and "ROLLBACK" in sql
        assert "statement_timeout" in sql and "LIMIT 30" in sql
        assert "patient_name" in sql
        return SimpleNamespace(returncode=0, stdout=json.dumps(row) + "\n")

    monkeypatch.setattr("scripts.consultation_export.subprocess.run", query)
    result = remote_export("ditan_db", 1, 30)
    serialized = json.dumps(result, ensure_ascii=False)
    assert "李小夏" not in serialized and "13800138000" not in serialized
    assert result["summary"]["raw_rows_written"] is False


def test_database_failure_never_echoes_source_data(monkeypatch):
    monkeypatch.setattr(
        "scripts.consultation_export.subprocess.run",
        lambda *a, **k: SimpleNamespace(
            returncode=1, stdout="private-row", stderr="private-error"
        ),
    )
    with pytest.raises(
        RuntimeError, match="Read-only PostgreSQL export failed"
    ) as error:
        remote_export("ditan_db", 1, 30)
    assert "private" not in str(error.value)
