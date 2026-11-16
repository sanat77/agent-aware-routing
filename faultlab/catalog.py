"""Bug catalog for MiniIssueTracker.

Each category owns
  * a check module in faultlab/checks/<module>.py (hidden tests, parameterised by a `case` dict),
  * several deterministic faults (exact source mutations),
  * a parameter generator producing the `case` dict for a variation,
  * issue-report text per fault.

Variation v (0..39) of a category uses fault  faults[v % len(faults)]  and parameters drawn from
random.Random(f"{category}:{v}"), so every episode is reproducible from (category, v) alone.
"""
import random
import string
from dataclasses import dataclass, field

VARIATIONS_PER_CATEGORY = 40

WORDS = ["login", "export", "invoice", "upload", "search", "report", "billing", "sync", "webhook",
         "profile", "session", "backup", "import", "metrics", "audit", "calendar", "digest", "badge"]


@dataclass(frozen=True)
class Fault:
    id: str
    edits: tuple            # ((relative_path, old, new), ...); each `old` must occur exactly once
    visible_test: str       # check function shipped to the agent as the failing reproduction test
    title: str
    expected: str
    actual: str
    needs: dict = field(default_factory=dict)   # parameter constraints understood by the generator


@dataclass(frozen=True)
class Category:
    name: str
    module: str
    description: str
    faults: tuple
    params: object          # callable(rng, fault_id) -> dict


def _word(rng):
    return rng.choice(WORDS)


def _titles(rng, n):
    return [f"{w}-{i}" for i, w in enumerate(rng.sample(WORDS, n))]


# ---------------------------------------------------------------------------
# parameter generators
# ---------------------------------------------------------------------------

def p_pagination(rng, fault):
    per_page = rng.randint(2, 5)
    return {"n": rng.randint(3, 12), "per_page": per_page, "full_pages": rng.randint(1, 4),
            "remainder": rng.randint(1, per_page - 1), "big_per_page": rng.randint(21, 30)}


def p_sorting(rng, fault):
    k = rng.randint(3, 5)
    titles = _titles(rng, k)
    priorities = rng.sample([1, 2, 3, 4, 5], k)
    words = rng.sample(WORDS, 3)
    words.sort()
    mixed = [words[0], words[1].capitalize(), words[2].upper()]
    rng.shuffle(mixed)
    due = [f"2026-04-{d:02d}" for d in rng.sample(range(1, 28), k)]
    none_idx = rng.sample(range(k), rng.randint(1, k - 1))
    for i in none_idx:
        due[i] = None
    return {"titles": titles, "priorities": priorities, "same_priority": rng.randint(1, 5),
            "mixed_titles": mixed, "due_dates": due}


def p_filtering(rng, fault):
    word = _word(rng)
    query = rng.choice([word, word.upper(), word.capitalize(), word[1:]])
    statuses = rng.sample(["open", "in_progress", "closed"], rng.randint(2, 3))
    priorities = [rng.randint(1, 5) for _ in range(rng.randint(3, 6))]
    pmin = rng.choice(priorities)
    tag = rng.choice(["api", "ui", "db", "ops", "docs"])
    return {"word": word, "query": query, "statuses": statuses, "none_token": rng.choice(["None", "NONE", "NoNe"]),
            "priorities": priorities, "priority_min": pmin, "tag": tag,
            "container_tag": rng.choice([tag + "v2", "legacy" + tag, tag + "-old"])}


def p_boundary(rng, fault):
    return {"prefix": f"{_word(rng)} {rng.randint(1, 999)} ", "tag_stem": rng.choice(["a", "tag", "zz", "lbl"])}


def p_null_empty(rng, fault):
    return {"title": f"{_word(rng)} task", "blank": rng.choice(["", "   ", "\t", " \n "]),
            "ws_title": rng.choice(["   ", "\t", " \n ", "\u00a0 "])}


def p_authentication(rng, fault):
    wrong = "" if fault == "auth_empty_password" else rng.choice(["password124", "Password123", "letmein!"])
    return {"user_id": rng.randint(1, 500), "ttl": rng.randint(10, 7200), "extra": rng.randint(1, 600),
            "scheme": rng.choice(["bearer", "BEARER", "bEaReR"]), "wrong_password": wrong}


def p_permissions(rng, fault):
    return {"title": f"{_word(rng)} cleanup", "new_title": f"{_word(rng)} rewrite",
            "status": rng.choice(["in_progress", "closed"])}


def p_serialization(rng, fault):
    return {"past_due": f"2026-02-{rng.randint(1, 28):02d}", "future_due": f"2026-{rng.randint(4, 12):02d}-15",
            "tags": rng.sample(["api", "ui", "db", "ops", "docs", "perf"], rng.randint(1, 3)),
            "seconds": rng.randint(1, 3000)}


def p_datetime(rng, fault):
    date = f"2026-{rng.randint(4, 12):02d}-{rng.randint(1, 28):02d}"
    hour = rng.randint(6, 16)
    offset = rng.choice([1, 2, 3, 5, -4, -7])
    utc_hour = hour - offset
    local = f"2026-06-10T{hour:02d}:30:00{'+' if offset > 0 else '-'}{abs(offset):02d}:00"
    return {"date": date, "local": local, "utc": f"2026-06-10T{utc_hour:02d}:30:00Z",
            "past_due": f"2026-03-0{rng.randint(1, 9)}"}


def p_defaults(rng, fault):
    return {"n": rng.randint(11, 25), "priority": rng.choice([1, 2, 4, 5]), "title": f"{_word(rng)} default",
            "seconds": rng.randint(400, 3500)}


def p_duplicates(rng, fault):
    key = "key-" + "".join(rng.choice(string.ascii_lowercase + string.digits) for _ in range(10))
    return {"key": key, "title": f"{_word(rng)} once", "repeats": rng.randint(2, 4), "priority": rng.randint(1, 5)}


def p_retry(rng, fault):
    return {"attempts": rng.randint(3, 5), "base": rng.choice([0.01, 0.02, 0.05, 0.1]),
            "message": rng.choice(["lock timeout on table tasks", "database busy during commit",
                                   "write lock held by worker"])}


