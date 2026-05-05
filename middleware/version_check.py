from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

class VersionCheckMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/api/"):
            if request.method == "OPTIONS":
                return await call_next(request)
            
            version = request.headers.get("X-API-Version")
            if not version:
                return JSONResponse(
                    status_code=400,
                    content={
                        "status": "error",
                        "message": "API version header required"
                    }
                )
        return await call_next(request)