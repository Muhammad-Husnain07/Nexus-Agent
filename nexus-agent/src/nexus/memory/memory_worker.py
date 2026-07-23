"""Background memory extraction worker — polls Redis Stream for jobs.

Runs as a standalone process (not part of the FastAPI server).  Polls the
``memory_extraction_queue`` Redis Stream for pending memory extraction jobs
and processes them via ``MemoryManager.extract_and_store()``.

Usage:
    uv run python -m nexus.memory.memory_worker
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

import structlog

from nexus.config.settings import get_settings
from nexus.llm.client import LLMClient
from nexus.memory.manager import MemoryManager
from nexus.memory.store import MemoryStore
from nexus.redis_client.client import create_redis_client

logger = structlog.get_logger("nexus.memory.memory_worker")

_STREAM_KEY = "memory_extraction_queue"
_GROUP_NAME = "memory_workers"
_CONSUMER_NAME = "worker-1"
_POLL_INTERVAL_S = 1.0
_MAX_BATCH = 10


async def ensure_group(redis: Any) -> None:
    """Create the consumer group if it doesn't exist."""
    try:
        await redis.xgroup_create(_STREAM_KEY, _GROUP_NAME, id="0", mkstream=True)
    except Exception as exc:
        if "BUSYGROUP" not in str(exc):
            logger.warning("memory_worker.group_setup", error=str(exc))


async def process_job(job_data: dict[str, Any]) -> bool:
    """Process a single memory extraction job.

    Args:
        job_data: Dict with ``session_id`` and ``agent_state`` keys.

    Returns:
        True if successful, False on failure.
    """
    session_id = job_data.get("session_id", "")
    agent_state_raw = job_data.get("agent_state")
    if not session_id or not agent_state_raw:
        logger.warning("memory_worker.invalid_job", session_id=session_id)
        return False

    # agent_state might be a JSON string or already a dict
    agent_state: dict[str, Any] = agent_state_raw if isinstance(agent_state_raw, dict) else {}

    try:
        llm = LLMClient()
        manager = MemoryManager(store=MemoryStore(), llm=llm)
        stored_ids = await manager.extract_and_store(
            session_id=session_id,
            agent_state=agent_state,
        )
        logger.info("memory_worker.completed", session_id=session_id, count=len(stored_ids))
        return True
    except Exception as exc:
        logger.error("memory_worker.failed", session_id=session_id, error=str(exc))
        return False


async def poll_loop() -> None:
    """Main loop: poll the Redis Stream for new jobs."""
    logger.info("memory_worker.starting", stream=_STREAM_KEY)
    redis = create_redis_client()
    await ensure_group(redis)

    while True:
        try:
            results = await redis.xreadgroup(
                _GROUP_NAME,
                _CONSUMER_NAME,
                {_STREAM_KEY: ">"},
                count=_MAX_BATCH,
                block=1000,
            )
        except Exception as exc:
            logger.warning("memory_worker.poll_error", error=str(exc))
            await asyncio.sleep(_POLL_INTERVAL_S)
            continue

        if not results:
            await asyncio.sleep(_POLL_INTERVAL_S)
            continue

        for stream_name, messages in results:
            if stream_name != _STREAM_KEY:
                continue
            for msg_id, msg_data in messages:
                try:
                    job = {k: json.loads(v) if isinstance(v, str) and v.startswith(("{", "[")) else v for k, v in msg_data.items()}
                except (json.JSONDecodeError, TypeError):
                    job = dict(msg_data)

                success = await process_job(job)
                if success:
                    await redis.xack(_STREAM_KEY, _GROUP_NAME, msg_id)
                # On failure, don't ack — message will be retried via pending list


async def main() -> None:
    """Entry point for the worker process."""
    logging = structlog.get_logger()
    logging.info("memory_worker.init")
    await poll_loop()


if __name__ == "__main__":
    asyncio.run(main())
