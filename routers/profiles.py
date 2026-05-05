import os
import csv
import httpx
from io import StringIO
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Query, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from utils.supabase import supabase
from middleware.auth import get_current_user, require_role

router = APIRouter(prefix="/api", tags=["profiles"])




def get_age_group(age: int) -> str:
    if age <= 12:
        return "child"
    elif age <= 19:
        return "teenager"
    elif age <= 59:
        return "adult"
    else:
        return "senior"


def extract_filters(query_text: str) -> dict:
    filters = {}
    q = query_text.lower()

    if "female" in q or "women" in q:
        filters["gender"] = "female"
    elif "male" in q or "men" in q:
        filters["gender"] = "male"

    if "young" in q:
        filters["min_age"] = 16
        filters["max_age"] = 24
    if "teenager" in q:
        filters["age_group"] = "teenager"
    if "adult" in q:
        filters["age_group"] = "adult"
    if "senior" in q:
        filters["age_group"] = "senior"
    if "child" in q:
        filters["age_group"] = "child"

    # Extract numbers for age ranges
    import re
    numbers = re.findall(r'\d+', q)
    if numbers:
        val = int(numbers[0])
        if any(word in q for word in ["above", "over", "older"]):
            filters["min_age"] = val
        if any(word in q for word in ["under", "below", "younger"]):
            filters["max_age"] = val

    countries = {
        "nigeria": "NG", "kenya": "KE", "angola": "AO",
        "benin": "BJ", "ghana": "GH", "south africa": "ZA",
        "united states": "US", "usa": "US", "uk": "GB",
        "united kingdom": "GB", "canada": "CA", "australia": "AU"
    }
    for name, code in countries.items():
        if name in q:
            filters["country_id"] = code

    return filters


def build_profile_query(
    query,
    gender=None,
    country_id=None,
    age_group=None,
    min_age=None,
    max_age=None
):
    if gender:
        query = query.ilike("gender", gender)
    if country_id:
        query = query.ilike("country_id", country_id)
    if age_group:
        query = query.ilike("age_group", age_group)
    if min_age:
        query = query.gte("age", min_age)
    if max_age:
        query = query.lte("age", max_age)
    return query


def build_pagination_links(request: Request, page: int, limit: int, total_pages: int, extra_params: str = "") -> dict:
    base = str(request.url).split("?")[0]
    return {
        "self": f"{base}?page={page}&limit={limit}{extra_params}",
        "next": f"{base}?page={page + 1}&limit={limit}{extra_params}" if page < total_pages else None,
        "prev": f"{base}?page={page - 1}&limit={limit}{extra_params}" if page > 1 else None
    }


# ─── GET /api/profiles ────────────────────────────────────────────

