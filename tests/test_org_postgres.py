"""Real PostgreSQL 17 migration and concurrent-write regressions.

Only runs against an explicitly supplied, disposable ditan_org_upload_test database.
Each test creates and drops its own randomly named schema.
"""

import asyncio
from copy import deepcopy
from datetime import datetime
import os
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from httpx import ASGITransport, AsyncClient
import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.exc import IntegrityError

from app.core.database import Base, get_db
from app.core.exceptions import DuplicateException
from app.core.organization import OrganizationContext
from app.models import (
    Patient,
    PatientMedicalRecord,
    PreDiagnosisRecord,
    SanzhenAnalysisResult,
)
from app.schemas.patient import MedicalRecordCreate
from app.services.medical_record_service import MedicalRecordService
from main import app
from tests.org_helpers import principal, upload_body

HEAD = "004_diagnosis_result_text"
PREVIOUS = "002_add_apkio_doctor_bindings"
MODELS = (Patient, PatientMedicalRecord, PreDiagnosisRecord, SanzhenAnalysisResult)


@pytest.fixture
async def pg_engine():
    url = os.environ.get("DITAN_TEST_POSTGRES_URL")
    if not url:
        pytest.skip(
            "Set DITAN_TEST_POSTGRES_URL to a disposable PostgreSQL 17 database"
        )
    parsed = make_url(url)
    if (
        parsed.drivername != "postgresql+asyncpg"
        or parsed.database != "ditan_org_upload_test"
    ):
        raise RuntimeError(
            "PostgreSQL tests require the dedicated ditan_org_upload_test database"
        )
    schema = "org_upload_test_" + uuid4().hex
    admin = create_async_engine(url, hide_parameters=True)
    engine = create_async_engine(
        url,
        hide_parameters=True,
        connect_args={"server_settings": {"search_path": schema}},
    )
    try:
        async with admin.begin() as conn:
            await conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
        yield engine
    finally:
        await engine.dispose()
        async with admin.begin() as conn:
            await conn.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin.dispose()


async def migrate(engine, revision=HEAD, downgrade=False):
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.attributes["configure_logger"] = False

    def run(connection):
        config.attributes["connection"] = connection
        (command.downgrade if downgrade else command.upgrade)(config, revision)

    async with engine.begin() as conn:
        await conn.run_sync(run)


async def snapshot(engine):
    async with engine.connect() as conn:

        def read(connection):
            metadata = sa.MetaData()
            metadata.reflect(connection)
            return {
                name: [
                    dict(row)
                    for row in connection.execute(
                        table.select().order_by(*table.primary_key)
                    ).mappings()
                ]
                for name, table in metadata.tables.items()
            }

        return await conn.run_sync(read)


async def row_counts(engine):
    async with engine.connect() as conn:
        return [
            await conn.scalar(sa.select(sa.func.count()).select_from(model))
            for model in MODELS
        ]


async def upload(engine, body, org="org-a"):
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        return await MedicalRecordService(
            session, OrganizationContext(org)
        ).create_medical_record(
            MedicalRecordCreate.model_validate(body),
            principal(org),
            str(uuid4()),
        )


