import os
import time
import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from dotenv import load_dotenv
from middleware.version_check import VersionCheckMiddleware
from routers import auth, profiles

load_dotenv()

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Rate limiter
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="Insighta Labs+ API")

# Rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("WEB_PORTAL_URL", "")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Version check
app.add_middleware(VersionCheckMiddleware)

# Request logging
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    duration = round((time.time() - start_time) * 1000, 2)
    logger.info(
        f"{request.method} {request.url.path} "
        f"{response.status_code} {duration}ms"
    )
    return response

# Routers
app.include_router(auth.router)
app.include_router(profiles.router)

@app.get("/")
async def root():
    return {"status": "success", "message": "Insighta Labs+ API is ready"}