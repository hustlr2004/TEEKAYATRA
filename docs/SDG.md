# SDG Mapping

Teeka Yatra primarily supports immunisation completion and equitable primary-care follow-up. The mapping below links implemented product features to selected Sustainable Development Goals.

## SDG 3: Good Health And Well-Being

- Data-driven vaccine schedule with due, overdue, catch-up, and next-visit planning.
- ASHA visit lists, defaulter follow-up, and one-tap dose recording.
- SMS, IVR, app reminders, and printable vaccination cards.
- Programme manager analytics for coverage, dropout, timeliness, zero-dose counts, and mismatch alerts.

## SDG 1: No Poverty

- No monetary rewards, penalties, or punitive late-dose mechanics.
- Offline-first workflows reduce the cost of repeated facility visits caused by missing records.
- Paper card fallback and feature-phone support reduce dependence on smartphones and data plans.
- Catch-up support helps families re-enter care without stigma.

## SDG 4: Quality Education

- Low-literacy UI patterns: large icons, read-aloud buttons, short labels, and language switching.
- Caregiver progress views explain the next due vaccine and nearest session.
- Printable cards reinforce vaccine milestones in a field-friendly format.
- ASHA screens support consistent health-worker training patterns.

## SDG 5: Gender Equality

- Caregiver-first consent and data-rights flows support women and guardians as decision-makers.
- ASHA workflows acknowledge women frontline workers as primary system users.
- No public shaming reduces gendered stigma around missed visits.
- Aggregated manager dashboards avoid exposing mothers or caregivers in public rankings.

## SDG 9: Industry, Innovation And Infrastructure

- Offline-first PWA with IndexedDB and service-worker caching.
- Idempotent sync with client UUIDs, conflict flags, and last-write-wins child metadata.
- Pluggable notification gateway for SMS/IVR/app delivery.
- Docker Compose and `make demo` provide a reproducible implementation path.

## SDG 10: Reduced Inequalities

- Works across smartphone, feature-phone, and paper-card channels.
- Hindi/Punjabi/English language support in the demo UI and reminder templates.
- JE endemic-only schedule logic supports district-specific needs.
- Manager analytics surface zero-dose and dropout gaps by block for targeted outreach.

## SDG 16: Peace, Justice And Strong Institutions

- Privacy by design: consent, audit logs, role-based access, encryption, and data minimisation review.
- Grievance form and caregiver export/delete flow.
- Ethics tests fail builds if leaderboards expose names/phones or points rules go negative.
- Admin-only retention job removes old low-value logs.

## SDG 17: Partnerships For The Goals

- Triangulation compares app records, stock usage, and simulated U-WIN/HMIS-style CSV data.
- Aggregate dashboards help managers coordinate with ASHAs, villages, and programme teams.
- YAML rules and schedule-as-data make policy updates auditable and portable.
- Open API surfaces support integration with SMS/IVR gateways and future government data systems.