async def seed_old_data(engine):
    def seed(connection):
        metadata = sa.MetaData()
        metadata.reflect(connection)
        now = datetime(2020, 1, 1)
        timestamps = {"created_at": now, "updated_at": now}

        def insert(table_name, **values):
            table = metadata.tables[table_name]
            return connection.execute(
                table.insert().values(**values).returning(*table.primary_key)
            ).scalar_one()

        doctor_id = insert(
            "doctors",
            username="historical",
            password_hash="synthetic",
            name="Synthetic doctor",
            gender="OTHER",
            phone="13900139000",
            **timestamps,
        )
        patient_id = insert(
            "patients",
            name="Synthetic historical patient",
            sex="MALE",
            birthday=now.date(),
            phone="13800138000",
        )
        record_id = insert(
            "patient_medical_records",
            patient_id=patient_id,
            uuid=str(uuid4()),
            status="pending",
            **timestamps,
        )
        pre_id = insert(
            "pre_diagnosis_records",
            record_id=record_id,
            uuid=str(uuid4()),
            coze_conversation_log="synthetic-old-transcript",
            **timestamps,
        )
        insert(
            "sanzhen_analysis_results",
            pre_diagnosis_id=pre_id,
            face="synthetic-face",
            face_image_url="https://invalid.test/historical",
        )
        ai_id = insert(
            "diagnosis_records",
            record_id=record_id,
            type="AI_DIAGNOSIS",
            formatted_medical_record="synthetic-ai-diagnosis",
            **timestamps,
        )
        insert("ai_diagnosis_records", diagnosis_id=ai_id, model_name="mock")
        diagnosis_id = insert(
            "diagnosis_records",
            record_id=record_id,
            type="DOCTOR_DIAGNOSIS",
            **timestamps,
        )
        insert(
            "doctor_diagnosis_records",
            diagnosis_id=diagnosis_id,
            doctor_id=doctor_id,
            comments="synthetic-doctor",
        )
        conversation_id = insert(
            "chat_conversations",
            session_id="old-linked-chat",
            patient_id=patient_id,
            is_active=True,
            **timestamps,
        )
        insert(
            "chat_conversations",
            session_id="old-anonymous-chat",
            patient_id=None,
            is_active=True,
            **timestamps,
        )
        insert(
            "chat_messages",
            conversation_id=conversation_id,
            role="USER",
            content="synthetic-old-chat",
            created_at=now,
        )

    async with engine.begin() as conn:
        await conn.run_sync(seed)


async def test_empty_database_upgrade_matches_models(pg_engine):
    await migrate(pg_engine)
    async with pg_engine.connect() as conn:
        revision = await conn.scalar(sa.text("SELECT version_num FROM alembic_version"))
        assert revision == HEAD
        differences = await conn.run_sync(
            lambda connection: compare_metadata(
                MigrationContext.configure(connection), Base.metadata
            )
        )
        assert differences == []
    assert await row_counts(pg_engine) == [0, 0, 0, 0]
    # A clean round trip must not leave enum types that break a second empty upgrade.
    await migrate(pg_engine, "base", downgrade=True)
    await migrate(pg_engine)
    assert await row_counts(pg_engine) == [0, 0, 0, 0]


async def test_upload_preserves_3000_character_diagnosis_result(
    pg_engine, monkeypatch, verifier
):
    await migrate(pg_engine)
    session_maker = async_sessionmaker(pg_engine, expire_on_commit=False)

    async def override_get_db():
        async with session_maker() as session:
            try:
                yield session
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    monkeypatch.setitem(app.dependency_overrides, get_db, override_get_db)
    body = upload_body()
    report = "测试诊断结果" * 500
    body["pre_diagnosis"]["sanzhen_analysis"]["diagnosis_result"] = report

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/medical-record",
            json=body,
            headers={"Authorization": "Bearer upload-a"},
        )
        assert response.status_code == 201, response.text
        result = response.json()
        assert result["success"] is True
        data = result["data"]
        assert data["pre_diagnosis"]["sanzhen_result"]["diagnosis_result"] == report

        # Repeating the same upload still returns the original record and full text.
        replay = await client.post(
            "/api/v1/medical-record",
            json=body,
            headers={"Authorization": "Bearer upload-a"},
        )
        assert replay.status_code == 201, replay.text
        assert replay.json()["data"] == data

    # A fresh session must read the committed text, not an in-memory response value.
    async with session_maker() as session:
        stored = await MedicalRecordService(
            session, OrganizationContext("org-a")
        ).get_complete_record(data["record_id"])
        assert stored["pre_diagnosis"]["sanzhen_result"]["diagnosis_result"] == report
    assert await row_counts(pg_engine) == [1, 1, 1, 1]


