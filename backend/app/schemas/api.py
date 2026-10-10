from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from ..models import Role, Sex


class LoginRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"phone": "+919000000101", "password": "demo123"}]})

    phone: str = Field(min_length=6, max_length=20)
    password: str = Field(min_length=1, max_length=255)


class RefreshRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"refresh_token": "refresh-token-from-login"}]})

    refresh_token: str = Field(min_length=20, max_length=512)


class OtpRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"phone": "+919000000101"}]})

    phone: str = Field(min_length=6, max_length=20)


class OtpVerify(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"phone": "+919000000101", "code": "123456"}]})

    phone: str = Field(min_length=6, max_length=20)
    code: str = Field(min_length=4, max_length=8)


class UserCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "role": "asha",
                    "name": "Sunita Devi",
                    "phone": "+919000000101",
                    "village_id": 1,
                    "password": "demo123",
                    "preferred_language": "hi",
                }
            ]
        }
    )

    role: Role
    name: str = Field(min_length=1, max_length=100)
    phone: str = Field(min_length=6, max_length=20)
    village_id: Optional[int] = None
    password: Optional[str] = Field(default=None, min_length=1, max_length=255)
    pw_hash: str = Field(default="", min_length=0, max_length=255)
    preferred_language: str = Field(default="en", max_length=8)


class ConsentCreate(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"guardian_id": 1, "purpose": "store_child"}]})

    guardian_id: int
    purpose: str = Field(min_length=1, max_length=100)


class ChildCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "dob": "2026-01-01",
                    "sex": "female",
                    "village_id": 1,
                    "guardian_id": 3,
                    "asha_id": 1,
                    "opt_in_sms": True,
                    "opt_in_ivr": False,
                    "opt_in_app": True,
                }
            ]
        }
    )

    dob: date
    sex: Sex
    village_id: int
    guardian_id: int
    asha_id: int
    opt_in_sms: bool = False
    opt_in_ivr: bool = False
    opt_in_app: bool = True


class SyncChildUpdate(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"id": 1, "client_updated_at": "2026-01-03T10:00:00", "opt_in_sms": True}]})

    id: int
    client_updated_at: datetime
    opt_in_sms: Optional[bool] = None
    opt_in_ivr: Optional[bool] = None
    opt_in_app: Optional[bool] = None


class SyncDoseIn(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "client_uuid": "offline-dose-001",
                    "child_id": 1,
                    "vaccine_code": "BCG",
                    "given_on": "2026-01-01",
                    "batch_no": "BCG-2026-01",
                    "source": "app",
                    "client_updated_at": "2026-01-03T10:00:00",
                }
            ]
        }
    )

    client_uuid: str = Field(min_length=1, max_length=80)
    child_id: int
    vaccine_code: str = Field(min_length=1, max_length=40)
    given_on: date
    batch_no: Optional[str] = None
    session_id: Optional[int] = None
    source: str = "app"
    client_updated_at: datetime


class SyncPush(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "children": [{"id": 1, "client_updated_at": "2026-01-03T10:00:00", "opt_in_sms": True}],
                    "doses": [
                        {
                            "client_uuid": "offline-dose-001",
                            "child_id": 1,
                            "vaccine_code": "BCG",
                            "given_on": "2026-01-01",
                            "source": "app",
                            "client_updated_at": "2026-01-03T10:00:00",
                        }
                    ],
                }
            ]
        }
    )

    children: List[SyncChildUpdate] = []
    doses: List[SyncDoseIn] = []


class SimInbound(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"phone": "+919000000101", "message": "STOP"}]})

    phone: str
    message: str


class GrievanceCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "child_id": 1,
                    "category": "consent",
                    "message": "Please help me understand how to withdraw SMS reminders.",
                    "contact_preference": "asha",
                }
            ]
        }
    )

    child_id: Optional[int] = None
    category: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=2000)
    contact_preference: str = Field(default="asha", max_length=40)


class ErrorResponse(BaseModel):
    code: str
    message: str
    details: dict[str, object] = Field(default_factory=dict)
    request_id: str
