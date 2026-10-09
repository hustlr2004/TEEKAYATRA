from __future__ import annotations

from datetime import date, datetime

import factory

from app.models import Child, Consent, Dose, DoseSource, Role, Sex, User, Village
from app.services.crypto import encrypt_phone


class VillageFactory(factory.Factory):
    class Meta:
        model = Village

    block = factory.Sequence(lambda index: "Block %s" % index)
    district = "Patna"


class UserFactory(factory.Factory):
    class Meta:
        model = User

    role = Role.caregiver
    name = factory.Sequence(lambda index: "User %s" % index)
    phone = factory.Sequence(lambda index: encrypt_phone("+9198000%05d" % index))
    village_id = None
    pw_hash = "hash"
    preferred_language = "en"


class ConsentFactory(factory.Factory):
    class Meta:
        model = Consent

    guardian_id = 1
    purpose = "store_child"
    granted_at = factory.LazyFunction(datetime.utcnow)
    withdrawn_at = None


class ChildFactory(factory.Factory):
    class Meta:
        model = Child

    dob = date(2026, 1, 1)
    sex = Sex.female
    village_id = 1
    guardian_id = 1
    asha_id = 2
    opt_in_sms = True
    opt_in_ivr = False
    opt_in_app = True


class DoseFactory(factory.Factory):
    class Meta:
        model = Dose

    child_id = 1
    vaccine_code = "BCG"
    given_on = date(2026, 1, 1)
    batch_no = "BATCH-001"
    session_id = None
    recorded_by = 2
    source = DoseSource.app
    synced_at = factory.LazyFunction(datetime.utcnow)
    client_uuid = factory.Sequence(lambda index: "factory-dose-%s" % index)
    client_updated_at = factory.LazyFunction(datetime.utcnow)