@pytest.mark.parametrize(
    "report",
    [None, "", "测试诊断结果", "甲" * 1024, "测试诊断结果" * 500],
    ids=["null", "empty", "short", "limit", "long"],
)
async def test_diagnosis_result_migration_round_trip(pg_engine, report):
    await migrate(pg_engine)
    body = upload_body()
    body["pre_diagnosis"]["sanzhen_analysis"]["diagnosis_result"] = report
    await upload(pg_engine, body)

    await migrate(pg_engine, "003_org_medical_upload", downgrade=True)
    async with pg_engine.connect() as conn:
        columns = await conn.run_sync(
            lambda connection: sa.inspect(connection).get_columns(
                "sanzhen_analysis_results"
            )
        )
        column = next(c for c in columns if c["name"] == "diagnosis_result")
        assert isinstance(column["type"], sa.VARCHAR)
        assert column["type"].length == 1024
        assert column["nullable"] is True
        stored = await conn.scalar(sa.select(SanzhenAnalysisResult.diagnosis_result))
        assert stored == (report[:1024] if report is not None else None)

    before = await snapshot(pg_engine)
    await migrate(pg_engine)
    after = await snapshot(pg_engine)
    for table in before:
        if table != "alembic_version":
            assert after[table] == before[table]
    async with pg_engine.connect() as conn:
        columns = await conn.run_sync(
            lambda connection: sa.inspect(connection).get_columns(
                "sanzhen_analysis_results"
            )
        )
        column = next(c for c in columns if c["name"] == "diagnosis_result")
        assert isinstance(column["type"], sa.Text)
        assert column["nullable"] is True


@pytest.mark.parametrize("uniqueness_style", ["index", "constraint", "both"])
async def test_historical_upgrade_preserves_data_and_removes_global_uniqueness(
    pg_engine, uniqueness_style
):
    await migrate(pg_engine, PREVIOUS)
    await seed_old_data(pg_engine)
    keys = [
        ("patients", "phone"),
        ("patient_medical_records", "uuid"),
        ("pre_diagnosis_records", "uuid"),
    ]
    if uniqueness_style != "index":
        async with pg_engine.begin() as conn:
            for table, column in keys:
                if uniqueness_style == "constraint":
                    await conn.execute(sa.text(f'DROP INDEX "ix_{table}_{column}"'))
                await conn.execute(
                    sa.text(
                        f'ALTER TABLE "{table}" ADD CONSTRAINT "old_{table}_{column}_uq" UNIQUE ("{column}")'
                    )
                )
    before = await snapshot(pg_engine)
    await migrate(pg_engine)
    after = await snapshot(pg_engine)
    for table, rows in before.items():
        if table == "alembic_version":
            continue
        assert len(rows) == len(after[table])
        for old, new in zip(rows, after[table]):
            assert all(new[key] == value for key, value in old.items())
            if "org_id" in new:
                assert new["org_id"] == "__legacy__"
    async with pg_engine.connect() as conn:

        def check(connection):
            inspector = sa.inspect(connection)
            for table, column in keys:
                assert not any(
                    c["column_names"] == [column]
                    for c in inspector.get_unique_constraints(table)
                )
                assert not any(
                    i["column_names"] == [column] and i["unique"]
                    for i in inspector.get_indexes(table)
                )
                org = next(
                    c for c in inspector.get_columns(table) if c["name"] == "org_id"
                )
                assert not org["nullable"]
                assert org["default"] is None

        await conn.run_sync(check)
    body = upload_body()
    # Use the historic UUIDs and phone in two new organizations.
    body["uuid"] = before["patient_medical_records"][0]["uuid"]
    body["pre_diagnosis"]["uuid"] = before["pre_diagnosis_records"][0]["uuid"]
    a, b = (
        await upload(pg_engine, body, "org-a"),
        await upload(pg_engine, body, "org-b"),
    )
    assert a.record_id != b.record_id
    assert await row_counts(pg_engine) == [3, 3, 3, 3]


