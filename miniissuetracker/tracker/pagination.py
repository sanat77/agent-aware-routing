"""Page-number pagination."""
import math
from dataclasses import dataclass

from .convert import parse_int
from .errors import ValidationError


@dataclass(frozen=True)
class PageRequest:
    page: int
    per_page: int

    @property
    def offset(self):
        return (self.page - 1) * self.per_page

    @property
    def limit(self):
        return self.per_page


def parse_page_request(params, config):
    page = parse_int(params.get("page"), default=1, name="page")
    per_page = parse_int(params.get("per_page"), default=config.default_page_size, name="per_page")
    if page < 1:
        raise ValidationError("page must be >= 1", {"page": "out_of_range"})
    if per_page < 1:
        raise ValidationError("per_page must be >= 1", {"per_page": "out_of_range"})
    per_page = min(per_page, config.max_page_size)
    return PageRequest(page=page, per_page=per_page)


def page_metadata(total, request):
    total_pages = math.ceil(total / request.per_page) if total else 0
    return {
        "page": request.page,
        "per_page": request.per_page,
        "total": total,
        "total_pages": total_pages,
        "has_next": request.page < total_pages,
        "has_prev": request.page > 1,
    }
