"""Central role and permission policy for the EYRES desktop application."""

from dataclasses import dataclass


ADMIN = "admin"
OPERATOR = "operator"
QUALITY_ENGINEER = "quality_engineer"
MAINTENANCE = "maintenance"
AI_ENGINEER = "ai_engineer"

ROLES = (ADMIN, OPERATOR, QUALITY_ENGINEER, MAINTENANCE, AI_ENGINEER)
ROLE_LABELS = {
    ADMIN: "Administrator",
    OPERATOR: "Operator",
    QUALITY_ENGINEER: "Quality Engineer",
    MAINTENANCE: "Maintenance",
    AI_ENGINEER: "AI Engineer",
}

PAGE_PERMISSIONS = {
    "dashboard": set(ROLES),
    "machines": {ADMIN, MAINTENANCE},
    "projects": {ADMIN, QUALITY_ENGINEER, AI_ENGINEER},
    "capture": {ADMIN, OPERATOR, MAINTENANCE, AI_ENGINEER},
    "annotation": {ADMIN, QUALITY_ENGINEER, AI_ENGINEER},
    "augmentation": {ADMIN, AI_ENGINEER},
    "training": {ADMIN, AI_ENGINEER},
    "live": {ADMIN, OPERATOR, QUALITY_ENGINEER, MAINTENANCE, AI_ENGINEER},
    "roi": {ADMIN, QUALITY_ENGINEER, AI_ENGINEER},
    "plc": {ADMIN, OPERATOR, MAINTENANCE},
    "user_management": {ADMIN},
    "system_maintenance": {ADMIN},
    "diagnostics": {ADMIN},
}

INDEX_TO_PERMISSION = {
    0: "dashboard", 1: "machines", 2: "projects", 3: "capture",
    4: "annotation", 5: "augmentation", 6: "training", 7: "roi", 8: "plc",
    9: "user_management",
    10: "system_maintenance",
    11: "diagnostics",
}


def normalize_role(role) -> str:
    value = str(role or OPERATOR).strip().lower().replace(" ", "_")
    aliases = {"administrator": ADMIN, "quality_inspector": QUALITY_ENGINEER}
    value = aliases.get(value, value)
    return value if value in ROLES else OPERATOR


def can_access(role, permission: str) -> bool:
    return normalize_role(role) in PAGE_PERMISSIONS.get(permission, set())


def can_access_index(role, index: int) -> bool:
    permission = INDEX_TO_PERMISSION.get(index)
    return bool(permission and can_access(role, permission))


@dataclass(frozen=True)
class SessionUser:
    username: str
    role: str
    active: bool = True

    @classmethod
    def from_record(cls, record):
        record = record or {}
        return cls(
            username=str(record.get("username") or "unknown"),
            role=normalize_role(record.get("role")),
            active=bool(record.get("active", True)),
        )
