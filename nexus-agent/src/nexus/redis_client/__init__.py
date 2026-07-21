"""Redis cache, pub/sub, rate limiting, and distributed lock client."""

from nexus.redis_client.cache import RedisCache
from nexus.redis_client.client import (
    close_redis,
    create_redis_client,
    get_redis,
    get_redis_client,
    health_check,
    init_redis,
    pubsub_channel,
    redis_health_check,
)
from nexus.redis_client.locks import LockAcquisitionError, distributed_lock
from nexus.redis_client.pubsub import (
    EventBus,
    agent_channel,
    tool_channel,
)
from nexus.redis_client.rate_limiter import (
    RateLimitError,
    SlidingWindowRateLimiter,
    TokenBucketRateLimiter,
)

__all__ = [
    "EventBus",
    "LockAcquisitionError",
    "RateLimitError",
    "RedisCache",
    "SlidingWindowRateLimiter",
    "TokenBucketRateLimiter",
    "agent_channel",
    "close_redis",
    "create_redis_client",
    "distributed_lock",
    "get_redis",
    "get_redis_client",
    "health_check",
    "init_redis",
    "pubsub_channel",
    "redis_health_check",
    "tool_channel",
]