def p_exceptions(rng, fault):
    return {"email": f"alice{rng.randint(2, 99)}@example.com",
            "bad_body": rng.choice(["{not json", "{\"title\": ", "[1, 2", "title=x"]),
            "user_id": rng.randint(100, 999),
            "bad_date": rng.choice(["2026-13-45", "tomorrow", "2026/03/01", "31-12-2026"])}


def p_transitions(rng, fault):
    reopen = "open" if fault == "closed_reopenable" else rng.choice(["open", "in_progress"])
    return {"title": f"{_word(rng)} flow", "reopen_to": reopen}


def p_db_query(rng, fault):
    n = rng.randint(3, 7)
    return {"n": n, "k": rng.randint(1, n - 2), "per_page": rng.randint(2, 5)}


def p_aggregation(rng, fault):
    statuses = ["open", "in_progress", "closed", "done"] + [rng.choice(["open", "blocked", "closed", "done"])
                                                            for _ in range(rng.randint(0, 3))]
    rng.shuffle(statuses)
    while True:
        priorities = [rng.randint(1, 5) for _ in range(rng.randint(2, 5))]
        if sum(priorities) % len(priorities):
            break
    while True:
        n = rng.choice([3, 6, 7, 9])
        k = rng.randint(1, n - 1)
        if round(k / n, 2) != round(k / n, 4):
            break
    return {"statuses": statuses, "priorities": priorities, "n": n, "k": k}


def p_input_validation(rng, fault):
    return {"email": rng.choice(["carol@localhost", "carol@intranet", "a@b"]),
            "username": rng.choice(["car$ol", "bob!x", "x@y.z", "o'neil"]),
            "unknown_field": rng.choice(["owner_id", "id", "ticket_number", "created_at"]),
            "password": "".join(rng.choice(string.ascii_lowercase) for _ in range(rng.choice([6, 7]))),
            "bad_title": rng.choice([123, 4.5, ["x"], {"a": 1}])}


def p_file_paths(rng, fault):
    name = rng.choice(["report.txt", "notes.md", "trace.log", "data.csv"])
    return {"name": name, "hidden": rng.choice([".env", ".secrets.txt", ".bashrc"]),
            "folder": rng.choice(["q1", "2026", "drafts"])}


def p_fallback(rng, fault):
    return {"junk": rng.choice(["abc", "12x", "", "ten"]) or "none", "non_positive": rng.choice([0, -1, -5]),
            "file_value": rng.randint(30, 60), "env_value": rng.randint(5, 15),
            "broken_json": rng.choice(["{", "not json", "{'a': 1}"])}


def p_error_propagation(rng, fault):
    return {"missing_id": rng.randint(100, 9999), "length": rng.randint(121, 200),
            "target": rng.choice(["done", "blocked"])}


def p_resource_cleanup(rng, fault):
    return {"message": f"boom {rng.randint(1, 99)}", "attempts": rng.randint(1, 3),
            "name": rng.choice(["a.txt", "b.md"]), "ttl": rng.randint(5, 120)}


def p_concurrency(rng, fault):
    return {"threads": rng.randint(3, 8), "start": rng.randint(1, 500)}


def p_type_conversion(rng, fault):
    return {"mixed_case_true": rng.choice(["True", "TRUE", "Yes", "ON"]),
            "false_word": rng.choice(["false", "0", "no", "off", "False"]),
            "fraction": rng.choice([2.5, 3.7, 1.2, 4.9]), "bool_value": True}


def p_status_codes(rng, fault):
    return {"title": f"{_word(rng)} status", "username": rng.choice(["carol", "dave", "erin", "frank"])}


def p_cache(rng, fault):
    return {"before": f"{_word(rng)} v1", "after": f"{_word(rng)} v2", "status": rng.choice(["in_progress", "closed"]),
            "n": rng.randint(1, 4)}


# ---------------------------------------------------------------------------
# faults
# ---------------------------------------------------------------------------
P = "tracker/pagination.py"
Q = "tracker/query.py"
V = "tracker/validation.py"
A = "tracker/auth.py"
S = "tracker/services.py"
SER = "tracker/serializers.py"
T = "tracker/timeutil.py"
C = "tracker/config.py"
M = "tracker/models.py"
I = "tracker/idempotency.py"
R = "tracker/retry.py"
REPO = "tracker/repository.py"
H = "tracker/http.py"
E = "tracker/errors.py"
DB = "tracker/db.py"
ATT = "tracker/attachments.py"
SEQ = "tracker/sequence.py"
CONV = "tracker/convert.py"
API = "tracker/api.py"
CACHE = "tracker/cache.py"

