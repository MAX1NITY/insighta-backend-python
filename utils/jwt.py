import os
import jwt
from datetime import datetime, timezone, timedelta

JWT_SECRET = os.getenv("JWT_SECRET")
JWT_REFRESH_SECRET = os.getenv("JWT_REFRESH_SECRET")

def create_access_token(data: dict) -> str:
    payload = data.copy()
    payload["exp"] = datetime.now(timezone.utc) + timedelta(minutes=3)
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

def create_refresh_token(data: dict) -> str:
    payload = data.copy()
    payload["exp"] = datetime.now(timezone.utc) + timedelta(minutes=5)
    return jwt.encode(payload, JWT_REFRESH_SECRET, algorithm="HS256")

def decode_access_token(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])

def decode_refresh_token(token: str) -> dict:
    return jwt.decode(token, JWT_REFRESH_SECRET, algorithms=["HS256"])