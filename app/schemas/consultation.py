"""Consultation inputs exclude direct patient identifiers."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, field_validator


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PatientInput(StrictInput):
    sex: Literal["男", "女"] | None = None
    birthday: str | None = None
    height_cm: FiniteFloat | None = None
    weight_kg: FiniteFloat | None = None
    target_weight_kg: FiniteFloat | None = None

    @field_validator("sex", mode="before")
    @classmethod
    def normalize_sex(cls, value):
        if isinstance(value, str):
            return {"male": "男", "female": "女"}.get(value.lower(), value)
        return value


class AssessmentInput(StrictInput):
    text: str | None = None
    source: str = "client"


class AssessmentsInput(StrictInput):
    face: AssessmentInput | None = None
    tongue: AssessmentInput | None = None
    tongue_down: AssessmentInput | None = None
    pulse: AssessmentInput | None = None


class ConsultationInputs(StrictInput):
    patient: PatientInput = Field(default_factory=PatientInput)
    assessments: AssessmentsInput = Field(default_factory=AssessmentsInput)


class ConsultationCreate(StrictInput):
    encounter_uuid: UUID
    pre_diagnosis_uuid: UUID | None = None
    inputs: ConsultationInputs


class TurnSubmit(StrictInput):
    turn_id: UUID
    kind: Literal["start", "answer", "report"]
    base_version: int = Field(ge=0, strict=True)
    text: str | None = None
    input_type: str | None = None
