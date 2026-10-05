from __future__ import annotations

import os
from dataclasses import asdict
from datetime import date, datetime
from time import time
from typing import Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .database import Base, engine, get_db
from .models import Child, Consent, Dose, Grievance, NotificationLog, Role, Sex, User, VaccineSchedule, Village
from .services.audit import audit_child_access
from .services.analytics import manager_dashboard, simulated_external_register_csv
from .services.auth import create_access_token, current_user, hash_password, require_role, verify_password
from .services.cards import vaccination_card_pdf
from .services.crypto import decrypt_phone, encrypt_phone, masked_phone
from .services.gamification import child_progress as gamified_child_progress
from .services.gamification import village_leaderboard as gamified_village_leaderboard
from .services.notifications import process_inbound_message
from .services.responsible_design import caregiver_export, delete_caregiver_data, run_retention_job
from .services.schedule import due_doses, next_visit, overdue_doses, schedule_windows


Base.metadata.create_all(bind=engine)

app = FastAPI(title="Teeka Yatra API", version="0.1.0")

allowed_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://localhost:5173",
    "https://127.0.0.1:5173",
]
configured_origins = os.getenv("ALLOWED_ORIGINS")
if configured_origins:
    allowed_origins.extend(origin.strip() for origin in configured_origins.split(",") if origin.strip())

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_MAX_REQUESTS = 120
_rate_limit_buckets: Dict[str, List[float]] = {}


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


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    if request.url.path == "/health":
        return await call_next(request)
    client = request.client.host if request.client is not None else "unknown"
    key = "%s:%s" % (client, request.url.path)
    now = time()
    bucket = [stamp for stamp in _rate_limit_buckets.get(key, []) if now - stamp < RATE_LIMIT_WINDOW_SECONDS]
    if len(bucket) >= RATE_LIMIT_MAX_REQUESTS:
        return Response(content='{"detail":"Rate limit exceeded"}', status_code=429, media_type="application/json")
    bucket.append(now)
    _rate_limit_buckets[key] = bucket
    return await call_next(request)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/auth/token")
