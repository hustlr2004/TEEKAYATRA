# Teeka Yatra Architecture

Teeka Yatra is a privacy-preserving, offline-first immunization platform for caregivers, ASHAs, programme managers, and admins. The backend is FastAPI with SQLAlchemy and Alembic, PostgreSQL in production, SQLite in tests, Redis for cache/job coordination, and an internal outbox-backed event bus.

## System View

```mermaid
flowchart LR
  Caregiver[Caregiver PWA] --> API[FastAPI /api/v1]
  ASHA[ASHA PWA offline queue] --> API
  Manager[Manager dashboard] --> API
  FeaturePhone[SMS/IVR feature phone] --> Notifications[Notification service]
  API --> DB[(PostgreSQL)]
  API --> Redis[(Redis cache/queues)]
  Worker[Background worker] --> DB
  Worker --> Redis
  API --> Events[Outbox event bus]
  Events --> Worker
  Worker --> Notifications
  Notifications --> DB
```

## Event Flow

```mermaid
sequenceDiagram
  participant A as ASHA app
  participant API as Sync API
  participant DB as PostgreSQL
  participant O as Outbox
  participant W as Worker/subscribers
  participant C as Caregiver SSE
  participant M as Manager SSE

  A->>API: POST /sync/push (Idempotency-Key)
  API->>DB: Store dose and change-log row
  API->>O: Publish DoseRecorded
  API-->>A: Per-item accepted/duplicate/conflict
  W->>O: Claim pending event
  W->>DB: Points, badges, next visit, reminders, analytics, audit
  W-->>C: Tree progress update
  W-->>M: Dashboard counter update
  W->>O: Mark subscriber delivery processed
```

## Sync Flow

```mermaid
flowchart TD
  Local[IndexedDB pending doses/child updates] --> Push[POST /api/v1/sync/push]
  Push --> Key{Idempotency-Key seen?}
  Key -->|same payload| Replay[Return stored response]
  Key -->|new payload| Tx[Single DB transaction]
  Tx --> Doses[Union doses by client UUID and child/vaccine uniqueness]
  Tx --> Children[Last-write-wins child opt-in updates]
  Doses --> Results[accepted / duplicate / conflict / rejected]
  Children --> Results
  Results --> ChangeLog[Monotonic server change log]
  ChangeLog --> Pull[GET /api/v1/sync/pull?cursor=n]
  Pull --> Client[Client updates local IndexedDB cursor]
  Results --> Conflicts[ASHA conflict review queue]
```

## Data Model

```mermaid
erDiagram
  VILLAGE ||--o{ USER : has
  VILLAGE ||--o{ CHILD : contains
  USER ||--o{ CHILD : guardian
  USER ||--o{ CHILD : asha
  USER ||--o{ CONSENT : grants
  CHILD ||--o{ DOSE : receives
  VACCINE_SCHEDULE ||--o{ DOSE : describes
  VILLAGE ||--o{ SESSION : hosts
  SESSION ||--o{ DOSE : records
  SESSION ||--o{ STOCK_LOG : consumes
  CHILD ||--o{ NOTIFICATION_LOG : reminds
  CHILD ||--o{ CONFLICT_REVIEW_ITEM : queues
  OUTBOX_EVENT ||--o{ EVENT_DELIVERY : tracks

  VILLAGE {
    int id
    string block
    string district
  }
  USER {
    int id
    enum role
    encrypted_string phone
    encrypted_string guardian_name
    int village_id
  }
  CHILD {
    int id
    date dob
    enum sex
    bool opt_in_sms
    datetime deleted_at
  }
  DOSE {
    int id
    int child_id
    string vaccine_code
    date given_on
    string client_uuid
  }
  VACCINE_SCHEDULE {
    string vaccine_code
    int age_due_days
    int window_days
    bool endemic_only
  }
```

## Boundaries

- Routers expose HTTP contracts and dependency injection only.
- Services own business rules: schedule, gamification, analytics, notifications, privacy, sync, and events.
- Repositories own database queries and pagination/filtering details.
- Models define persistence, indexes, uniqueness, foreign keys, and soft deletion.
- Schemas define request validation and OpenAPI examples.
- Background jobs handle reminders, analytics refresh, leaderboards, retention, and register imports with retries/dead-letter logging.
