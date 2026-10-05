from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Optional, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Child, Consent, NotificationChannel, NotificationLog, NotificationOptOut, User
from .crypto import decrypt_phone
from .schedule import DoseWindow, schedule_windows


SMS_TEMPLATES = {
    "en": {
        "seven_day": "Teeka Yatra: {child} is due for {vaccine} on {due_on}. Please visit your nearest session.",
        "one_day": "Teeka Yatra: {child}'s {vaccine} is due tomorrow, {due_on}. Your ASHA can help.",
        "missed": "Teeka Yatra: {child} missed {vaccine}. There is no penalty. Please plan a catch-up visit.",
    },
    "hi": {
        "seven_day": "Teeka Yatra: {child} ka {vaccine} tika {due_on} ko hai. Kripya najdik ke session par jayein.",
        "one_day": "Teeka Yatra: {child} ka {vaccine} tika kal, {due_on}, hai. ASHA madad kar sakti hain.",
        "missed": "Teeka Yatra: {child} ka {vaccine} tika chhut gaya hai. Koi jurmana nahi. Catch-up visit karein.",
    },
    "pa": {
        "seven_day": "Teeka Yatra: {child} da {vaccine} tika {due_on} nu hai. Kirpa karke najdeeki session te jao.",
        "one_day": "Teeka Yatra: {child} da {vaccine} tika kal, {due_on}, hai. ASHA madad kar sakdi hai.",
        "missed": "Teeka Yatra: {child} da {vaccine} tika reh gaya hai. Koi jurmana nahi. Catch-up visit karo.",
    },
}

IVR_TEMPLATES = {
    "en": "Hello {guardian}. This is Teeka Yatra. {child} needs {vaccine}. Due date: {due_on}. Please visit the nearest immunization session. You can say repeat to hear this again.",
    "hi": "Namaste {guardian}. Yeh Teeka Yatra se sandesh hai. {child} ko {vaccine} tika chahiye. Tareekh: {due_on}. Kripya najdik ke tika session par jayein. Dobara sunne ke liye repeat bolen.",
    "pa": "Sat sri akal {guardian}. Eh Teeka Yatra da sandesh hai. {child} nu {vaccine} tika chahida hai. Tareekh: {due_on}. Kirpa karke najdeeki session te jao. Dobara sunan lai repeat kaho.",
}


@dataclass(frozen=True)
class Reminder:
    child: Child
    window: DoseWindow
    reminder_type: str
    scheduled_for: date


class NotificationGateway(Protocol):
    def send_sms(self, guardian: User, child: Child, reminder: Reminder, message: str) -> bool:
        ...

    def send_ivr(self, guardian: User, child: Child, reminder: Reminder, script: str) -> bool:
        ...


class MockDbNotificationGateway:
    def __init__(self, db: Session) -> None:
        self.db = db

    def send_sms(self, guardian: User, child: Child, reminder: Reminder, message: str) -> bool:
        return self._log(NotificationChannel.sms, guardian, child, reminder, message)

    def send_ivr(self, guardian: User, child: Child, reminder: Reminder, script: str) -> bool:
        return self._log(NotificationChannel.ivr, guardian, child, reminder, script)

    def _log(self, channel: NotificationChannel, guardian: User, child: Child, reminder: Reminder, message: str) -> bool:
        existing = self.db.scalar(
            select(NotificationLog.id).where(
                NotificationLog.guardian_id == guardian.id,
                NotificationLog.child_id == child.id,
                NotificationLog.channel == channel,
                NotificationLog.reminder_type == reminder.reminder_type,
                NotificationLog.vaccine_code == reminder.window.vaccine_code,
                NotificationLog.scheduled_for == reminder.scheduled_for,
            )
        )
        if existing is not None:
            return False
        self.db.add(
            NotificationLog(
                guardian_id=guardian.id,
                child_id=child.id,
                channel=channel,
                reminder_type=reminder.reminder_type,
                vaccine_code=reminder.window.vaccine_code,
                language=_language_for(guardian),
                recipient_phone=guardian.phone,
                message=message,
                status="logged",
                scheduled_for=reminder.scheduled_for,
            )
        )
        self.db.flush()
        return True