@pytest.mark.parametrize("duplicate_field", ["phone", "record_uuid", "pre_uuid"])
async def test_downgrade_refuses_each_lossy_global_unique_constraint(
    pg_engine, duplicate_field
):
    await migrate(pg_engine)
    a = upload_body()
    b = upload_body()
    b["patient_phone"] = b["patient_info"]["phone"] = "13800138001"
    if duplicate_field == "phone":
        b["patient_phone"] = b["patient_info"]["phone"] = a["patient_phone"]
    elif duplicate_field == "record_uuid":
        b["uuid"] = a["uuid"]
    else:
        b["pre_diagnosis"]["uuid"] = a["pre_diagnosis"]["uuid"]
    await upload(pg_engine, a, "org-a")
    await upload(pg_engine, b, "org-b")
    before = await snapshot(pg_engine)
    with pytest.raises(RuntimeError, match="Unsafe downgrade refused"):
        await migrate(pg_engine, PREVIOUS, downgrade=True)
    assert await snapshot(pg_engine) == before


async def test_safe_downgrade_keeps_historical_rows_and_relationships(pg_engine):
    await migrate(pg_engine, PREVIOUS)
    await seed_old_data(pg_engine)
    before = await snapshot(pg_engine)
    await migrate(pg_engine)
    await migrate(pg_engine, PREVIOUS, downgrade=True)
    assert await snapshot(pg_engine) == before


@pytest.mark.parametrize(
    "mode", ["same", "different_records", "conflicting_content", "conflicting_patient"]
)
async def test_concurrent_uploads_have_no_duplicates_or_orphans(
    pg_engine, monkeypatch, mode
):
    await migrate(pg_engine)
    participants = 6
    barrier = asyncio.Barrier(participants)
    original_insert = MedicalRecordService._insert_upload

    async def synchronized_insert(service, *args, **kwargs):
        if not getattr(service, "_test_waited", False):
            service._test_waited = True
            await asyncio.wait_for(barrier.wait(), timeout=15)
        return await original_insert(service, *args, **kwargs)

    monkeypatch.setattr(MedicalRecordService, "_insert_upload", synchronized_insert)
    body = upload_body()
    bodies = [deepcopy(body) for _ in range(participants)]
    for index, current in enumerate(bodies):
        if mode == "different_records":
            current["uuid"] = str(uuid4())
            current["pre_diagnosis"]["uuid"] = str(uuid4())
        elif mode == "conflicting_content":
            current["pre_diagnosis"]["coze_conversation_log"] = f"synthetic-{index}"
        elif mode == "conflicting_patient":
            current["patient_phone"] = current["patient_info"]["phone"] = (
                f"1380013800{index}"
            )
    results = await asyncio.wait_for(
        asyncio.gather(
            *(upload(pg_engine, current) for current in bodies),
            return_exceptions=True,
        ),
        timeout=30,
    )
    successes = [r for r in results if not isinstance(r, BaseException)]
    errors = [r for r in results if isinstance(r, BaseException)]
    if mode in ("conflicting_content", "conflicting_patient"):
        assert len(successes) == 1, results
        assert len(errors) == participants - 1
        assert all(isinstance(error, DuplicateException) for error in errors)
    else:
        assert not errors, errors
        assert len(successes) == participants
    expected_records = participants if mode == "different_records" else 1
    assert len({r.record_id for r in successes}) == expected_records
    assert await row_counts(pg_engine) == [
        1,
        expected_records,
        expected_records,
        expected_records,
    ]


async def test_database_rejects_cross_org_parent_link_even_without_repository(
    pg_engine,
):
    await migrate(pg_engine)
    body = upload_body()
    b = await upload(pg_engine, body, "org-b")
    async with async_sessionmaker(pg_engine, expire_on_commit=False)() as session:
        with pytest.raises(IntegrityError):
            async with session.begin():
                session.add(
                    PatientMedicalRecord(
                        org_id="org-a", patient_id=b.patient_id, uuid=str(uuid4())
                    )
                )
                await session.flush()
    assert await row_counts(pg_engine) == [1, 1, 1, 1]
