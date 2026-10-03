"""Scoped consultation reads; the turn service owns transaction boundaries."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.consultation import Consultation, ConsultationMessage, ConsultationTurn


class ConsultationRepository:
    def __init__(self, db: AsyncSession, org_id: str):
        self.db = db
        self.org_id = org_id

    async def get(
        self, consultation_id: str, *, lock: bool = False
    ) -> Consultation | None:
        query = select(Consultation).where(
            Consultation.org_id == self.org_id, Consultation.id == consultation_id
        )
        if lock:
            query = query.with_for_update()
        return await self.db.scalar(query.execution_options(populate_existing=True))

    async def get_turn(
        self, consultation_id: str, turn_id: str
    ) -> ConsultationTurn | None:
        return await self.db.scalar(
            select(ConsultationTurn)
            .where(
                ConsultationTurn.org_id == self.org_id,
                ConsultationTurn.consultation_id == consultation_id,
                ConsultationTurn.turn_id == turn_id,
            )
            .execution_options(populate_existing=True)
        )

    async def messages(
        self, consultation_id: str, turn_id: str | None = None
    ) -> list[ConsultationMessage]:
        query = (
            select(ConsultationMessage)
            .where(
                ConsultationMessage.org_id == self.org_id,
                ConsultationMessage.consultation_id == consultation_id,
            )
            .order_by(ConsultationMessage.seq)
        )
        if turn_id is not None:
            query = query.where(ConsultationMessage.turn_id == turn_id)
        return list((await self.db.scalars(query)).all())

    async def active_turn(self, consultation_id: str) -> ConsultationTurn | None:
        return await self.db.scalar(
            select(ConsultationTurn).where(
                ConsultationTurn.org_id == self.org_id,
                ConsultationTurn.consultation_id == consultation_id,
                ConsultationTurn.status == "processing",
            )
        )