def schedule_reminders(db: Session, today: date, gateway: Optional[NotificationGateway] = None) -> List[NotificationLog]:
    gateway = gateway or MockDbNotificationGateway(db)
    before_ids = set(db.scalars(select(NotificationLog.id)).all())
    children = db.scalars(select(Child).order_by(Child.id)).all()
    for child in children:
        for reminder in reminders_for_child(child, today):
            guardian = child.guardian
            if child.opt_in_sms and can_contact(db, guardian.id, NotificationChannel.sms):
                gateway.send_sms(guardian, child, reminder, sms_message(guardian, child, reminder))
            if child.opt_in_ivr and can_contact(db, guardian.id, NotificationChannel.ivr):
                gateway.send_ivr(guardian, child, reminder, ivr_script(guardian, child, reminder))
    db.commit()
    return list(db.scalars(select(NotificationLog).where(NotificationLog.id.not_in(before_ids)).order_by(NotificationLog.id)).all())


def reminders_for_child(child: Child, today: date) -> List[Reminder]:
    reminders: List[Reminder] = []
    for window in schedule_windows(child, today):
        if window.given_on is not None:
            continue
        days_until_due = (window.due_on - today).days
        if days_until_due == 7:
            reminders.append(Reminder(child=child, window=window, reminder_type="seven_day", scheduled_for=today))
        elif days_until_due == 1:
            reminders.append(Reminder(child=child, window=window, reminder_type="one_day", scheduled_for=today))
        elif today > window.due_until:
            reminders.append(Reminder(child=child, window=window, reminder_type="missed", scheduled_for=today))
    return reminders


def sms_message(guardian: User, child: Child, reminder: Reminder) -> str:
    language = _language_for(guardian)
    template = SMS_TEMPLATES.get(language, SMS_TEMPLATES["en"])[reminder.reminder_type]
    return template.format(
        child="Child %s" % child.id,
        vaccine=reminder.window.name,
        due_on=reminder.window.due_on.isoformat(),
    )


def ivr_script(guardian: User, child: Child, reminder: Reminder) -> str:
    language = _language_for(guardian)
    template = IVR_TEMPLATES.get(language, IVR_TEMPLATES["en"])
    return template.format(
        guardian=guardian.name,
        child="Child %s" % child.id,
        vaccine=reminder.window.name,
        due_on=reminder.window.due_on.isoformat(),
    )


def can_contact(db: Session, guardian_id: int, channel: NotificationChannel) -> bool:
    if has_opted_out(db, guardian_id, channel):
        return False
    purpose = "sms_reminders" if channel == NotificationChannel.sms else "ivr_reminders"
    consent = db.scalar(
        select(Consent).where(
            Consent.guardian_id == guardian_id,
            Consent.purpose == purpose,
            Consent.withdrawn_at.is_(None),
        )
    )
    return consent is not None


def process_inbound_message(db: Session, phone: str, message: str) -> bool:
    if message.strip().upper() != "STOP":
        return False
    guardian = find_user_by_phone(db, phone)
    if guardian is None:
        return False
    register_opt_out(db, guardian.id, NotificationChannel.sms, "STOP")
    for child in guardian.guardian_children:
        child.opt_in_sms = False
    db.commit()
    return True


def register_opt_out(db: Session, guardian_id: int, channel: NotificationChannel, reason: str) -> NotificationOptOut:
    opt_out = db.scalar(
        select(NotificationOptOut).where(
            NotificationOptOut.guardian_id == guardian_id,
            NotificationOptOut.channel == channel,
        )
    )
    if opt_out is not None:
        opt_out.reason = reason
        opt_out.opted_out_at = datetime.utcnow()
        return opt_out
    opt_out = NotificationOptOut(guardian_id=guardian_id, channel=channel, reason=reason)
    db.add(opt_out)
    purpose = "sms_reminders" if channel == NotificationChannel.sms else "ivr_reminders"
    for consent in db.scalars(
        select(Consent).where(
            Consent.guardian_id == guardian_id,
            Consent.purpose == purpose,
            Consent.withdrawn_at.is_(None),
        )
    ):
        consent.withdrawn_at = datetime.utcnow()
    return opt_out


def has_opted_out(db: Session, guardian_id: int, channel: NotificationChannel) -> bool:
    return (
        db.scalar(
            select(NotificationOptOut.id).where(
                NotificationOptOut.guardian_id == guardian_id,
                NotificationOptOut.channel == channel,
            )
        )
        is not None
    )


def find_user_by_phone(db: Session, phone: str) -> Optional[User]:
    for user in db.scalars(select(User)).all():
        try:
            if decrypt_phone(user.phone) == phone:
                return user
        except ValueError:
            if user.phone == phone:
                return user
    return None


def _language_for(guardian: User) -> str:
    return guardian.preferred_language if guardian.preferred_language in SMS_TEMPLATES else "en"
