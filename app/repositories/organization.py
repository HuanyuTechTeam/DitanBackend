"""Repositories that require an explicit server-owned scope for every operation."""

from typing import Any, TypeVar, Type
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.exceptions import NotFoundException
from app.core.organization import LEGACY_ORG_ID, OrganizationContext
from app.models import (
    Patient,
    PatientMedicalRecord,
    PreDiagnosisRecord,
    SanzhenAnalysisResult,
    AIDiagnosisRecord,
    DoctorDiagnosisRecord,
    Doctor,
)
from app.repositories.base import BaseRepository

T = TypeVar("T")


class OrganizationRepository(BaseRepository[T]):
    def __init__(
        self, db: AsyncSession, model: Type[T], organization: OrganizationContext
    ):
        super().__init__(db, model)
        self.organization = organization

    def _scope_clause(self) -> ColumnElement[bool]:
        model: Any = self.model
        org_id = self.organization.org_id
        if self.model in (Patient, PatientMedicalRecord, PreDiagnosisRecord):
            return model.org_id == org_id
        if self.model is SanzhenAnalysisResult:
            return (
                select(PreDiagnosisRecord.pre_diagnosis_id)
                .where(
                    PreDiagnosisRecord.pre_diagnosis_id == model.pre_diagnosis_id,
                    PreDiagnosisRecord.org_id == org_id,
                )
                .exists()
            )
        return (
            select(PatientMedicalRecord.record_id)
            .where(
                PatientMedicalRecord.record_id == model.record_id,
                PatientMedicalRecord.org_id == org_id,
            )
            .exists()
        )

    def _select(self):
        return select(self.model).where(self._scope_clause())

    async def _authorize_entity(self, entity: T) -> None:
        org_id = self.organization.org_id
        if isinstance(entity, (Patient, PatientMedicalRecord, PreDiagnosisRecord)):
            if entity.org_id != org_id:
                raise NotFoundException()
        if isinstance(entity, PatientMedicalRecord):
            parent = await self.db.scalar(
                select(Patient.patient_id).where(
                    Patient.patient_id == entity.patient_id,
                    Patient.org_id == org_id,
                )
            )
            if parent is None:
                raise NotFoundException()
        if isinstance(
            entity, (PreDiagnosisRecord, AIDiagnosisRecord, DoctorDiagnosisRecord)
        ):
            parent = await self.db.scalar(
                select(PatientMedicalRecord.record_id).where(
                    PatientMedicalRecord.record_id == entity.record_id,
                    PatientMedicalRecord.org_id == org_id,
                )
            )
            if parent is None:
                raise NotFoundException()
        if isinstance(entity, SanzhenAnalysisResult):
            parent = await self.db.scalar(
                select(PreDiagnosisRecord.pre_diagnosis_id).where(
                    PreDiagnosisRecord.pre_diagnosis_id == entity.pre_diagnosis_id,
                    PreDiagnosisRecord.org_id == org_id,
                )
            )
            if parent is None:
                raise NotFoundException()
        if isinstance(entity, DoctorDiagnosisRecord):
            doctor_scope = (
                Doctor.apkio_org_id.is_(None)
                if org_id == LEGACY_ORG_ID
                else Doctor.apkio_org_id == org_id
            )
            doctor = await self.db.scalar(
                select(Doctor.doctor_id).where(
                    Doctor.doctor_id == entity.doctor_id,
                    doctor_scope,
                )
            )
            if doctor is None:
                raise NotFoundException()

    async def create(self, entity: T) -> T:
        await self._authorize_entity(entity)
        return await super().create(entity)

    async def update(self, entity: T) -> T:
        await self._authorize_entity(entity)
        return await super().update(entity)

    async def delete(self, entity: T) -> None:
        await self._authorize_entity(entity)
        await super().delete(entity)

    async def refresh(self, entity: T, attribute_names: list[str] | None = None) -> T:
        await self._authorize_entity(entity)
        return await super().refresh(entity, attribute_names)
