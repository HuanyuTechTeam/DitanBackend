"""Server-owned scope, fixed for an operation's lifetime."""

from dataclasses import dataclass

LEGACY_ORG_ID = "__legacy__"


@dataclass(frozen=True)
class OrganizationContext:
    org_id: str

    def __post_init__(self) -> None:
        if not self.org_id or not self.org_id.strip():
            raise ValueError("An organization scope is required")
