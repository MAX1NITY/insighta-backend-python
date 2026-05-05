import os
import json
from upstash_redis import Redis

redis = Redis(
    url=os.getenv("UPSTASH_REDIS_REST_URL"),
    token=os.getenv("UPSTASH_REDIS_REST_TOKEN")
)

def get_cache(key: str):
    try:
        data = redis.get(key)
        if data:
            return json.loads(data)
        return None
    except Exception:
        return None

def set_cache(key: str, value: dict, ttl: int = 300):
    try:
        redis.set(key, json.dumps(value), ex=ttl)
    except Exception:
        pass

def delete_cache(key: str):
    try:
        redis.delete(key)
    except Exception:
        pass

def flush_profiles_cache():
    try:
        keys = redis.keys("profiles:*")
        if keys:
            redis.delete(*keys)
    except Exception:
        pass