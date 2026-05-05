import os
import hashlib
import base64
import httpx
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Request, HTTPException, Response, Query, Depends
from utils.limiter import limiter
from fastapi.responses import RedirectResponse, JSONResponse
from pydantic import BaseModel
from utils.supabase import supabase
from utils.jwt import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token
)
from middleware.auth import get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])

GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")
BACKEND_URL = os.getenv("BACKEND_URL")
WEB_PORTAL_URL = os.getenv("WEB_PORTAL_URL")


@router.get("/github")
async def github_login(request: Request):
    state = request.query_params.get("state")
    code_verifier = request.query_params.get("code_verifier")

    if not state:
        raise HTTPException(status_code=400, detail={
            "status": "error",
            "message": "Missing state parameter"
        })

    # Store state + code_verifier in auth_state
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    
    result = supabase.from_("auth_state").insert({
        "state": state,
        "code_verifier": code_verifier,  # None for web flow
        "expires_at": expires_at.isoformat()
    }).execute()

    if not result.data:
        raise HTTPException(status_code=500, detail={
            "status": "error",
            "message": "Failed to initiate auth"
        })

    # Redirect to GitHub
    params = {
        "client_id": GITHUB_CLIENT_ID,
        "redirect_uri": f"{BACKEND_URL}/auth/github/callback",
        "scope": "user:email",
        "state": state
    }
    query_string = "&".join(f"{k}={v}" for k, v in params.items())
    return RedirectResponse(
        url=f"https://github.com/login/oauth/authorize?{query_string}"
    )


@router.get("/github/callback")
async def github_callback(request: Request, response: Response):
    code = request.query_params.get("code")
    state = request.query_params.get("state")

    # 1. Validate state exists
    if not state:
        raise HTTPException(status_code=400, detail={
            "status": "error",
            "message": "Missing state parameter"
        })

    # 2. Look up state in Supabase
    try:
        result = supabase.from_("auth_state") \
            .select("*") \
            .eq("state", state) \
            .single() \
            .execute()
        pending = result.data
    except Exception:
        pending = None

    # 3. Validate pending exists and not expired
    if not pending:
        raise HTTPException(status_code=400, detail={
            "status": "error",
            "message": "Invalid or expired state"
        })

    expires_at = datetime.fromisoformat(
        pending["expires_at"].replace("Z", "+00:00")
    )
    if datetime.now(timezone.utc) > expires_at:
        supabase.from_("auth_state").delete().eq("state", state).execute()
        raise HTTPException(status_code=400, detail={
            "status": "error",
            "message": "Invalid or expired state"
        })

    # 4. Detect CLI vs web flow
    is_cli = pending.get("code_verifier") is not None
    code_verifier = pending.get("code_verifier")

    # 5. Clean up — single use
    supabase.from_("auth_state").delete().eq("state", state).execute()

    if not code:
        raise HTTPException(status_code=400, detail={
            "status": "error",
            "message": "No code from GitHub"
        })

    # 6. Exchange code with GitHub
    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            "https://github.com/login/oauth/access_token",
            json={
                "client_id": GITHUB_CLIENT_ID,
                "client_secret": GITHUB_CLIENT_SECRET,
                "code": code,
                **({"code_verifier": code_verifier} if is_cli and code_verifier else {})
            },
            headers={"Accept": "application/json"}
        )
        token_data = token_response.json()

    github_access_token = token_data.get("access_token")
    if not github_access_token:
        raise HTTPException(status_code=400, detail={
            "status": "error",
            "message": "Failed to get GitHub token"
        })

    # 7. Get GitHub user info
    async with httpx.AsyncClient() as client:
        user_response = await client.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {github_access_token}"}
        )
        github_user = user_response.json()

        # Fetch email separately
        email_response = await client.get(
            "https://api.github.com/user/emails",
            headers={"Authorization": f"Bearer {github_access_token}"}
        )
        emails = email_response.json()

    primary_email = next(
        (e["email"] for e in emails if e.get("primary") and e.get("verified")),
        None
    )

    # 8. Upsert user in Supabase
    upsert_result = supabase.from_("users").upsert({
        "github_id": str(github_user["id"]),
        "username": github_user["login"],
        "email": primary_email,
        "avatar_url": github_user.get("avatar_url"),
        "last_login_at": datetime.now(timezone.utc).isoformat()
    }, on_conflict="github_id").execute()

    user = upsert_result.data[0] if upsert_result.data else None

    if not user:
        raise HTTPException(status_code=500, detail={
            "status": "error",
            "message": "Failed to create user"
        })

    token_payload = {
        "id": user["id"],
        "role": user.get("role", "analyst")
    }

    # 9. Issue tokens
    access_token = create_access_token(token_payload)
    refresh_token = create_refresh_token({"id": user["id"]})

    # 10. Respond based on flow
    if is_cli:
        return RedirectResponse(
            url=f"http://localhost:3000?access_token={access_token}&refresh_token={refresh_token}"
        )

    # Web — set HttpOnly cookies
    web_response = RedirectResponse(
    url=f"{WEB_PORTAL_URL}/dashboard",
    status_code=302
)
    web_response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=180  # 3 minutes
    )
    web_response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=300  # 5 minutes
    )
    return web_response


class RefreshRequest(BaseModel):
    refresh_token: str



@router.get("/me")
async def read_users_me(current_user: dict = Depends(get_current_user)):
    return {
        "status": "success",
        "data": {
            "id": current_user["id"],
            "username": current_user["github_username"],
            "role": current_user["role"],
            "email": current_user.get("email")
        }
    }


@router.post("/refresh")
async def refresh_token(body: RefreshRequest):
    if not body.refresh_token:
        raise HTTPException(status_code=400, detail={
            "status": "error",
            "message": "Refresh token required"
        })

    try:
        payload = decode_refresh_token(body.refresh_token)
    except Exception:
        raise HTTPException(status_code=403, detail={
            "status": "error",
            "message": "Invalid refresh token"
        })

    result = supabase.from_("users").select("*").eq("id", payload["id"]).single().execute()
    user = result.data

    if not user or not user.get("is_active"):
        raise HTTPException(status_code=403, detail={
            "status": "error",
            "message": "User not found or inactive"
        })

    new_access_token = create_access_token(user["id"], user["role"])
    new_refresh_token = create_refresh_token(user["id"])

    return {
        "status": "success",
        "access_token": new_access_token,
        "refresh_token": new_refresh_token
    }


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(
        key="access_token",
        httponly=True,
        secure=True,
        samesite="none"
    )
    response.delete_cookie(
        key="refresh_token",
        httponly=True,
        secure=True,
        samesite="none"
    )
    return {
        "status": "success",
        "message": "Logged out successfully."
    }

@limiter.limit("10/minute")
async def github_login(
    request: Request, 
    state: str = Query(...), 
    code_verifier: str = Query(None)
):
    try:
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()

        data = {
            "state": state,
            "code_verifier": code_verifier,
            "expires_at": expires_at
        }
        
        supabase.table("auth_state").insert(data).execute()

        client_id = os.getenv("GITHUB_CLIENT_ID")
        redirect_uri = f"{os.getenv('BACKEND_URL')}/auth/github/callback"
        
        github_url = (
            f"https://github.com/login/oauth/authorize?"
            f"client_id={client_id}&"
            f"redirect_uri={redirect_uri}&"
            f"state={state}&"
            f"scope=user:email"
        )

        return RedirectResponse(url=github_url)

    except Exception as e:
        return HTTPException(
            status_code=500, 
            detail={"status": "error", "message": str(e)}
        )