import json

def normalize_filters(
    gender: str = None,
    country_id: str = None,
    age_group: str = None,
    min_age: int = None,
    max_age: int = None,
    sort_by: str = "created_at",
    order: str = "desc",
    page: int = 1,
    limit: int = 10
) -> dict:
    return {
        "gender": gender.lower().strip() if gender else None,
        "country_id": country_id.upper().strip() if country_id else None,
        "age_group": age_group.lower().strip() if age_group else None,
        "min_age": int(min_age) if min_age is not None else None,
        "max_age": int(max_age) if max_age is not None else None,
        "sort_by": sort_by.lower().strip() if sort_by else "created_at",
        "order": order.lower().strip() if order else "desc",
        "page": int(page),
        "limit": int(limit)
    }


def normalize_search_query(q: str) -> str:
    return q.lower().strip() if q else ""


def make_cache_key(prefix: str, normalized: dict) -> str:
    return f"{prefix}:{json.dumps(normalized, sort_keys=True)}"