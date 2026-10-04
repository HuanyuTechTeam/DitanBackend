"""Versioned workflows; retain old versions for existing consultations."""

from app.services.consultation.workflows import v1


def get_workflow(version: str):
    if version == "v1":
        return v1
    raise ValueError(f"Unsupported workflow version: {version}")
