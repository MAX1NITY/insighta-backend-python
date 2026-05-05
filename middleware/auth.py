import jwt
from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from utils.jwt import decode_access_token
from utils.supabase import supabase

security = HTTPBearer(auto_error=False)

async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    token = None

    if credentials:
        token = credentials.credentials

    if not token:
        token = request.cookies.get("access_token")

    if not token:
        raise HTTPException(status_code=401, detail={
            "status": "error",
            "message": "Authentication token required"
        })

    try:
        payload = decode_access_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=403, detail={
            "status": "error",
            "message": "Invalid or expired token"
        })
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=403, detail={
            "status": "error",
            "message": "Invalid or expired token"
        })

    # Use "id" claim — not "sub"
    user_id = payload.get("id")
    if not user_id:
        raise HTTPException(status_code=403, detail={
            "status": "error",
            "message": "Invalid token claims"
        })

    try:
        result = supabase.from_("users") \
            .select("*") \
            .eq("id", user_id) \
            .single() \
            .execute()
        user = result.data
    except Exception:
        user = None

    if not user:
        raise HTTPException(status_code=404, detail={
            "status": "error",
            "message": "User not found"
        })

    if not user.get("is_active"):
        raise HTTPException(status_code=403, detail={
            "status": "error",
            "message": "Account is deactivated"
        })

    return user


def require_role(role: str):
    async def role_checker(
        current_user: dict = Depends(get_current_user)
    ):
        if current_user.get("role") != role:
            raise HTTPException(status_code=403, detail={
                "status": "error",
                "message": "Forbidden"
            })
        return current_user
    return role_checker