CATEGORIES = [
    Category("incorrect_pagination", "pagination", "Pagination returns the wrong slice or wrong page metadata", (
        Fault("page_offset", ((P, "return (self.page - 1) * self.per_page", "return self.page * self.per_page"),),
              "test_first_page_starts_at_first_item", "First page of /tasks skips the first items",
              "page=1 starts with the very first task", "page=1 is missing the first per_page tasks"),
        Fault("total_pages_floor", ((P, "math.ceil(total / request.per_page) if total else 0",
                                     "total // request.per_page if total else 0"),),
              "test_last_partial_page_is_counted", "total_pages ignores the final partial page",
              "a partially filled last page is counted in total_pages", "total_pages is one too small"),
        Fault("has_next_last_page", ((P, '"has_next": request.page < total_pages,',
                                      '"has_next": request.page <= total_pages,'),),
              "test_no_next_page_on_last_page", "has_next is true on the last page",
              "has_next is false on the last page", "clients keep requesting an empty extra page"),
        Fault("per_page_capped_to_default", ((P, "per_page = min(per_page, config.max_page_size)",
                                              "per_page = min(per_page, config.default_page_size)"),),
              "test_per_page_above_default_is_honoured", "per_page values above 20 are silently reduced",
              "per_page up to max_page_size (100) is honoured", "per_page is capped at the default page size"),
    ), p_pagination),
    Category("sorting_errors", "sorting", "Task list ordering is wrong", (
        Fault("desc_ignored", ((Q, '            direction = "DESC"\n', '            direction = "ASC"\n'),),
              "test_descending_sort", "sort=-priority returns ascending order",
              "a leading '-' sorts descending", "results come back in ascending order"),
        Fault("tiebreak_desc", ((Q, 'order.append(("id", "ASC"))', 'order.append(("id", "DESC"))'),),
              "test_ties_broken_by_ascending_id", "Tasks with equal sort keys come back newest-first",
              "ties are broken by ascending id (creation order)", "ties are ordered by descending id"),
        Fault("title_case_sensitive", ((Q, 'clauses.append(f"LOWER(title) {direction}")',
                                        'clauses.append(f"title {direction}")'),),
              "test_title_sort_ignores_case", "sort=title puts capitalised titles first",
              "title sorting is case-insensitive", "uppercase titles sort before lowercase ones"),
        Fault("nulls_first", ((Q, 'clauses.append(f"due_at IS NULL, due_at {direction}")',
                               'clauses.append(f"due_at {direction}")'),),
              "test_tasks_without_due_date_sort_last", "Tasks without a due date sort first by due_at",
              "tasks without due_at always sort last", "undated tasks appear at the top"),
    ), p_sorting),
    Category("filtering_errors", "filtering", "List filters return the wrong tasks", (
        Fault("search_prefix_only", ((Q, 'args.append("%" + str(text).strip().lower() + "%")',
                                      'args.append(str(text).strip().lower() + "%")'),),
              "test_search_matches_anywhere_in_title", "Search q= only matches the start of a title",
              "q matches anywhere in the title", "words in the middle of a title are not found"),
        Fault("status_list_first_only", ((Q, 'statuses = [s.strip() for s in str(status).split(",") if s.strip()]',
                                          'statuses = [str(status).split(",")[0].strip()]'),),
              "test_filter_by_several_statuses", "status=a,b only filters by the first status",
              "every comma-separated status is included", "only the first status is applied"),
        Fault("unassigned_case", ((Q, 'if str(assignee).lower() == "none":', 'if str(assignee) == "none":'),),
              "test_filter_unassigned_tasks", "assignee_id=None returns a validation error",
              "assignee_id=none (any case) lists unassigned tasks", "mixed-case 'None' is rejected with 422"),
        Fault("priority_min_exclusive", ((Q, 'clauses.append("priority >= ?")', 'clauses.append("priority > ?")'),),
              "test_priority_min_is_inclusive", "priority_min excludes tasks with exactly that priority",
              "priority_min is inclusive", "tasks at the minimum priority are missing"),
        Fault("tag_substring", ((Q, "args.append('%\"' + str(tag).strip().lower() + '\"%')",
                                 "args.append(\"%\" + str(tag).strip().lower() + \"%\")"),),
              "test_tag_filter_matches_whole_tag", "tag= filter also matches longer tags containing the text",
              "tag=X matches only the exact tag X", "tasks tagged e.g. 'Xv2' are returned too"),
    ), p_filtering),
    Category("boundary_conditions", "boundary", "Inclusive limits are treated as exclusive", (
        Fault("title_max_exclusive", ((V, "if len(title) > TITLE_MAX:", "if len(title) >= TITLE_MAX:"),),
              "test_title_at_max_length_accepted", "Titles of exactly 120 characters are rejected",
              "a 120-character title is accepted", "422 title too_long"),
        Fault("priority_max_exclusive", ((V, "if priority < PRIORITY_MIN or priority > PRIORITY_MAX:",
                                          "if priority < PRIORITY_MIN or priority >= PRIORITY_MAX:"),),
              "test_priority_upper_bound_accepted", "priority=5 is rejected", "priority 5 is valid",
              "422 priority out_of_range"),
        Fault("priority_min_exclusive", ((V, "if priority < PRIORITY_MIN or priority > PRIORITY_MAX:",
                                          "if priority <= PRIORITY_MIN or priority > PRIORITY_MAX:"),),
              "test_priority_lower_bound_accepted", "priority=1 is rejected", "priority 1 is valid",
              "422 priority out_of_range"),
        Fault("max_tags_exclusive", ((V, "if len(cleaned) > MAX_TAGS:", "if len(cleaned) >= MAX_TAGS:"),),
              "test_maximum_number_of_tags_accepted", "A task with exactly 10 tags is rejected",
              "10 tags are allowed", "422 tags too_many"),
        Fault("tag_length_exclusive", ((V, "if len(tag) > TAG_MAX_LENGTH:", "if len(tag) >= TAG_MAX_LENGTH:"),),
              "test_tag_at_max_length_accepted", "30-character tags are rejected", "a 30-character tag is valid",
              "422 tag too long"),
    ), p_boundary),
    Category("null_empty_handling", "null_empty", "Null / empty / whitespace inputs are mishandled", (
        Fault("blank_description_kept", ((V, "    text = value.strip()\n    return text or None",
                                          "    text = value.strip()\n    return text"),),
              "test_blank_description_stored_as_null", "Blank descriptions are stored as empty strings",
              "a blank description is stored as null", "description comes back as \"\""),
        Fault("title_not_stripped", ((V, "    title = value.strip()\n", "    title = value\n"),),
              "test_whitespace_only_title_rejected", "Whitespace-only titles are accepted",
              "a whitespace-only title is rejected with 422", "the task is created with a blank title"),
        Fault("null_tags_rejected", ((V, "    if value is None:\n        return []\n    if not isinstance(value, list):",
                                      "    if not isinstance(value, list):"),
                                     (V, 'cleaned["tags"] = _clean_tags(data.get("tags"))',
                                      'cleaned["tags"] = _clean_tags(data.get("tags", []))')),
              "test_null_tags_become_empty_list", "Sending \"tags\": null fails with 422",
              "tags: null is treated as no tags", "422 tags must be a list"),
        Fault("null_priority_defaulted", ((V, '        raise ValidationError("priority must not be null", {"priority": "required"})',
                                           "        return 3"),),
              "test_null_priority_rejected", "\"priority\": null is silently accepted",
              "an explicit null priority is rejected with details {priority: required}",
              "the task is created with priority 3"),
    ), p_null_empty),
    Category("authentication_mistakes", "authentication", "Authentication accepts or rejects the wrong credentials", (
        Fault("expiry_inclusive", ((A, "if int(now.timestamp()) >= expires:", "if int(now.timestamp()) > expires:"),),
              "test_token_rejected_at_exact_expiry", "Tokens are still accepted at their exact expiry second",
              "a token is invalid once now >= expiry", "the token works for one extra second"),
        Fault("scheme_case_sensitive", ((A, 'if scheme.lower() != "bearer" or not token.strip():',
                                         'if scheme != "Bearer" or not token.strip():'),),
              "test_bearer_scheme_is_case_insensitive", "Authorization: bearer <token> is rejected",
              "the Bearer scheme is matched case-insensitively", "401 unsupported authorization scheme"),
        Fault("ttl_minutes", ((A, "expires = int(now.timestamp()) + ttl_seconds", "expires = int(now.timestamp()) + ttl_seconds * 60"),),
              "test_token_expires_after_ttl", "Login tokens stay valid long after the TTL",
              "tokens expire after token_ttl_seconds", "tokens keep working past the TTL"),
        Fault("auth_empty_password", ((S, 'if user is None or not auth.verify_password(password or "", user.password_hash):',
                                       'if user is None or (password and not auth.verify_password(password, user.password_hash)):'),),
              "test_wrong_password_rejected", "Login succeeds with an empty password",
              "an empty password is rejected with 401", "a token is issued"),
    ), p_authentication),
    Category("permission_errors", "permissions", "Permission checks allow or deny the wrong users", (
        Fault("assignee_can_edit", ((A, '"""Only the owner of a task or an admin may edit its fields."""\n    return user.is_admin or task.owner_id == user.id',
                                     '"""Only the owner of a task or an admin may edit its fields."""\n    return user.is_admin or user.id in (task.owner_id, task.assignee_id)'),),
              "test_assignee_cannot_edit_fields", "Assignees can edit task fields",
              "only the owner or an admin may PATCH a task", "the assignee gets 200"),
        Fault("assignee_can_delete", ((A, "def can_delete_task(user, task):\n    return user.is_admin or task.owner_id == user.id",
                                       "def can_delete_task(user, task):\n    return user.is_admin or user.id in (task.owner_id, task.assignee_id)"),),
              "test_assignee_cannot_delete", "Assignees can delete tasks they do not own",
              "DELETE by a non-owner assignee returns 403", "the task is deleted"),
        Fault("assignee_cannot_move", ((A, "    return user.id in (task.owner_id, task.assignee_id)", "    return user.id == task.owner_id"),),
              "test_assignee_can_change_status", "Assignees cannot change the status of their tasks",
              "the assignee may change status", "403 forbidden"),
        Fault("admin_email_hidden", ((A, "return viewer.is_admin or viewer.id == user.id", "return viewer.id == user.id"),),
              "test_admin_can_see_user_email", "Admins cannot see user email addresses",
              "admins see the email field", "email is missing for admins"),
        Fault("unassigned_anyone_moves", ((A, "    return user.id in (task.owner_id, task.assignee_id)",
                                           "    return task.assignee_id is None or user.id in (task.owner_id, task.assignee_id)"),),
              "test_stranger_cannot_change_status", "Anyone can change the status of unassigned tasks",
              "a user who is neither owner nor assignee gets 403", "the status change succeeds"),
    ), p_permissions),
    Category("serialization_bugs", "serialization", "API JSON output has wrong types or fields", (
        Fault("overdue_string", ((SER, '"is_overdue": is_overdue(task.due_at, task.status, now),',
                                  '"is_overdue": str(is_overdue(task.due_at, task.status, now)).lower(),'),),
              "test_is_overdue_is_a_boolean", "is_overdue is serialized as a string",
              "is_overdue is a JSON boolean", "is_overdue is \"true\"/\"false\""),
        Fault("password_hash_leak", ((SER, '        "created_at": user.created_at,\n    }',
                                      '        "created_at": user.created_at,\n        "password_hash": user.password_hash,\n    }'),),
              "test_password_hash_never_serialized", "User responses include password_hash",
              "password hashes never leave the server", "password_hash is present in /users/me"),
        Fault("tags_joined", ((SER, '"tags": list(task.tags),', '"tags": ",".join(task.tags),'),),
              "test_tags_serialized_as_list", "tags are returned as a comma-separated string",
              "tags is a JSON array", "tags is a string"),
        Fault("updated_at_wrong", ((SER, '"updated_at": task.updated_at,', '"updated_at": task.created_at,'),),
              "test_updated_at_changes_on_update", "updated_at never changes after an edit",
              "updated_at reflects the time of the last update", "updated_at equals created_at"),
    ), p_serialization),
    Category("datetime_errors", "datetime_handling", "Due dates are parsed or compared incorrectly", (
        Fault("date_start_of_day", ((T, "time(23, 59, 59)", "time(0, 0, 0)"),),
              "test_date_only_due_means_end_of_day", "Date-only due dates become midnight at the start of the day",
              "due_at=YYYY-MM-DD means 23:59:59Z that day", "due_at is T00:00:00Z"),
        Fault("offset_dropped", ((T, "return parsed.astimezone(timezone.utc).replace(microsecond=0)",
                                  "return parsed.replace(tzinfo=timezone.utc, microsecond=0)"),),
              "test_offset_converted_to_utc", "Due dates with a UTC offset are stored with the wrong time",
              "offsets are converted to UTC", "the local clock time is stored as if it were UTC"),
        Fault("overdue_inclusive", ((T, "    return due < now\n", "    return due <= now\n"),),
              "test_due_exactly_now_is_not_overdue", "A task due right now is reported as overdue",
              "overdue means strictly past due", "is_overdue is true at the due instant"),
        Fault("done_overdue", ((T, 'if due_at is None or status in ("done", "closed"):',
                                'if due_at is None or status == "closed":'),),
              "test_done_task_is_not_overdue", "Completed tasks are still flagged overdue",
              "done tasks are never overdue", "is_overdue stays true after completion"),
    ), p_datetime),
    Category("incorrect_defaults", "defaults", "Default values are wrong", (
        Fault("page_size_10", ((C, '"default_page_size": 20,', '"default_page_size": 10,'),),
              "test_default_page_size_is_twenty", "GET /tasks returns 10 items by default",
              "the default page size is 20", "only 10 items are returned"),
        Fault("priority_default_ignored", ((S, "data = validate_task_payload(payload, default_priority=self.config.default_priority)",
                                            "data = validate_task_payload(payload)"),),
              "test_configured_default_priority_used", "The configured default_priority is ignored",
              "new tasks use config.default_priority", "new tasks always get priority 3"),
        Fault("default_status", ((M, 'DEFAULT_STATUS = "open"', 'DEFAULT_STATUS = "in_progress"'),),
              "test_new_tasks_start_open", "New tasks start in_progress", "new tasks start open",
              "status is in_progress"),
        Fault("ttl_default", ((C, '"token_ttl_seconds": 3600,', '"token_ttl_seconds": 360,'),),
              "test_token_valid_within_default_ttl", "Users are logged out after a few minutes",
              "tokens last one hour by default", "401 after ~6 minutes"),
    ), p_defaults),
    Category("duplicate_request_handling", "duplicate_requests", "Idempotency-Key handling is wrong", (
        Fault("key_not_user_scoped", ((I, '"SELECT fingerprint, status, body FROM idempotency_keys WHERE key = ? AND user_id = ?",\n                (key, user_id),',
                                       '"SELECT fingerprint, status, body FROM idempotency_keys WHERE key = ?",\n                (key,),'),),
              "test_idempotency_key_scoped_per_user", "Two users with the same Idempotency-Key get each other's task",
              "keys are scoped to the user", "the second user receives the first user's task"),
        Fault("mismatch_not_conflict", ((I, '            raise ConflictError("Idempotency-Key reused with a different payload")',
                                         "            return None"),),
              "test_key_reuse_with_different_payload_conflicts", "Reusing a key with a different body creates a new task",
              "409 when a key is reused with a different payload", "a second task is created"),
        Fault("replay_ignored", ((S, "            if previous is not None:\n                return previous",
                                  "            if previous is not None and previous[0] != 201:\n                return previous"),),
              "test_retried_post_creates_single_task", "Retried POSTs with the same key create duplicates",
              "a retried POST returns the original task", "each retry creates a new task"),
        Fault("fingerprint_order", ((I, 'canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))',
                                     'canonical = json.dumps(payload, separators=(",", ":"))'),),
              "test_field_order_does_not_matter", "Same payload with different key order is a 409",
              "JSON field order does not affect idempotency", "409 conflict"),
    ), p_duplicates),
    Category("retry_logic_bugs", "retry_logic", "Retry helper retries the wrong number of times or the wrong errors", (
        Fault("one_attempt_short", ((R, "    for attempt in range(attempts):", "    for attempt in range(attempts - 1):"),),
              "test_gives_up_after_configured_attempts", "retry_call returns None instead of raising when retries run out",
              "the last TransientError is raised after `attempts` tries", "None is returned"),
        Fault("retries_everything", ((R, "        except retry_on:", "        except Exception:"),),
              "test_non_transient_errors_not_retried", "Programming errors are retried",
              "only retry_on errors are retried", "ValueError is retried"),
        Fault("linear_backoff", ((R, "base_delay * (2 ** i)", "base_delay * (2 * i)"),),
              "test_backoff_doubles_each_attempt", "Backoff starts at zero and grows linearly",
              "delays are base, 2*base, 4*base...", "first delay is 0"),
        Fault("constant_sleep", ((R, "sleep(delays[attempt])", "sleep(delays[0])"),),
              "test_sleeps_follow_backoff_schedule", "Retries never back off", "sleeps follow the backoff schedule",
              "every sleep uses the first delay"),
        Fault("error_replaced", ((R, "            if attempt == attempts - 1:\n                raise\n",
                                  "            if attempt == attempts - 1:\n                raise TransientError(\"retries exhausted\")\n"),),
              "test_exhausted_retries_reraise_last_error", "The original error message is lost after retries",
              "the last underlying exception is re-raised", "a generic 'retries exhausted' error"),
    ), p_retry),
    Category("exception_handling_errors", "exception_handling", "Exceptions surface as 500s instead of proper errors", (
        Fault("integrity_runtime", ((REPO, '            raise ConflictError("username or email already registered") from exc',
                                     '            raise RuntimeError("username or email already registered") from exc'),),
              "test_duplicate_registration_is_conflict", "Registering an existing username returns 500",
              "409 conflict", "500 internal_error"),
        Fault("json_error_uncaught", ((H, "except (UnicodeDecodeError, json.JSONDecodeError) as exc:",
                                       "except UnicodeDecodeError as exc:"),),
              "test_malformed_json_is_bad_request", "Malformed JSON bodies return 500", "400 bad_request",
              "500 internal_error"),
        Fault("unknown_user_404", ((S, "        try:\n            return self.users.get(user_id)\n        except NotFoundError as exc:\n            raise AuthenticationError(\"unknown user\") from exc",
                                    "        return self.users.get(user_id)"),),
              "test_token_for_unknown_user_is_unauthenticated", "A token for a deleted user returns 404",
              "401 unauthenticated", "404 not_found"),
        Fault("date_error_uncaught", ((T, "    except ValueError as exc:\n        raise ValidationError(f\"{field} is not a valid date\"",
                                       "    except TypeError as exc:\n        raise ValidationError(f\"{field} is not a valid date\""),),
              "test_invalid_due_date_is_validation_error", "Invalid due dates return 500", "422 validation_error",
              "500 internal_error"),
    ), p_exceptions),
    Category("state_transition_errors", "state_transitions", "Task status state machine allows/denies the wrong moves", (
        Fault("blocked_to_done", ((M, '"blocked": {"in_progress"},', '"blocked": {"in_progress", "done"},'),),
              "test_blocked_task_cannot_be_finished", "Blocked tasks can be marked done directly",
              "blocked -> done is rejected with 409", "200"),
        Fault("closed_reopenable", ((M, '"closed": set(),', '"closed": {"open"},'),),
              "test_closed_task_is_final", "Closed tasks can be reopened", "closed is terminal", "200"),
        Fault("done_not_reopenable", ((M, '"done": {"open", "closed"},', '"done": {"closed"},'),),
              "test_done_task_can_be_reopened", "Done tasks cannot be reopened", "done -> open is allowed", "409"),
        Fault("cannot_block", ((M, '"in_progress": {"open", "blocked", "done"},', '"in_progress": {"open", "done"},'),),
              "test_in_progress_task_can_be_blocked", "In-progress tasks cannot be blocked",
              "in_progress -> blocked is allowed", "409"),
        Fault("transition_reversed", ((M, "return target in TRANSITIONS.get(current, set())",
                                       "return current in TRANSITIONS.get(target, set())"),),
              "test_open_task_can_be_closed", "Open tasks cannot be closed", "open -> closed is allowed", "409"),
    ), p_transitions),
    Category("database_query_mistakes", "db_query", "SQL queries touch or count the wrong rows", (
        Fault("count_ignores_filter", ((S, "total = self.tasks.count(where_sql, args)", 'total = self.tasks.count("1=1", [])'),),
              "test_total_respects_filters", "meta.total ignores filters", "total counts only matching tasks",
              "total counts every task"),
        Fault("owner_or_assignee", ((REPO, '            sql += " WHERE owner_id = ?"\n            args.append(owner_id)\n        sql += " GROUP BY status"',
                                     '            sql += " WHERE owner_id = ? OR assignee_id = ?"\n            args.extend([owner_id, owner_id])\n        sql += " GROUP BY status"'),),
              "test_stats_for_owner", "stats?owner_id= also counts tasks assigned to the user",
              "only tasks owned by owner_id are counted", "assigned tasks are included"),
        Fault("update_range", ((REPO, "WHERE id = ?\", args)", "WHERE id >= ?\", args)"),),
              "test_update_changes_only_target_task", "Editing one task renames later tasks too",
              "PATCH changes only the target task", "every task with a higher id is changed"),
        Fault("limit_offset_swapped", ((REPO, "[*args, limit, offset]", "[*args, offset, limit]"),),
              "test_first_page_is_not_empty", "The first page of /tasks is empty", "page 1 contains tasks",
              "items is []"),
        Fault("delete_by_owner", ((REPO, 'conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))',
                                   'conn.execute("DELETE FROM tasks WHERE owner_id = (SELECT owner_id FROM tasks WHERE id = ?)", (task_id,))'),),
              "test_delete_removes_only_target", "Deleting a task deletes all of the owner's tasks",
              "only the target task is deleted", "all tasks of that owner disappear"),
    ), p_db_query),
    Category("incorrect_aggregation", "aggregation", "Task statistics are computed incorrectly", (
        Fault("closed_not_finished", ((S, "finished = sum(counts[s] for s in TERMINAL_STATUSES)", 'finished = counts["done"]'),),
              "test_completion_rate_counts_closed_tasks", "completion_rate ignores closed tasks",
              "done and closed both count as finished", "closed tasks are not counted"),
        Fault("average_floor", ((S, "round(sum(priorities) / len(priorities), 2)", "round(sum(priorities) // len(priorities), 2)"),),
              "test_average_priority_keeps_fraction", "average_priority is truncated to an integer",
              "average_priority keeps two decimals", "the fraction is dropped"),
        Fault("open_count_only_open", ((S, '"open_count": total - finished,', '"open_count": counts["open"],'),),
              "test_open_count_includes_active_tasks", "open_count ignores in-progress and blocked tasks",
              "open_count counts every unfinished task", "only status=open is counted"),
        Fault("rate_two_decimals", ((S, "round(finished / total, 4)", "round(finished / total, 2)"),),
              "test_completion_rate_has_four_decimals", "completion_rate is rounded to 2 decimals",
              "completion_rate has 4 decimals", "it has only 2"),
        Fault("missing_status_keys", ((REPO, "counts = {status: 0 for status in STATUSES}", "counts = {}"),),
              "test_stats_with_no_finished_tasks", "/tasks/stats returns 500 when some statuses are unused",
              "by_status lists every status (zero when unused)", "500 internal_error"),
    ), p_aggregation),
    Category("input_validation_failures", "input_validation", "Invalid input is accepted", (
        Fault("email_no_tld", ((V, r'EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$")', r'EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+$")'),),
              "test_email_requires_top_level_domain", "Emails without a domain suffix are accepted",
              "emails need a dot and a TLD", "201"),
        Fault("username_any_chars", ((V, r'USERNAME_RE = re.compile(r"^[a-z0-9_]{3,32}$")', r'USERNAME_RE = re.compile(r"^\S{3,32}$")'),),
              "test_username_rejects_symbols", "Usernames with punctuation are accepted",
              "usernames are [a-z0-9_]{3,32}", "201"),
        Fault("unknown_fields_allowed", ((V, "unknown = set(data) - TASK_FIELDS\n",
                                          'unknown = set(data) - TASK_FIELDS - {"owner_id", "id", "ticket_number", "created_at"}\n'),),
              "test_create_rejects_unknown_fields", "Server-managed fields are silently accepted on create",
              "unknown or read-only fields are rejected with 422", "201"),
        Fault("password_min_6", ((V, "len(password) < PASSWORD_MIN:", "len(password) < PASSWORD_MIN - 2:"),),
              "test_short_password_rejected", "6 and 7 character passwords are accepted",
              "passwords need at least 8 characters", "201"),
        Fault("title_coerced", ((V, '    if not isinstance(value, str):\n        raise ValidationError("title must be a string", {"title": "invalid"})\n    title = value.strip()\n',
                                 "    title = str(value).strip()\n"),),
              "test_non_string_title_rejected", "Non-string titles are converted to text and accepted",
              "a non-string title is rejected with 422", "201"),
    ), p_input_validation),
    Category("file_path_handling", "file_paths", "Attachment filenames are sanitised incorrectly", (
        Fault("backslash_kept", ((ATT, 'base = os.path.basename(name.replace("\\\\", "/")).strip()', "base = os.path.basename(name).strip()"),),
              "test_windows_path_reduced_to_basename", "Windows-style paths are stored verbatim",
              "C:\\\\dir\\\\file.txt is stored as file.txt", "the full path becomes the filename"),
        Fault("hidden_allowed", ((ATT, 'if base in ("", ".", "..") or base.startswith("."):', 'if base in ("", ".", ".."):'),),
              "test_hidden_filename_rejected", "Hidden dot-files can be uploaded", "dot-files are rejected with 422", "201"),
        Fault("spaces_removed", ((ATT, 'base = base.replace(" ", "_")', 'base = base.replace(" ", "")'),),
              "test_spaces_replaced_with_underscores", "Spaces in filenames are dropped",
              "spaces become underscores", "spaces disappear"),
        Fault("nested_dirs", ((ATT, 'base = os.path.basename(name.replace("\\\\", "/")).strip()', 'base = name.replace("\\\\", "/").strip()'),),
              "test_nested_path_reduced_to_basename", "Uploading reports/x/file.txt creates sub-directories",
              "only the basename is stored", "a nested directory is created"),
    ), p_file_paths),
    Category("incorrect_fallback", "fallback", "Fallback to defaults does not happen", (
        Fault("invalid_int_zero", ((C, "        except (TypeError, ValueError):\n            return None", "        except (TypeError, ValueError):\n            return 0"),),
              "test_invalid_env_value_uses_default", "A non-numeric TRACKER_MAX_PAGE_SIZE sets the limit to 0",
              "invalid values fall back to the default", "max_page_size becomes 0"),
        Fault("non_positive_kept", ((C, "return number if number > 0 else None", "return number"),),
              "test_non_positive_env_value_uses_default", "TRACKER_DEFAULT_PAGE_SIZE=0 is used as-is",
              "non-positive numbers fall back to the default", "page size 0 / negative"),
        Fault("file_over_env", ((C, 'for source in (overrides.get(name), env.get("TRACKER_" + name.upper()), file_values.get(name)):',
                                 'for source in (overrides.get(name), file_values.get(name), env.get("TRACKER_" + name.upper())):'),),
              "test_env_overrides_config_file", "Config file values override environment variables",
              "environment variables take precedence over the config file", "the file value wins"),
        Fault("bad_file_crash", ((C, "except (OSError, json.JSONDecodeError):", "except OSError:"),),
              "test_malformed_config_file_ignored", "A malformed config file crashes startup",
              "a broken config file is ignored", "JSONDecodeError"),
        Fault("display_name_blank", ((SER, "    if user.full_name and user.full_name.strip():\n        return user.full_name.strip()\n    return user.username",
                                      '    return (user.full_name or "").strip()'),),
              "test_display_name_falls_back_to_username", "display_name is empty for users without a full name",
              "display_name falls back to the username", "display_name is \"\""),
    ), p_fallback),
    Category("error_propagation_bugs", "error_propagation", "Error responses lose information or status", (
        Fault("not_found_message", ((REPO, '        if row is None:\n            raise NotFoundError(f"task {task_id} not found")\n        return Task.from_row(row)',
                                     '        if row is None:\n            raise NotFoundError("not found")\n        return Task.from_row(row)'),),
              "test_error_body_has_code_and_message", "404 responses do not say which task is missing",
              "the message names the missing task id", "message is just 'not found'"),
        Fault("details_dropped", ((E, '        body = {"code": self.code, "message": self.message}\n        if self.details:\n            body["details"] = self.details\n',
                                   '        body = {"code": self.code, "message": self.message}\n'),),
              "test_validation_details_returned", "Validation errors no longer include field details",
              "error.details lists offending fields", "details is missing"),
        Fault("transition_500", ((E, "class InvalidTransitionError(ConflictError):", "class InvalidTransitionError(ApiError):"),),
              "test_invalid_transition_is_conflict", "Invalid status transitions return 500",
              "409 invalid_transition", "500"),
        Fault("empty_default_message", ((E, 'self.message = message or self.code.replace("_", " ")', "self.message = message"),),
              "test_default_error_messages", "Errors raised without a message have an empty message",
              "a default message derived from the code", "message is \"\""),
    ), p_error_propagation),
    Category("resource_cleanup_issues", "resource_cleanup", "Connections, files or cache entries leak", (
        Fault("connection_leak", ((DB, "        conn = self._connect()\n        try:\n            yield conn\n        finally:\n            self._close(conn)\n\n    @contextmanager\n    def transaction",
                                   "        conn = self._connect()\n        yield conn\n        self._close(conn)\n\n    @contextmanager\n    def transaction"),),
              "test_connection_closed_after_error", "Database connections leak when a query raises",
              "connections are always closed", "open_connections keeps growing"),
        Fault("transaction_leak", ((DB, "            conn.rollback()\n            raise\n        finally:\n            self._close(conn)",
                                    "            conn.rollback()\n            raise\n        else:\n            self._close(conn)"),),
              "test_failed_transaction_releases_connection", "Failed transactions leave connections open",
              "connections are released after rollback", "open_connections > 0"),
        Fault("file_not_closed", ((ATT, '        with open(path, "w", encoding="utf-8") as handle:\n            handle.write(content)',
                                   '        handle = open(path, "w", encoding="utf-8")\n        handle.write(content)\n        handle.flush()'),),
              "test_attachment_file_handle_closed", "Attachment uploads leak file handles",
              "file handles are closed after writing", "handles stay open"),
        Fault("expired_not_evicted", ((CACHE, "                del self._data[key]\n                self.misses += 1",
                                       "                self.misses += 1"),),
              "test_expired_cache_entries_removed", "Expired cache entries are never removed (memory grows)",
              "expired entries are deleted on access", "they stay in the cache"),
    ), p_resource_cleanup),
    Category("concurrency_defects", "concurrency", "Ticket numbers are duplicated under concurrent requests", (
        Fault("no_lock", ((SEQ, "        with self._lock:\n            current = self._next\n            self._store(current + 1)\n            self.issued.append(current)\n            return current",
                           "        current = self._next\n        self._store(current + 1)\n        self.issued.append(current)\n        return current"),),
              "test_concurrent_ticket_numbers_are_unique", "Concurrent task creation produces duplicate ticket numbers",
              "every ticket number is unique", "two tasks share a number"),
        Fault("lock_read_only", ((SEQ, "        with self._lock:\n            current = self._next\n            self._store(current + 1)\n            self.issued.append(current)\n            return current",
                                  "        with self._lock:\n            current = self._next\n        self._store(current + 1)\n        self.issued.append(current)\n        return current"),),
              "test_concurrent_ticket_numbers_are_unique", "Duplicate ticket numbers under load (lock looks present)",
              "read-and-increment is atomic", "duplicates appear"),
        Fault("lock_write_only", ((SEQ, "        with self._lock:\n            current = self._next\n            self._store(current + 1)\n            self.issued.append(current)\n            return current",
                                   "        current = self._next\n        with self._lock:\n            self._store(current + 1)\n        self.issued.append(current)\n        return current"),),
              "test_concurrent_ticket_numbers_are_unique", "Ticket numbers repeat when requests arrive together",
              "read-and-increment is atomic", "duplicates appear"),
    ), p_concurrency),
    Category("type_conversion_bugs", "type_conversion", "Query/JSON values are converted to the wrong types", (
        Fault("bool_case", ((CONV, "    text = str(value).strip().lower()", "    text = str(value).strip()"),),
              "test_boolean_query_is_case_insensitive", "overdue=True is rejected", "booleans are case-insensitive", "422"),
        Fault("truthy_string", ((CONV, "    if isinstance(value, bool):\n        return value\n    text",
                                 "    if isinstance(value, (bool, str)):\n        return bool(value)\n    text"),),
              "test_false_string_means_false", "overdue=false behaves like overdue=true",
              "'false'/'0'/'no' mean False", "any non-empty string is True"),
        Fault("float_truncated", ((CONV, '    if isinstance(value, float):\n        if value.is_integer():\n            return int(value)\n        raise ValidationError(f"{name} must be an integer", {name: "not_an_integer"})',
                                   "    if isinstance(value, float):\n        return int(value)"),),
              "test_fractional_priority_rejected", "priority=2.5 is silently truncated", "fractional numbers are rejected",
              "201 with priority 2"),
        Fault("bool_as_int", ((CONV, '    if isinstance(value, bool):\n        raise ValidationError(f"{name} must be an integer", {name: "not_an_integer"})\n    if isinstance(value, int):',
                               "    if isinstance(value, int):"),),
              "test_boolean_priority_rejected", "priority=true is accepted as 1", "booleans are not integers", "201"),
    ), p_type_conversion),
    Category("incorrect_status_codes", "status_codes", "Endpoints return the wrong HTTP status codes", (
        Fault("create_200", ((API, "        return Response(status, body)", "        return Response(200, body)"),),
              "test_create_returns_201", "POST /tasks returns 200", "201 Created", "200"),
        Fault("delete_200", ((API, "        return Response(204, None)", '        return Response(200, {"deleted": True})'),),
              "test_delete_returns_204_without_body", "DELETE returns 200 with a body", "204 with no body", "200"),
        Fault("register_200", ((API, "        return Response(201, users.get_profile(user, user.id))", "        return users.get_profile(user, user.id)"),),
              "test_register_returns_201", "POST /users returns 200", "201 Created", "200"),
        Fault("attachment_200", ((API, '        return Response(201, {"filename": name, "size": len(content)})', '        return {"filename": name, "size": len(content)}'),),
              "test_attachment_upload_returns_201", "Attachment upload returns 200", "201 Created", "200"),
        Fault("validation_400", ((E, "class ValidationError(ApiError):\n    status = 422", "class ValidationError(ApiError):\n    status = 400"),),
              "test_validation_error_returns_422", "Validation errors return 400", "422", "400"),
        Fault("forbidden_401", ((E, "class PermissionDeniedError(ApiError):\n    status = 403", "class PermissionDeniedError(ApiError):\n    status = 401"),),
              "test_forbidden_returns_403", "Permission errors return 401", "403 forbidden", "401"),
    ), p_status_codes),
    Category("cache_invalidation_mistakes", "cache_invalidation", "Cached data goes stale after writes", (
        Fault("patch_stale", ((S, "        updated = self.tasks.update(task_id, changes, self._now_iso())\n        self._invalidate(task_id)\n",
                               "        updated = self.tasks.update(task_id, changes, self._now_iso())\n"),),
              "test_get_after_patch_is_fresh", "GET returns the old title after PATCH", "GET reflects the update",
              "stale title"),
        Fault("status_stale", ((S, '        updated = self.tasks.update(task_id, {"status": target}, self._now_iso())\n        self._invalidate(task_id)\n',
                                '        updated = self.tasks.update(task_id, {"status": target}, self._now_iso())\n'),),
              "test_get_after_status_change_is_fresh", "GET returns the old status after a status change",
              "GET reflects the new status", "stale status"),
        Fault("delete_stale", ((S, "        self.tasks.delete(task_id)\n        self._invalidate(task_id)\n", "        self.tasks.delete(task_id)\n"),),
              "test_get_after_delete_is_404", "Deleted tasks are still returned by GET", "404 after delete", "200"),
        Fault("create_stats_stale", ((S, '        self.cache.invalidate_prefix("stats:")\n        result = (201,', "        result = (201,"),),
              "test_stats_refresh_after_create", "/tasks/stats does not count newly created tasks",
              "stats include new tasks", "stale totals"),
        Fault("invalidate_skips_stats", ((S, '        self.cache.invalidate(f"task:{task_id}")\n        self.cache.invalidate_prefix("stats:")',
                                          '        self.cache.invalidate(f"task:{task_id}")'),),
              "test_stats_refresh_after_status_change", "/tasks/stats ignores status changes",
              "stats reflect status changes", "stale by_status"),
    ), p_cache),
]

CATEGORY_BY_NAME = {c.name: c for c in CATEGORIES}
assert len(CATEGORIES) == 25, len(CATEGORIES)


def variation(category_name, v):
    """Return (category, fault, case) for variation v of a category."""
    category = CATEGORY_BY_NAME[category_name]
    fault = category.faults[v % len(category.faults)]
    rng = random.Random(f"{category_name}:{v}")
    case = category.params(rng, fault.id)
    return category, fault, case


def default_case(category_name):
    """Parameters used when a category's checks run as part of the hidden regression suite."""
    category = CATEGORY_BY_NAME[category_name]
    return category.params(random.Random(f"{category_name}:regression"), None)
