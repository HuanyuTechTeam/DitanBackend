"""Export a small deidentified Coze replay batch over an authorized SSH connection.

Only the remote worker sees source identifiers. It uses a read-only PostgreSQL
transaction and emits sanitized samples; no source rows or mapping are persisted.
"""

import argparse
from collections import Counter
from datetime import date, datetime
import json
from pathlib import Path
import re
import subprocess
import sys
import unicodedata

MARK = "[已脱敏]"
COMMON_SURNAMES = "赵钱孙李周吴郑王冯陈蒋沈韩杨朱秦许何吕张孔曹严华金魏陶姜谢邹范彭鲁韦马俞任袁柳史唐薛雷贺倪汤罗毕郝安常于傅齐康伍余顾孟黄穆萧尹姚邵汪毛成戴宋庞熊纪项董梁杜蓝贾江童颜郭梅林钟徐邱高夏蔡田樊胡霍万管卢莫丁邓洪包左石崔龚程邢陆翁段刘龙叶乔谭曾廖牛"
PHONE = re.compile(r"(?<![\d.])(?:\+?86[- ]?)?1[3-9](?:[- ]?\d){9}(?!\d)")
LANDLINE = re.compile(r"(?<!\d)0\d{2,3}[- ]?\d{7,8}(?!\d)")
IDENTITY_CARD = re.compile(r"(?<![A-Za-z0-9])\d{17}[\dXx](?![A-Za-z0-9])")
EMAIL = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
URL = re.compile(r"(?:https?://|www\.)[^\s\"'<>\u3000]+", re.IGNORECASE)
UUID = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE
)
LONG_ID = re.compile(r"\b(?=[A-Za-z0-9]{20,}\b)(?=[A-Za-z0-9]*\d)[A-Za-z0-9]+\b")
TIMESTAMP = re.compile(
    r"(?<!\d)\d{4}[-/]\d{1,2}[-/]\d{1,2}[ T]\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?(?!\d)"
)
ROLE = re.compile(r"^(User|AI|Status):[ \t]*(.*)$", re.IGNORECASE)
IDENTIFIER_LABEL = re.compile(
    r"(?i)(姓名|患者姓名|名字|手机号|电话号码|电话|联系方式|身份证(?:号)?|证件(?:号)?|"
    r"患者编号|病历号|就诊编号|住址|家庭地址|联系地址|工作单位|学校|微信(?:号)?|邮箱|"
    r"patient_name|patient_phone|phone|mobile|email|address|id_card)"
    r"([\"']?[ \t]*[:：=][ \t]*)([\"']?)([^\n，,;；\"'<>]+)"
)


def age_on(birthday: str | None, basis: date) -> int | None:
    if not birthday:
        return None
    try:
        born = date.fromisoformat(birthday)
    except ValueError:
        return None
    if born > basis:
        return None
    return basis.year - born.year - ((basis.month, basis.day) < (born.month, born.day))


def anonymous_dates(
    birthday: str | None, consultation_date: str
) -> tuple[str, str | None]:
    age = age_on(birthday, date.fromisoformat(consultation_date))
    for month in (1, 4, 7, 10):
        basis = date(2026, month, 1)
        replacement = (
            date(2026 - age, month, 1).isoformat() if age is not None else None
        )
        if basis.isoformat() != consultation_date and (
            replacement is None or replacement != birthday
        ):
            return basis.isoformat(), replacement
    raise ValueError("Cannot choose anonymous age-preserving dates")


