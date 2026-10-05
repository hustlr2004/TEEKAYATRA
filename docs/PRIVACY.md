# Privacy And Responsible Design Review

## Data Minimisation

Teeka Yatra stores only the data needed to support immunisation follow-up, offline work, auditability, and caregiver rights.

| Data | Why it is needed | Minimisation control |
| --- | --- | --- |
| Caregiver name and phone | Login, reminders, grievance follow-up | Phone is encrypted at rest and masked outside self-export/admin contexts |
| Child DOB, sex, village, guardian, ASHA | Schedule calculation and role-based care coordination | No child name field is stored in the current schema |
| Doses | Paper/app/register reconciliation and catch-up support | Batch/session/source are stored, but no monetary reward or penalty data |
| Consent | Proof of lawful caregiver choice | Consent has purpose scope and withdrawal timestamp |
| Audit logs | Accountability for child-data reads/writes | Retention job removes old audit entries |
| Notification logs | Demo gateway and delivery trace | Retention job removes old reminder logs |
| Grievances | Caregiver complaint and correction path | Stored separately from leaderboards and analytics |

## Consent And Choice

- Child creation requires active guardian consent for `store_child`.
- SMS and IVR reminders use separate consent scopes.
- Caregivers can withdraw consent and use `DELETE /me/data`.
- The frontend login flow presents consent checkboxes before mock OTP login.
- SMS STOP creates a channel opt-out and disables SMS reminders for the caregiver's children.

## Access And Masking

- Caregivers see only their own children.
- ASHAs see children only in assigned villages.
- Managers receive aggregate-only views and cannot print child cards or access child records.
- Admins can manage users and review grievances.
- Phone numbers are encrypted at rest and masked in admin user responses.

## Retention

`POST /jobs/data-retention` is admin-only and removes:

- Audit logs older than 365 days.
- Notification logs older than 180 days.
- Closed grievances older than 730 days.

Child clinical records are not automatically deleted by this job because they are part of the caregiver-held immunisation record. Deletion is caregiver-initiated through `DELETE /me/data`.

## Fairness And Gamification Guardrails

- No points rule may be negative.
- Late doses receive catch-up support, never penalties.
- Leaderboards are village/team aggregates only.
- The ethics test suite fails if leaderboard payloads expose name-like or phone-like fields.
- Duplicate doses are rejected and implausible ASHA daily volume is flagged for review.

## Grievance And Data Rights

- `POST /grievances` lets caregivers file correction/support requests.
- `GET /me/data/export` returns a caregiver's own user, consent, child, dose, and grievance data.
- `DELETE /me/data` removes caregiver child records, withdraws consents, and anonymises the caregiver account.

## Residual Risks

- The current rate limiter is in-memory and intended for local/demo SQLite deployments; production should use a shared backing store such as Redis.
- Demo frontend export/delete is local-browser only until connected to authenticated API calls.
- Hindi/Punjabi labels use transliterated text where the default PDF font does not support full Indic glyph shaping.
