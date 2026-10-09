from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from ..models import Role, Sex


class LoginRequest(BaseModel):
    phone: str = Field(min_length=6, max_length=20)
    password: str = Field(min_length=1, max_length=255)


class UserCreate(BaseModel):
    role: Role
    name: str = Field(min_length=1, max_length=100)
    phone: str = Field(min_length=6, max_length=20)
    village_id: Optional[int] = None
    password: Optional[str] = Field(default=None, min_length=1, max_length=255)
    pw_hash: str = Field(default="", min_length=0, max_length=255)
    preferred_language: str = Field(default="en", max_length=8)


class ConsentCreate(BaseModel):
    guardian_id: int
    purpose: str = Field(min_length=1, max_length=100)


class ChildCreate(BaseModel):
    dob: date
    sex: Sex
    village_id: int
    guardian_id: int
    asha_id: int
    opt_in_sms: bool = False
    opt_in_ivr: bool = False
    opt_in_app: bool = True


class SyncChildUpdate(BaseModel):
    id: int
    client_updated_at: datetime
    opt_in_sms: Optional[bool] = None
    opt_in_ivr: Optional[bool] = None
    opt_in_app: Optional[bool] = None


class SyncDoseIn(BaseModel):
    client_uuid: str = Field(min_length=1, max_length=80)
    child_id: int
    vaccine_code: str = Field(min_length=1, max_length=40)
    given_on: date
    batch_no: Optional[str] = None
    session_id: Optional[int] = None
    source: str = "app"
    client_updated_at: datetime


class SyncPush(BaseModel):
    children: List[SyncChildUpdate] = []
    doses: List[SyncDoseIn] = []


class SimInbound(BaseModel):
    phone: str
    message: str


class GrievanceCreate(BaseModel):
    child_id: Optional[int] = None
    category: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=2000)
    contact_preference: str = Field(default="asha", max_length=40)
