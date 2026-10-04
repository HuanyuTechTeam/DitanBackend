from datetime import timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.exc import IntegrityError

from app.models.consultation import Consultation, ConsultationTurn, utcnow
from tests.test_org_postgres import migrate
from tests.test_org_postgres import pg_engine as pg_engine


def consultation(org="org-a", encounter=None):
    return Consultation(
        org_id=org,
        encounter_uuid=encounter or str(uuid4()),
        inputs={},
        created_by_user_id="operator",
        created_by_device_id="device",
    )


def turn(parent, org="org-a"):
    return ConsultationTurn(
        org_id=org,
        consultation_id=parent,
        turn_id=str(uuid4()),
        kind="start",
        base_version=0,
        deadline_at=utcnow() + timedelta(seconds=60),
        actor_user_id="operator",
        actor_device_id="device",
    )


async def test_active_encounter_is_unique_per_org(pg_engine):
    await migrate(pg_engine)
    async with async_sessionmaker(pg_engine, expire_on_commit=False)() as session:
        encounter = str(uuid4())
        first = consultation(encounter=encounter)
        session.add_all([first, consultation("org-b", encounter)])
        await session.commit()
        first_id = first.id
        session.add(consultation(encounter=encounter))
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()
        await session.execute(
            sa.update(Consultation)
            .where(Consultation.id == first_id)
            .values(status="abandoned")
        )
        await session.commit()
        session.add(consultation(encounter=encounter))
        await session.commit()


async def test_processing_turn_is_unique_and_org_link_is_enforced(pg_engine):
    await migrate(pg_engine)
    async with async_sessionmaker(pg_engine, expire_on_commit=False)() as session:
        parent = consultation()
        session.add(parent)
        await session.commit()
        parent_id = parent.id
        session.add(turn(parent_id))
        await session.commit()
        session.add(turn(parent_id))
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()
        await session.execute(sa.update(ConsultationTurn).values(status="completed"))
        await session.commit()
        session.add(turn(parent_id, "org-b"))
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()
        session.add(turn(parent_id))
        await session.commit()


async def test_consultation_tables_upgrade_downgrade(pg_engine):
    await migrate(pg_engine)
    await migrate(pg_engine, "004_diagnosis_result_text", downgrade=True)
    async with pg_engine.connect() as conn:
        names = await conn.run_sync(
            lambda connection: sa.inspect(connection).get_table_names()
        )
        assert "consultations" not in names
        assert "sanzhen_analysis_results" in names
    await migrate(pg_engine)
    async with pg_engine.connect() as conn:
        names = await conn.run_sync(
            lambda connection: sa.inspect(connection).get_table_names()
        )
        assert {
            "consultations",
            "consultation_turns",
            "consultation_messages",
            "consultation_llm_calls",
        } <= set(names)