def auth_token(user_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return {"access_token": create_access_token(user), "token_type": "bearer"}


@app.post("/auth/login")
def auth_login(payload: LoginRequest, db: Session = Depends(get_db)) -> dict[str, str]:
    user = None
    for candidate in db.scalars(select(User)).all():
        if decrypt_phone(candidate.phone) == payload.phone:
            user = candidate
            break
    if user is None or not verify_password(payload.password, user.pw_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid phone or password")
    return {"access_token": create_access_token(user), "token_type": "bearer"}


@app.post("/users", status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, actor: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, object]:
    require_role(actor, Role.admin)
    password_hash = payload.pw_hash or (hash_password(payload.password) if payload.password else "")
    if not password_hash:
        raise HTTPException(status_code=400, detail="Password is required")
    user = User(
        role=payload.role,
        name=payload.name,
        phone=encrypt_phone(payload.phone),
        village_id=payload.village_id,
        pw_hash=password_hash,
        preferred_language=payload.preferred_language,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user_public(user, include_phone=True)


@app.get("/users")
def list_users(actor: User = Depends(current_user), db: Session = Depends(get_db)) -> List[dict[str, object]]:
    require_role(actor, Role.admin)
    users = db.scalars(select(User).order_by(User.id)).all()
    return [user_public(user, include_phone=True) for user in users]


@app.get("/villages")
def list_villages(actor: User = Depends(current_user), db: Session = Depends(get_db)) -> List[dict[str, object]]:
    villages = db.scalars(select(Village).order_by(Village.district, Village.block)).all()
    return [{"id": village.id, "block": village.block, "district": village.district} for village in villages]


@app.get("/schedule")
def list_schedule(actor: User = Depends(current_user), db: Session = Depends(get_db)) -> List[dict[str, object]]:
    rows = db.scalars(select(VaccineSchedule).order_by(VaccineSchedule.age_due_days, VaccineSchedule.vaccine_code)).all()
    return [
        {
            "vaccine_code": row.vaccine_code,
            "name": row.name,
            "age_due_days": row.age_due_days,
            "window_days": row.window_days,
            "endemic_only": row.endemic_only,
        }
        for row in rows
    ]


@app.get("/demo-summary")
def demo_summary(actor: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, int]:
    return {
        "villages": db.scalar(select(func.count()).select_from(Village)) or 0,
        "users": db.scalar(select(func.count()).select_from(User)) or 0,
        "children": db.scalar(select(func.count()).select_from(Child)) or 0,
        "doses": db.scalar(select(func.count()).select_from(Dose)) or 0,
    }


@app.post("/consents", status_code=status.HTTP_201_CREATED)
def capture_consent(payload: ConsentCreate, actor: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, object]:
    if actor.role == Role.caregiver and actor.id != payload.guardian_id:
        raise HTTPException(status_code=403, detail="Caregiver can consent only for self")
    if actor.role not in {Role.caregiver, Role.admin}:
        raise HTTPException(status_code=403, detail="Only guardian or admin can capture consent")
    consent = Consent(guardian_id=payload.guardian_id, purpose=payload.purpose, granted_at=datetime.utcnow())
    db.add(consent)
    db.commit()
    db.refresh(consent)
    return {"id": consent.id, "guardian_id": consent.guardian_id, "purpose": consent.purpose, "granted_at": consent.granted_at}


@app.post("/consents/{consent_id}/withdraw")
def withdraw_consent(consent_id: int, actor: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, object]:
    consent = db.get(Consent, consent_id)
    if consent is None:
        raise HTTPException(status_code=404, detail="Consent not found")
    if actor.role == Role.caregiver and actor.id != consent.guardian_id:
        raise HTTPException(status_code=403, detail="Caregiver can withdraw only own consent")
    if actor.role not in {Role.caregiver, Role.admin}:
        raise HTTPException(status_code=403, detail="Only guardian or admin can withdraw consent")
    consent.withdrawn_at = datetime.utcnow()
    db.commit()
    return {"id": consent.id, "withdrawn_at": consent.withdrawn_at}


@app.post("/children", status_code=status.HTTP_201_CREATED)
def create_child(payload: ChildCreate, actor: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, object]:
    if actor.role == Role.caregiver and actor.id != payload.guardian_id:
        raise HTTPException(status_code=403, detail="Caregiver can store only own child")
    if actor.role == Role.asha and actor.village_id != payload.village_id:
        raise HTTPException(status_code=403, detail="ASHA can store children only in assigned village")
    if actor.role == Role.manager:
        raise HTTPException(status_code=403, detail="Managers cannot store child records")
    if not active_guardian_consent(db, payload.guardian_id, "store_child"):
        raise HTTPException(status_code=400, detail="Guardian consent required before storing child")

    child = Child(**payload.model_dump())
    db.add(child)
    db.flush()
    audit_child_access(db, actor.id, "write", child.id, "store child with guardian consent")
    db.commit()
    db.refresh(child)
    return child_public(child)


@app.get("/children")
def list_children(actor: User = Depends(current_user), db: Session = Depends(get_db)) -> List[dict[str, object]]:
    if actor.role == Role.manager:
        return aggregated_children(db)
    query = select(Child).order_by(Child.id)
    if actor.role == Role.caregiver:
        query = query.where(Child.guardian_id == actor.id)
    elif actor.role == Role.asha:
        query = query.where(Child.village_id == actor.village_id)
    children = db.scalars(query).all()
    for child in children:
        audit_child_access(db, actor.id, "read", child.id, "list children")
    db.commit()
    return [child_public(child) for child in children]


@app.get("/children/card-template.pdf")
def blank_card_template_pdf(actor: User = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    if actor.role == Role.manager:
        raise HTTPException(status_code=403, detail="Managers cannot print child-level cards")
    content = vaccination_card_pdf(db, None)
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": "inline; filename=teeka-yatra-blank-card.pdf"},
    )


@app.get("/children/{child_id}")
def get_child(child_id: int, actor: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, object]:
    child = accessible_child(db, child_id, actor)
    audit_child_access(db, actor.id, "read", child.id, "read child")
    db.commit()
    return child_public(child)


@app.get("/children/{child_id}/schedule")
def child_schedule(child_id: int, actor: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, object]:
    child = accessible_child(db, child_id, actor)
    audit_child_access(db, actor.id, "read", child.id, "read child schedule")
    current_day = date.today()
    db.commit()
    return {
        "child_id": child.id,
        "as_of": current_day.isoformat(),
        "schedule": [asdict(window) for window in schedule_windows(child, current_day)],
        "due": [asdict(window) for window in due_doses(child, current_day)],
        "overdue": [asdict(window) for window in overdue_doses(child, current_day)],
        "next_visit": asdict(next_visit(child)),
    }


@app.get("/children/{child_id}/progress")
def child_progress(child_id: int, actor: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, object]:
    child = accessible_child(db, child_id, actor)
    audit_child_access(db, actor.id, "read", child.id, "read child progress")
    result = asdict(gamified_child_progress(db, child))
    db.commit()
    return result


@app.get("/children/{child_id}/card.pdf")
def child_card_pdf(child_id: int, actor: User = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    child = accessible_child(db, child_id, actor)
    audit_child_access(db, actor.id, "read", child.id, "print vaccination card")
    content = vaccination_card_pdf(db, child)
    db.commit()
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": "inline; filename=teeka-yatra-child-%s-card.pdf" % child.id},
    )


@app.delete("/me/data")
def delete_my_data(actor: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, object]:
    require_role(actor, Role.caregiver)
    child_ids = delete_caregiver_data(db, actor)
    db.commit()
    return {"deleted_child_ids": child_ids}


@app.get("/me/data/export")
def export_my_data(actor: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, object]:
    require_role(actor, Role.caregiver)
    payload = caregiver_export(db, actor)
    db.commit()
    return payload


@app.post("/grievances", status_code=status.HTTP_201_CREATED)
def create_grievance(payload: GrievanceCreate, actor: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, object]:
    guardian_id: Optional[int] = None
    if actor.role == Role.caregiver:
        guardian_id = actor.id
        if payload.child_id is not None:
            accessible_child(db, payload.child_id, actor)
    elif actor.role == Role.asha and payload.child_id is not None:
        accessible_child(db, payload.child_id, actor)
    elif actor.role == Role.manager:
        raise HTTPException(status_code=403, detail="Managers cannot file individual grievances")
    grievance = Grievance(
        guardian_id=guardian_id,
        child_id=payload.child_id,
        category=payload.category,
        message=payload.message,
        contact_preference=payload.contact_preference,
    )
    db.add(grievance)
    db.commit()
    db.refresh(grievance)
    return grievance_public(grievance)


@app.get("/grievances")
def list_grievances(actor: User = Depends(current_user), db: Session = Depends(get_db)) -> List[dict[str, object]]:
    require_role(actor, Role.admin)
    return [grievance_public(row) for row in db.scalars(select(Grievance).order_by(Grievance.id)).all()]


@app.post("/jobs/data-retention")
def data_retention_job(actor: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, int]:
    require_role(actor, Role.admin)
    return asdict(run_retention_job(db, date.today()))


@app.get("/leaderboard/village")
def village_leaderboard(actor: User = Depends(current_user), db: Session = Depends(get_db)) -> List[dict[str, object]]:
    if actor.role == Role.caregiver:
        raise HTTPException(status_code=403, detail="Caregivers cannot view leaderboards")
    return [asdict(row) for row in gamified_village_leaderboard(db)]


@app.get("/analytics/manager")
def manager_analytics(actor: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, object]:
    require_role(actor, Role.manager, Role.admin)
    return manager_dashboard(db, date.today(), simulated_external_register_csv())


@app.get("/sim", response_class=HTMLResponse)
def feature_phone_sim(db: Session = Depends(get_db)) -> str:
    messages = db.scalars(select(NotificationLog).order_by(NotificationLog.sent_at.desc(), NotificationLog.id.desc()).limit(30)).all()
    items = "\n".join(
        [
            "<li><span>%s</span><b>%s</b><p>%s</p></li>"
            % (log.channel.value.upper(), log.sent_at.strftime("%d %b %H:%M"), _escape_html(log.message))
            for log in messages
        ]
    )
    if not items:
        items = "<li><span>SMS</span><b>No messages yet</b><p>Run the reminder scheduler to populate this inbox.</p></li>"
    return """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Teeka Yatra Feature Phone Sim</title>
  <style>
    body { margin: 0; min-height: 100vh; display: grid; place-items: center; background: #f6f7ef; font-family: Arial, sans-serif; color: #17231d; }
    main { width: min(360px, 92vw); border: 12px solid #27312b; border-radius: 28px; background: #dce8d4; box-shadow: 0 22px 60px rgba(0,0,0,.22); overflow: hidden; }
    header { background: #17231d; color: #fff; padding: 14px 18px; display: flex; justify-content: space-between; font-weight: 700; }
    ol { list-style: none; padding: 12px; margin: 0; display: grid; gap: 10px; max-height: 560px; overflow: auto; }
    li { background: #fbfff7; border: 2px solid #91a488; border-radius: 8px; padding: 10px; }
    span { display: inline-block; background: #0f766e; color: white; border-radius: 4px; padding: 2px 6px; font-size: 12px; margin-right: 6px; }
    b { font-size: 13px; }
    p { margin: 8px 0 0; line-height: 1.35; font-size: 15px; }
    form { display: grid; gap: 8px; padding: 12px; border-top: 2px solid #91a488; background: #eef6e8; }
    input, button { min-height: 42px; font-size: 16px; border-radius: 6px; border: 1px solid #5d6f60; padding: 0 10px; }
    button { background: #14532d; color: white; font-weight: 700; }
  </style>
</head>
<body>
  <main>
    <header><div>Inbox</div><div>Teeka Yatra</div></header>
    <ol>%s</ol>
    <form method="get" action="/sim/inbound">
      <input name="phone" placeholder="+91 caregiver phone" aria-label="Caregiver phone" />
      <input name="message" value="STOP" aria-label="Inbound message" />
      <button type="submit">Send inbound SMS</button>
    </form>
  </main>
</body>
</html>
""" % items


@app.post("/sim/inbound")
def sim_inbound(payload: SimInbound, db: Session = Depends(get_db)) -> dict[str, object]:
    return {"processed": process_inbound_message(db, payload.phone, payload.message)}


@app.get("/sim/inbound")
def sim_inbound_query(phone: str, message: str = "STOP", db: Session = Depends(get_db)) -> HTMLResponse:
    processed = process_inbound_message(db, phone, message)
    status_text = "STOP processed" if processed else "No matching opt-out was processed"
    return HTMLResponse(
        "<!doctype html><title>Teeka Yatra Sim</title><p>%s.</p><p><a href='/sim'>Back to inbox</a></p>"
        % _escape_html(status_text)
    )


@app.post("/sync/push")
def sync_push(payload: SyncPush, actor: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, object]:
    if actor.role not in {Role.asha, Role.admin}:
        raise HTTPException(status_code=403, detail="Only ASHAs and admins can push offline sync batches")
    accepted: List[str] = []
    duplicates: List[str] = []
    conflicts: List[dict[str, object]] = []

    for child_update in payload.children:
        child = accessible_child(db, child_update.id, actor)
        audit_child_access(db, actor.id, "write", child.id, "sync child update")
        if child.client_updated_at is None or child_update.client_updated_at >= child.client_updated_at:
            if child_update.opt_in_sms is not None:
                child.opt_in_sms = child_update.opt_in_sms
            if child_update.opt_in_ivr is not None:
                child.opt_in_ivr = child_update.opt_in_ivr
            if child_update.opt_in_app is not None:
                child.opt_in_app = child_update.opt_in_app
            child.client_updated_at = child_update.client_updated_at
        else:
            child.conflict_flag = True
            conflicts.append({"type": "child_out_of_order", "child_id": child.id})

    for incoming in payload.doses:
        child = accessible_child(db, incoming.child_id, actor)
        existing_uuid = db.scalar(select(Dose).where(Dose.client_uuid == incoming.client_uuid))
        if existing_uuid is not None:
            duplicates.append(incoming.client_uuid)
            continue
        existing_dose = db.scalar(
            select(Dose).where(
                Dose.child_id == incoming.child_id,
                Dose.vaccine_code == incoming.vaccine_code,
            )
        )
        if existing_dose is not None:
            existing_dose.conflict_flag = True
            conflicts.append(
                {
                    "type": "dose_conflict",
                    "client_uuid": incoming.client_uuid,
                    "child_id": incoming.child_id,
                    "vaccine_code": incoming.vaccine_code,
                }
            )
            continue
        dose = Dose(
            child_id=incoming.child_id,
            vaccine_code=incoming.vaccine_code,
            given_on=incoming.given_on,
            batch_no=incoming.batch_no,
            session_id=incoming.session_id,
            recorded_by=actor.id,
            source=incoming.source,
            synced_at=datetime.utcnow(),
            client_uuid=incoming.client_uuid,
            client_updated_at=incoming.client_updated_at,
        )
        db.add(dose)
        audit_child_access(db, actor.id, "write", child.id, "sync dose")
        accepted.append(incoming.client_uuid)

    db.commit()
    return {"accepted": accepted, "duplicates": duplicates, "conflicts": conflicts}


@app.get("/sync/pull")
def sync_pull(since: Optional[datetime] = None, actor: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, object]:
    if actor.role == Role.manager:
        return {"children": aggregated_children(db), "doses": [], "conflicts": []}
    child_query = select(Child).order_by(Child.id)
    if actor.role == Role.caregiver:
        child_query = child_query.where(Child.guardian_id == actor.id)
    elif actor.role == Role.asha:
        child_query = child_query.where(Child.village_id == actor.village_id)
    children = db.scalars(child_query).all()
    child_ids = [child.id for child in children]
    dose_query = select(Dose).where(Dose.child_id.in_(child_ids)).order_by(Dose.id)
    if since is not None:
        dose_query = dose_query.where(Dose.synced_at.is_not(None), Dose.synced_at >= since)
    doses = db.scalars(dose_query).all()
    for child in children:
        audit_child_access(db, actor.id, "read", child.id, "sync pull")
    db.commit()
    return {
        "children": [child_public(child) | {"client_updated_at": child.client_updated_at, "conflict_flag": child.conflict_flag} for child in children],
        "doses": [dose_public(dose) for dose in doses],
        "conflicts": conflict_rows(children, doses),
        "server_time": datetime.utcnow().isoformat(),
    }


def accessible_child(db: Session, child_id: int, actor: User) -> Child:
    child = db.get(Child, child_id)
    if child is None:
        raise HTTPException(status_code=404, detail="Child not found")
    if actor.role == Role.caregiver and child.guardian_id != actor.id:
        raise HTTPException(status_code=403, detail="Child not accessible")
    if actor.role == Role.asha and child.village_id != actor.village_id:
        raise HTTPException(status_code=403, detail="Child not in assigned village")
    if actor.role == Role.manager:
        raise HTTPException(status_code=403, detail="Managers can view aggregated data only")
    return child


def active_guardian_consent(db: Session, guardian_id: int, purpose: str) -> bool:
    consent = db.scalar(
        select(Consent).where(
            Consent.guardian_id == guardian_id,
            Consent.purpose == purpose,
            Consent.withdrawn_at.is_(None),
        )
    )
    return consent is not None


def child_public(child: Child) -> dict[str, object]:
    return {
        "id": child.id,
        "dob": child.dob,
        "sex": child.sex.value,
        "village_id": child.village_id,
        "guardian_id": child.guardian_id,
        "asha_id": child.asha_id,
        "opt_in_sms": child.opt_in_sms,
        "opt_in_ivr": child.opt_in_ivr,
        "opt_in_app": child.opt_in_app,
    }


def dose_public(dose: Dose) -> dict[str, object]:
    return {
        "id": dose.id,
        "client_uuid": dose.client_uuid,
        "child_id": dose.child_id,
        "vaccine_code": dose.vaccine_code,
        "given_on": dose.given_on,
        "batch_no": dose.batch_no,
        "session_id": dose.session_id,
        "source": dose.source.value,
        "synced_at": dose.synced_at,
        "client_updated_at": dose.client_updated_at,
        "conflict_flag": dose.conflict_flag,
    }


def conflict_rows(children: List[Child], doses: List[Dose]) -> List[dict[str, object]]:
    rows: List[dict[str, object]] = []
    for child in children:
        if child.conflict_flag:
            rows.append({"type": "child", "child_id": child.id})
    for dose in doses:
        if dose.conflict_flag:
            rows.append({"type": "dose", "dose_id": dose.id, "child_id": dose.child_id})
    return rows


def user_public(user: User, include_phone: bool) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": user.id,
        "role": user.role.value,
        "name": user.name,
        "village_id": user.village_id,
        "preferred_language": user.preferred_language,
    }
    if include_phone:
        payload["phone"] = masked_phone(user.phone)
    return payload


def grievance_public(grievance: Grievance) -> dict[str, object]:
    return {
        "id": grievance.id,
        "guardian_id": grievance.guardian_id,
        "child_id": grievance.child_id,
        "category": grievance.category,
        "message": grievance.message,
        "contact_preference": grievance.contact_preference,
        "status": grievance.status,
        "created_at": grievance.created_at,
    }


def aggregated_children(db: Session) -> List[dict[str, object]]:
    rows = db.execute(
        select(Village.id, Village.block, Village.district, func.count(Child.id))
        .join(Child, Child.village_id == Village.id, isouter=True)
        .group_by(Village.id, Village.block, Village.district)
        .order_by(Village.district, Village.block)
    ).all()
    return [
        {
            "village_id": village_id,
            "block": block,
            "district": district,
            "children_count": count,
        }
        for village_id, block, district, count in rows
    ]


def _escape_html(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
