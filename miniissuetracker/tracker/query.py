"""Translate list-endpoint query parameters into SQL WHERE / ORDER BY clauses."""
from .convert import parse_bool, parse_int
from .errors import ValidationError
from .models import STATUSES, TERMINAL_STATUSES

SORTABLE_FIELDS = ("id", "title", "priority", "status", "created_at", "updated_at", "due_at")
DEFAULT_SORT = [("id", "ASC")]


def parse_sort(value):
    """Parse 'priority,-created_at' into [('priority','ASC'), ('created_at','DESC'), ('id','ASC')].

    A leading '-' means descending. 'id' is appended as a tie-breaker so ordering is stable.
    """
    if value is None or not str(value).strip():
        return list(DEFAULT_SORT)
    order = []
    for raw in str(value).split(","):
        part = raw.strip()
        if not part:
            continue
        direction = "ASC"
        if part.startswith("-"):
            direction = "DESC"
            part = part[1:]
        if part not in SORTABLE_FIELDS:
            raise ValidationError(f"cannot sort by {part}", {"sort": "invalid"})
        order.append((part, direction))
    if not any(field == "id" for field, _ in order):
        order.append(("id", "ASC"))
    return order


def order_by_sql(order):
    clauses = []
    for field, direction in order:
        if field == "due_at":
            # tasks without a due date always sort last
            clauses.append(f"due_at IS NULL, due_at {direction}")
        elif field == "title":
            clauses.append(f"LOWER(title) {direction}")
        else:
            clauses.append(f"{field} {direction}")
    return ", ".join(clauses)


def build_filters(params, now_iso=None):
    """Return (where_sql, args). An empty filter returns ('1=1', [])."""
    clauses = []
    args = []
    status = params.get("status")
    if status:
        statuses = [s.strip() for s in str(status).split(",") if s.strip()]
        for item in statuses:
            if item not in STATUSES:
                raise ValidationError(f"unknown status {item}", {"status": "invalid"})
        clauses.append("status IN (%s)" % ", ".join("?" for _ in statuses))
        args.extend(statuses)
    assignee = params.get("assignee_id")
    if assignee is not None and assignee != "":
        if str(assignee).lower() == "none":
            clauses.append("assignee_id IS NULL")
        else:
            clauses.append("assignee_id = ?")
            args.append(parse_int(assignee, name="assignee_id"))
    owner = parse_int(params.get("owner_id"), name="owner_id")
    if owner is not None:
        clauses.append("owner_id = ?")
        args.append(owner)
    priority_min = parse_int(params.get("priority_min"), name="priority_min")
    if priority_min is not None:
        clauses.append("priority >= ?")
        args.append(priority_min)
    text = params.get("q")
    if text and str(text).strip():
        clauses.append("LOWER(title) LIKE ?")
        args.append("%" + str(text).strip().lower() + "%")
    tag = params.get("tag")
    if tag and str(tag).strip():
        clauses.append("tags LIKE ?")
        args.append('%"' + str(tag).strip().lower() + '"%')
    overdue = parse_bool(params.get("overdue"), name="overdue")
    if overdue is not None and now_iso is not None:
        terminal = ", ".join("?" for _ in TERMINAL_STATUSES)
        if overdue:
            clauses.append(f"(due_at IS NOT NULL AND due_at < ? AND status NOT IN ({terminal}))")
        else:
            clauses.append(f"NOT (due_at IS NOT NULL AND due_at < ? AND status NOT IN ({terminal}))")
        args.append(now_iso)
        args.extend(TERMINAL_STATUSES)
    return (" AND ".join(clauses) or "1=1"), args
