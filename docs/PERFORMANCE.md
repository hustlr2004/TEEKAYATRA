# Performance

## Scope

This pass adds pagination, filtering, sorting, compression, ETag caching, large-data seeding, and Locust load testing for read-heavy API paths.

## Large Dataset

Seed 100,000 children and 1,000,000 doses:

```bash
cd backend
python -m app.performance_seed
```

The seed creates:

- 10 performance villages in district `Load`
- 50 ASHAs
- 2,000 caregivers
- 100,000 children
- 1,000,000 dose records, capped by the no-duplicate-dose-per-child-per-vaccine constraint

The script is separate from `make demo` so the normal demo stays fast.

## Optimisations Added

- DB-backed pagination for child, user, village, schedule, grievance, conflict, leaderboard, and manager analytics list-style endpoints.
- Filtering by relevant fields such as `q`, `role`, `block`, `district`, `status`, and analytics date ranges.
- Sorting with allow-listed columns to avoid unsafe dynamic SQL.
- GZip response compression for larger responses.
- ETag caching for safe JSON `GET` responses, returning `304` on matching `If-None-Match`.
- Extra indexes:
  - `villages(district, block)`
  - `grievances(status, created_at)`
- Existing high-value indexes remain in place for child village lookups, dose child/vaccine lookup, dose dates, and points entity lookups.

## Locust

Run the API, seed the large dataset, then run:

```bash
cd backend
locust -f locustfile.py --host http://localhost:8000 \
  --headless --users 50 --spawn-rate 5 --run-time 5m \
  --csv ../docs/performance-locust
```

The Locust scenario exercises:

- `GET /children?page=1&page_size=100&sort=id`
- `GET /villages?page=1&page_size=50&district=Load`
- `GET /schedule?page=1&page_size=50`
- `GET /analytics/manager?district=Load&page=1&page_size=20`
- `GET /leaderboard/village?page=1&page_size=20`

## Current Local Verification

The full-scale Postgres/Redis stack was not running in this local workspace, so the 100k/1m Locust benchmark was not executed here. The implemented performance paths were verified with automated tests against SQLite and the full backend test suite.

| Check | Result |
|---|---:|
| Pagination/filter/sort/ETag API test | Pass |
| Analytics aggregate tests | Pass |
| Full backend tests | 89 passed |
| Bandit | Pass |

## Target Report Template

Use this table when `docs/performance-locust_stats.csv` is produced from the command above. Read endpoints should stay under 300 ms p95.

| Endpoint | p50 ms | p95 ms | Target |
|---|---:|---:|---|
| `GET /children` | TBD | TBD | p95 < 300 ms |
| `GET /villages` | TBD | TBD | p95 < 300 ms |
| `GET /schedule` | TBD | TBD | p95 < 300 ms |
| `GET /analytics/manager` | TBD | TBD | p95 < 300 ms |
| `GET /leaderboard/village` | TBD | TBD | p95 < 300 ms |
| `GET /sync/pull` | TBD | TBD | p95 < 300 ms |
| `GET /sync/conflicts` | TBD | TBD | p95 < 300 ms |
| `GET /users` | TBD | TBD | p95 < 300 ms |
| `GET /grievances` | TBD | TBD | p95 < 300 ms |
| `GET /admin/jobs` | TBD | TBD | p95 < 300 ms |

## Notes

- Manager analytics is intentionally cached by filter tuple.
- Leaderboard responses are cached by pagination and sort tuple.
- Child-level reads remain role-filtered before pagination.
- ETags are only emitted for safe JSON `GET` responses, not PDFs, SSE, or metrics.
