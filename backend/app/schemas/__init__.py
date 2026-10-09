from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from ..models import DoseSource, EntityType, Role, Sex


class VillageRead(BaseModel):
    id: int
    block: str
    district: str
    model_config = ConfigDict(from_attributes=True)


class UserRead(BaseModel):
    id: int
    role: Role
    name: str
    phone: str
    village_id: Optional[int]
    model_config = ConfigDict(from_attributes=True)


class ChildRead(BaseModel):
    id: int
    dob: date
    sex: Sex
    village_id: int
    guardian_id: int
    asha_id: int
    opt_in_sms: bool
    opt_in_ivr: bool
    opt_in_app: bool
    model_config = ConfigDict(from_attributes=True)


class DoseRead(BaseModel):
    id: int
    child_id: int
    vaccine_code: str
    given_on: date
    batch_no: Optional[str]
    session_id: Optional[int]
    recorded_by: int
    source: DoseSource
    synced_at: Optional[datetime]
    model_config = ConfigDict(from_attributes=True)


class PointsRead(BaseModel):
    entity_type: EntityType
    entity_id: int
    points: int
    reason: str
    ts: datetime
    model_config = ConfigDict(from_attributes=True)