class Redactor:
    def __init__(self, rows: list[dict]):
        self.identifiers = set()
        for row in rows:
            for field in ("patient_name", "patient_phone"):
                value = (
                    unicodedata.normalize("NFKC", str(row.get(field) or ""))
                    .replace("\u200b", "")
                    .strip()
                )
                if len(value) >= 2 and value not in {"未知", "匿名", "测试患者"}:
                    self.identifiers.add(value)
        self.identity_patterns = []
        for value in sorted(self.identifiers, key=len, reverse=True):
            expression = re.escape(value)
            if value.isascii() and re.search(r"[A-Za-z]", value):
                expression = r"(?<![A-Za-z0-9])" + expression + r"(?![A-Za-z0-9])"
            self.identity_patterns.append(re.compile(expression, re.IGNORECASE))
        self.counts: Counter = Counter()
        surnames = set(COMMON_SURNAMES) | {
            str(row.get("patient_name") or "")[0:1] for row in rows
        }
        self.salutation = re.compile(
            rf"[{re.escape(''.join(sorted(surnames)))}][\u4e00-\u9fff]{{0,3}}(?:先生|女士|小姐|医生|阿姨|叔叔)"
        )

    def scrub(self, text: str | None, birthday: str | None = None) -> str:
        result = (
            unicodedata.normalize("NFKC", text or "")
            .replace("\u200b", "")
            .replace("\ufeff", "")
        )
        for pattern in self.identity_patterns:
            result, count = pattern.subn(MARK, result)
            self.counts["known_identity"] += count
        if birthday:
            try:
                born = date.fromisoformat(birthday)
                dates = {
                    birthday,
                    birthday.replace("-", "/"),
                    birthday.replace("-", ""),
                    f"{born.year}年{born.month}月{born.day}日",
                    f"{born.year}年{born.month:02}月{born.day:02}日",
                }
                for value in dates:
                    result, count = re.subn(re.escape(value), "[生日已脱敏]", result)
                    self.counts["birthday"] += count
            except ValueError:
                pass
        for label, pattern in (
            ("phone", PHONE),
            ("phone", LANDLINE),
            ("identity_card", IDENTITY_CARD),
            ("email", EMAIL),
            ("url", URL),
            ("uuid", UUID),
            ("long_id", LONG_ID),
            ("timestamp", TIMESTAMP),
        ):
            result, count = pattern.subn(MARK, result)
            self.counts[label] += count
        result, count = IDENTIFIER_LABEL.subn(
            lambda m: m[1] + m[2] + m[3] + MARK, result
        )
        self.counts["identifier_label"] += count
        # Names in greetings need not match the name currently stored on the patient row.
        result, count = self.salutation.subn("[称呼]", result)
        self.counts["salutation"] += count
        result = re.sub(
            r"(?:我叫|我的名字(?:是|叫)|我姓)[^，,。.!！?？\n]{1,12}",
            "姓名" + MARK,
            result,
        )
        result = re.sub(
            r"(?:家住|住在|居住于|居住在|家庭住址为)[^，,。.!！?？\n]+",
            "住址" + MARK,
            result,
        )
        result = re.sub(
            r"(?:我在|就职于|任职于)[^，,。.!！?？\n]{1,32}(?:公司|医院|大学|学校|集团|银行|研究所|工厂)",
            "工作单位" + MARK,
            result,
        )
        return result

    def verify(self, sample: dict):
        encoded = json.dumps(sample, ensure_ascii=False)
        if any(pattern.search(encoded) for pattern in self.identity_patterns):
            raise ValueError("Known identity survived redaction")
        if any(
            pattern.search(encoded)
            for pattern in (PHONE, LANDLINE, IDENTITY_CARD, EMAIL, URL, UUID)
        ):
            raise ValueError("Identifier pattern survived redaction")


def anonymize_row(row: dict, redactor: Redactor, sample_id: str) -> dict:
    basis, birthday = anonymous_dates(row.get("birthday"), row["consultation_date"])
    original_birthday = row.get("birthday")
    sample = {
        "sample_id": sample_id,
        "consultation_date": basis,
        "inputs": {
            "patient": {
                "sex": {"MALE": "男", "FEMALE": "女"}.get(
                    (row.get("sex") or "").upper()
                ),
                "birthday": birthday,
                "height_cm": row.get("height"),
                "weight_kg": row.get("weight"),
                "target_weight_kg": None,
            },
            "assessments": {
                key: redactor.scrub(row.get(source), original_birthday)
                for key, source in (
                    ("face", "face"),
                    ("tongue", "tongue_front"),
                    ("tongue_down", "tongue_bottom"),
                    ("pulse", "pulse"),
                )
            },
        },
        "coze_conversation_log": redactor.scrub(
            row.get("coze_conversation_log"), original_birthday
        ),
        "coze_report": redactor.scrub(row.get("coze_report"), original_birthday),
    }
    redactor.verify(sample)
    return sample


def select_rows(rows: list[dict], count: int) -> list[dict]:
    def quality(row):
        dialogue = row.get("coze_conversation_log") or ""
        answers = len(re.findall(r"(?m)^User:", dialogue))
        age = age_on(row.get("birthday"), date.fromisoformat(row["consultation_date"]))
        expected = 12
        if row.get("sex") == "FEMALE" and (age is None or age >= 10):
            expected += 4 if age is not None and age >= 20 else 3
        lengths = [
            len(row.get(key) or "")
            for key in ("face", "tongue_front", "tongue_bottom", "pulse")
        ]
        assessment_size = sum(
            len(row.get(key) or "")
            for key in ("face", "tongue_front", "tongue_bottom", "pulse")
        )
        return (
            answers >= 11,
            -abs(answers - expected),
            sum(length > 100 for length in lengths),
            -assessment_size,
        )

    ranked = sorted(rows, key=quality, reverse=True)
    selected, groups = [], set()
    for row in ranked:
        age = age_on(row.get("birthday"), date.fromisoformat(row["consultation_date"]))
        group = (
            row.get("sex"),
            "unknown"
            if age is None
            else "child"
            if age < 10
            else "teen"
            if age < 20
            else "adult",
        )
        if group not in groups:
            groups.add(group)
            selected.append(row)
            if len(selected) == count:
                return selected
    for row in ranked:
        if not any(row is existing for existing in selected):
            selected.append(row)
            if len(selected) == count:
                break
    return selected