@router.get("/profiles")
async def list_profiles(
    request: Request,
    gender: str = None,
    country_id: str = None,
    age_group: str = None,
    min_age: int = None,
    max_age: int = None,
    sort_by: str = "created_at",
    order: str = "desc",
    page: int = 1,
    limit: int = 10,
    current_user: dict = Depends(get_current_user)
):
    valid_sorts = ["age", "gender_probability", "created_at", "name"]
    if sort_by not in valid_sorts:
        raise HTTPException(status_code=400, detail={
            "status": "error",
            "message": "Invalid sort field"
        })

    limit = max(1, min(50, limit))
    page = max(1, page)
    offset = (page - 1) * limit

    try:
        query = supabase.from_("profiles").select("*", count="exact")
        query = build_profile_query(query, gender, country_id, age_group, min_age, max_age)

        ascending = order == "asc"
        result = query.order(sort_by, desc=not ascending).range(offset, offset + limit - 1).execute()

        total = result.count or 0
        total_pages = -(-total // limit)  # ceiling division

        links = build_pagination_links(request, page, limit, total_pages)

        return {
            "status": "success",
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": total_pages,
            "links": links,
            "data": result.data or []
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail={
            "status": "error",
            "message": "Server failure"
        })


# ─── POST /api/profiles ───────────────────────────────────────────

class CreateProfileRequest(BaseModel):
    name: str


@router.post("/profiles", status_code=201)
async def create_profile(
    body: CreateProfileRequest,
    current_user: dict = Depends(require_role("admin"))
):
    name = body.name.strip()

    if not name:
        raise HTTPException(status_code=400, detail={
            "status": "error",
            "message": "Missing or empty parameter"
        })

    # Check if profile already exists
    existing = supabase.from_("profiles").select("*").ilike("name", name).execute()
    if existing.data:
        return {
            "status": "success",
            "message": "Profile already exists",
            "data": existing.data[0]
        }

    # Fetch from external APIs
    try:
        import asyncio
        async with httpx.AsyncClient() as client:
            g_res, a_res, n_res = await asyncio.gather(
                client.get(f"https://api.genderize.io?name={name}"),
                client.get(f"https://api.agify.io?name={name}"),
                client.get(f"https://api.nationalize.io?name={name}")
            )
        gender_data = g_res.json()
        age_data = a_res.json()
        nation_data = n_res.json()

    except Exception:
        raise HTTPException(status_code=502, detail={
            "status": "error",
            "message": "Server failure"
        })

    if not gender_data.get("gender"):
        raise HTTPException(status_code=502, detail={
            "status": "error", "message": "Server failure"
        })

    if not age_data.get("age"):
        raise HTTPException(status_code=502, detail={
            "status": "error", "message": "Server failure"
        })

    if not nation_data.get("country"):
        raise HTTPException(status_code=502, detail={
            "status": "error", "message": "Server failure"
        })

    # Get country name
    import pycountry
    country_code = nation_data["country"][0]["country_id"]
    try:
        country = pycountry.countries.get(alpha_2=country_code)
        country_name = country.name if country else "Unknown"
    except Exception:
        country_name = "Unknown"

    import uuid
    new_profile = {
        "id": str(uuid.uuid4()),
        "name": name,
        "gender": gender_data.get("gender", "unknown"),
        "gender_probability": float(gender_data.get("probability", 0)),
        "age": int(age_data.get("age", 0)),
        "age_group": get_age_group(int(age_data.get("age", 0))),
        "country_id": country_code,
        "country_name": country_name,
        "country_probability": float(nation_data["country"][0].get("probability", 0)),
        "created_at": datetime.now(timezone.utc).isoformat()
    }

    result = supabase.from_("profiles").insert(new_profile).execute()

    if not result.data:
        raise HTTPException(status_code=500, detail={
            "status": "error",
            "message": "Server failure"
        })

    return {
        "status": "success",
        "data": result.data[0]
    }


# ─── GET /api/profiles/search ─────────────────────────────────────

@router.get("/profiles/search")
async def search_profiles(
    request: Request,
    q: str = None,
    sort_by: str = "created_at",
    order: str = "desc",
    page: int = 1,
    limit: int = 10,
    current_user: dict = Depends(get_current_user)
):
    if not q:
        raise HTTPException(status_code=400, detail={
            "status": "error",
            "message": "Unable to interpret query"
        })

    limit = max(1, min(50, limit))
    page = max(1, page)
    offset = (page - 1) * limit

    filters = extract_filters(q)
    ascending = order == "asc"

    try:
        query = supabase.from_("profiles").select("*", count="exact")

        if filters:
            query = build_profile_query(
                query,
                gender=filters.get("gender"),
                country_id=filters.get("country_id"),
                age_group=filters.get("age_group"),
                min_age=filters.get("min_age"),
                max_age=filters.get("max_age")
            )
        else:
            query = query.ilike("name", f"%{q}%")

        result = query.order(sort_by, desc=not ascending).range(offset, offset + limit - 1).execute()

        total = result.count or 0
        total_pages = -(-total // limit)

        extra = f"&q={q}"
        links = build_pagination_links(request, page, limit, total_pages, extra)

        return {
            "status": "success",
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": total_pages,
            "links": links,
            "data": result.data or []
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail={
            "status": "error",
            "message": "Server failure"
        })


# ─── GET /api/profiles/export ─────────────────────────────────────

@router.get("/profiles/export")
async def export_profiles(  
    request: Request,
    x_api_version: str = Header(..., alias="X-API-Version"),
    gender: str = None,
    country_id: str = None,
    age_group: str = None,
    min_age: int = None,
    max_age: int = None,
    sort_by: str = "created_at",
    order: str = "desc",
    current_user: dict = Depends(require_role("admin"))
):
    valid_sorts = ["age", "gender_probability", "created_at", "name"]
    sort_by = sort_by if sort_by in valid_sorts else "created_at"
    ascending = order == "asc"

    try:
        query = supabase.from_("profiles").select(
            "id, name, gender, gender_probability, age, age_group, "
            "country_id, country_name, country_probability, created_at"
        )
        query = build_profile_query(query, gender, country_id, age_group, min_age, max_age)
        result = query.order(sort_by, desc=not ascending).execute()

        profiles = result.data or []

        # Build CSV with exact column order
        columns = [
            "id", "name", "gender", "gender_probability",
            "age", "age_group", "country_id", "country_name",
            "country_probability", "created_at"
        ]

        output = StringIO()
        writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(profiles)

        output.seek(0)
        timestamp = int(datetime.now(timezone.utc).timestamp() * 1000)

        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename=profiles_{timestamp}.csv"
            }
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail={
            "status": "error",
            "message": "Export failed"
        })


# ─── GET /api/profiles/:id ────────────────────────────────────────

@router.get("/profiles/{profile_id}")
async def get_profile(
    profile_id: str,
    current_user: dict = Depends(get_current_user)
):
    result = supabase.from_("profiles").select("*").eq("id", profile_id).single().execute()

    if not result.data:
        raise HTTPException(status_code=404, detail={
            "status": "error",
            "message": "Profile not found"
        })

    return {
        "status": "success",
        "data": result.data
    }


# ─── DELETE /api/profiles/:id ─────────────────────────────────────

@router.delete("/profiles/{profile_id}", status_code=204)
async def delete_profile(
    profile_id: str,
    current_user: dict = Depends(require_role("admin"))
):
    existing = supabase.from_("profiles").select("id").eq("id", profile_id).single().execute()

    if not existing.data:
        raise HTTPException(status_code=404, detail={
            "status": "error",
            "message": "Profile not found"
        })

    supabase.from_("profiles").delete().eq("id", profile_id).execute()
    return None


# ─── GET /api/me ──────────────────────────────────────────────────

@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    return {
        "status": "success",
        "data": {
            "id": current_user["id"],
            "username": current_user["username"],
            "email": current_user.get("email"),
            "avatar_url": current_user.get("avatar_url"),
            "role": current_user["role"],
            "is_active": current_user["is_active"]
        }
    }