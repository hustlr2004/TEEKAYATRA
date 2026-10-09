from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Child, Role, User, Village
from app.services.crypto import decrypt_phone
from tests.factories import ChildFactory, ConsentFactory, UserFactory, VillageFactory


def test_factories_create_persistable_domain_models() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    with session_factory() as db:
        village = VillageFactory(id=1)
        guardian = UserFactory(id=1, role=Role.caregiver, village_id=1)
        asha = UserFactory(id=2, role=Role.asha, village_id=1)
        child = ChildFactory(id=1, village_id=1, guardian_id=1, asha_id=2)
        consent = ConsentFactory(guardian_id=1)
        db.add_all([village, guardian, asha, consent, child])
        db.commit()

        saved_child = db.scalar(select(Child).where(Child.id == 1))
        saved_guardian = db.scalar(select(User).where(User.id == 1))
        saved_village = db.scalar(select(Village).where(Village.id == 1))

        assert saved_child is not None
        assert saved_guardian is not None
        assert saved_village is not None
        assert saved_child.guardian_id == saved_guardian.id
        assert saved_village.block.startswith("Block")
        assert decrypt_phone(saved_guardian.phone).startswith("+9198000")