def remote_export(container: str, count: int, candidate_limit: int) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", container):
        raise ValueError("Invalid container name")
    if not 1 <= count <= 20 or not count <= candidate_limit <= 500:
        raise ValueError("Invalid bounded export size")
    sql = (
        """
BEGIN TRANSACTION READ ONLY;
SET LOCAL statement_timeout = '10s';
SET LOCAL lock_timeout = '1s';
SELECT row_to_json(sample) FROM (
 SELECT p.name AS patient_name, p.phone AS patient_phone, p.sex::text AS sex,
   p.birthday::text AS birthday,
   (((r.created_at AT TIME ZONE 'UTC') AT TIME ZONE 'Asia/Shanghai')::date)::text AS consultation_date,
   d.height, d.weight, d.coze_conversation_log,
   s.face, s.tongue_front, s.tongue_bottom, s.pulse, s.diagnosis_result AS coze_report
 FROM patient_medical_records r
 JOIN patients p ON p.patient_id=r.patient_id AND p.org_id=r.org_id
 JOIN pre_diagnosis_records d ON d.record_id=r.record_id AND d.org_id=r.org_id
 JOIN sanzhen_analysis_results s ON s.pre_diagnosis_id=d.pre_diagnosis_id
 WHERE coalesce(trim(d.coze_conversation_log),'')<>'' AND coalesce(trim(s.diagnosis_result),'')<>''
 ORDER BY r.record_id DESC LIMIT %d
) sample;
ROLLBACK;
"""
        % candidate_limit
    )
    process = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            container,
            "sh",
            "-c",
            'exec psql -X -q -A -t -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"',
        ],
        input=sql,
        text=True,
        capture_output=True,
        timeout=20,
    )
    if process.returncode:
        raise RuntimeError("Read-only PostgreSQL export failed")
    rows = [json.loads(line) for line in process.stdout.splitlines() if line.strip()]
    redactor = Redactor(rows)
    samples = [
        anonymize_row(row, redactor, f"S{index:03}")
        for index, row in enumerate(select_rows(rows, count), 1)
    ]
    return {
        "samples": samples,
        "summary": {
            "candidate_count": len(rows),
            "exported_count": len(samples),
            "redactions": dict(redactor.counts),
            "raw_rows_written": False,
            "dates": "Synthetic consultation and birth dates preserve whole-year age",
            "source_date_basis": "medical record created_at, interpreted as UTC then converted to Beijing date",
            "cohorts": [
                {
                    "sample_id": sample["sample_id"],
                    "sex": sample["inputs"]["patient"]["sex"],
                    "age": age_on(
                        sample["inputs"]["patient"]["birthday"],
                        date.fromisoformat(sample["consultation_date"]),
                    ),
                }
                for sample in samples
            ],
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh-host", help="Explicitly authorized SSH host alias")
    parser.add_argument("--container", default="ditan_db")
    parser.add_argument("--count", type=int, default=2)
    parser.add_argument("--candidate-limit", type=int, default=100)
    parser.add_argument(
        "--output", type=Path, default=Path(".consultation-data/t9/samples.jsonl")
    )
    parser.add_argument("--remote-worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.remote_worker:
        try:
            result = remote_export(args.container, args.count, args.candidate_limit)
        except Exception as exc:
            # Never include a raw SQL row, identifier or exception message in the SSH response.
            print(json.dumps({"error": type(exc).__name__}), file=sys.stderr)
            raise SystemExit(1) from None
        print(json.dumps(result, ensure_ascii=False))
        return
    if not args.ssh_host or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]*", args.ssh_host
    ):
        parser.error("Use a configured SSH host alias")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", args.container):
        parser.error("Invalid container name")
    if not 1 <= args.count <= 20 or not args.count <= args.candidate_limit <= 500:
        parser.error("Use 1-20 samples and at most 500 candidate rows")
    if args.output.exists() or args.output.with_suffix(".summary.json").exists():
        parser.error("Output already exists; use a new batch path")
    source = Path(__file__).read_text(encoding="utf-8")
    process = subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            args.ssh_host,
            "python3",
            "-",
            "--remote-worker",
            "--container",
            args.container,
            "--count",
            str(args.count),
            "--candidate-limit",
            str(args.candidate_limit),
        ],
        input=source,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=45,
    )
    if process.returncode:
        raise SystemExit("Remote export failed; no source data saved")
    result = json.loads(process.stdout)
    for sample in result["samples"]:
        Redactor([]).verify(sample)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(
            json.dumps(sample, ensure_ascii=False) + "\n"
            for sample in result["samples"]
        ),
        encoding="utf-8",
    )
    summary = {
        **result["summary"],
        "exported_at": datetime.now().isoformat(timespec="seconds"),
    }
    args.output.with_suffix(".summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"output": str(args.output), **summary}, ensure_ascii=False))


if __name__ == "__main__":
    main()
