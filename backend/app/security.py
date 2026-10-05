from __future__ import annotations

from fastapi import HTTPException, status

from .models import Role, User


ROLE_PERMISSIONS = {
    Role.caregiver: {"children:read", "journey:read"},
    Role.asha: {"children:read", "children:create", "dose:create", "journey:read"},
    Role.manager: {"children:read", "journey:read", "leaderboard:read"},
    Role.admin: {
        "children:read",
        "children:create",
        "dose:create",
        "journey:read",
        "leaderboard:read",
        "user:create",
    },
}


def require_permission(user: User, permission: str) -> None:
    if permission not in ROLE_PERMISSIONS[user.role]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Role does not have permission for this action",
        )
