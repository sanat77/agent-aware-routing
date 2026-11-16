# MiniIssueTracker

A small issue/task tracking REST service. Pure standard library (WSGI + SQLite); tests use pytest.

## Layout

| Module | Responsibility |
|---|---|
| `tracker/app.py` | application factory and dependency wiring |
| `tracker/api.py` | REST routes |
| `tracker/http.py` | WSGI micro-framework, routing, error mapping, test client |
| `tracker/services.py` | business logic (tasks, users, stats, idempotency) |
| `tracker/repository.py` | SQL data access |
| `tracker/db.py` | SQLite schema, connections, transactions |
| `tracker/validation.py` | payload validation |
| `tracker/auth.py` | password hashing, bearer tokens, permissions |
| `tracker/pagination.py` | page-number pagination |
| `tracker/query.py` | filtering and sorting |
| `tracker/serializers.py` | JSON serialization |
| `tracker/timeutil.py` | UTC date/time handling |
| `tracker/convert.py` | type conversion of query values |
| `tracker/cache.py` | TTL cache |
| `tracker/retry.py` | retry with exponential backoff |
| `tracker/attachments.py` | file attachments on disk |
| `tracker/sequence.py` | ticket numbers |
| `tracker/idempotency.py` | Idempotency-Key handling |
| `tracker/config.py` | configuration loading |
| `tracker/models.py` | domain models and status state machine |

## API

| Method | Path | Notes |
|---|---|---|
| POST | /users | register (201) |
| POST | /auth/login | returns bearer token |
| GET | /users/me, /users/{id} | email visible only to self/admin |
| GET | /tasks | `page`, `per_page`, `sort` (e.g. `-priority,title`), `status`, `assignee_id`, `owner_id`, `priority_min`, `q`, `tag`, `overdue` |
| POST | /tasks | 201; supports `Idempotency-Key` header |
| GET/PATCH/DELETE | /tasks/{id} | DELETE returns 204 |
| POST | /tasks/{id}/status | state machine: open→in_progress/closed, in_progress→open/blocked/done, blocked→in_progress, done→open/closed |
| GET | /tasks/stats | totals, by_status, completion_rate, average_priority |
| POST/GET | /tasks/{id}/attachments | |

## Running

```
python -m pytest -q          # tests
python -m tracker.app        # serve on :8000
```
