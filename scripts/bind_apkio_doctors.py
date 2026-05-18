"""将已有医生绑定到 Apkio Org 用户。

CSV 必须包含列：doctor_id, apkio_org_id, apkio_user_id, apkio_email。
"""

import argparse
import asyncio
import csv
import sys
from pathlib import Path

from sqlalchemy import select

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.core.database import async_session_maker, close_db  # noqa: E402
from app.models import Doctor  # noqa: E402

REQUIRED_COLUMNS = {"doctor_id", "apkio_org_id", "apkio_user_id", "apkio_email"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="绑定 Ditan 医生与 Apkio Org 用户")
    parser.add_argument("csv_path", type=Path, help="绑定清单 CSV 路径")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只校验并打印结果，不写入数据库",
    )
    return parser.parse_args()


def read_rows(csv_path: Path) -> list[tuple[int, dict[str, str]]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        columns = set(reader.fieldnames or [])
        missing = sorted(REQUIRED_COLUMNS - columns)
        if missing:
            raise ValueError(f"CSV 缺少必需列: {', '.join(missing)}")
        return [
            (line_number, {key: (value or "").strip() for key, value in row.items()})
            for line_number, row in enumerate(reader, start=2)
        ]


async def bind_doctors(csv_path: Path, *, dry_run: bool) -> int:
    rows = read_rows(csv_path)
    errors: list[str] = []
    seen_doctors: set[int] = set()
    seen_apkio_users: set[tuple[str, str]] = set()

    async with async_session_maker() as session:
        for line_number, row in rows:
            try:
                doctor_id = int(row["doctor_id"])
            except ValueError:
                errors.append(f"第 {line_number} 行 doctor_id 不是整数")
                continue

            apkio_org_id = row["apkio_org_id"]
            apkio_user_id = row["apkio_user_id"]
            apkio_email = row["apkio_email"]
            if not apkio_org_id or not apkio_user_id or not apkio_email:
                errors.append(f"第 {line_number} 行 Apkio 绑定字段不能为空")
                continue

            if doctor_id in seen_doctors:
                errors.append(f"第 {line_number} 行 doctor_id 重复: {doctor_id}")
                continue
            seen_doctors.add(doctor_id)

            apkio_key = (apkio_org_id, apkio_user_id)
            if apkio_key in seen_apkio_users:
                errors.append(
                    f"第 {line_number} 行 Apkio 用户重复: {apkio_org_id}/{apkio_user_id}"
                )
                continue
            seen_apkio_users.add(apkio_key)

            doctor = await session.get(Doctor, doctor_id)
            if doctor is None:
                errors.append(f"第 {line_number} 行医生不存在: {doctor_id}")
                continue

            conflict = await session.scalar(
                select(Doctor).where(
                    Doctor.doctor_id != doctor_id,
                    Doctor.apkio_org_id == apkio_org_id,
                    Doctor.apkio_user_id == apkio_user_id,
                )
            )
            if conflict is not None:
                errors.append(
                    f"第 {line_number} 行 Apkio 用户已绑定医生: "
                    f"{apkio_org_id}/{apkio_user_id} -> doctor_id={conflict.doctor_id}"
                )
                continue

            doctor.apkio_org_id = apkio_org_id
            doctor.apkio_user_id = apkio_user_id
            doctor.apkio_email = apkio_email

        if errors:
            await session.rollback()
            for error in errors:
                print(error, file=sys.stderr)
            return 1

        if dry_run:
            await session.rollback()
            print(f"校验通过，待绑定医生数: {len(rows)}")
            return 0

        await session.commit()
        print(f"绑定完成，医生数: {len(rows)}")
        return 0


async def main() -> int:
    args = parse_args()
    try:
        return await bind_doctors(args.csv_path, dry_run=args.dry_run)
    finally:
        await close_db()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
