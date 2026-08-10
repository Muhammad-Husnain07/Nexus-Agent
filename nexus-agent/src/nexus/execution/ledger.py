"""Durable idempotency ledger (D1/P0-D, invariant I5).

Identity = (scope, operation, resolved inputs): ``session_id`` +
``execution_key`` (SHA256 of tool + resolved inputs). ``attempt_id`` is
execution metadata and NEVER participates in the key.

Contract:
- Exactly one attempt wins the claim for a key; others observe the
  completed result (reuse) or a held lease (explicit outcome).
- A completed result is replayed, never re-executed — across executor
  instances, reflection retries, checkpoint resumes and replays.
- A stale lease (expired) can be reclaimed — crash recovery is safe.
- Architecture fingerprint rides the row: results from a different
  architecture are never replayed.

The store interface is deliberately small so unit tests can inject a
dict-backed fake; the SQL is a thin adapter.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

DEFAULT_LEASE_S = 120


@dataclass(frozen=True)
class LedgerEntry:
    """A ledger row snapshot used for the claim/reuse decision."""

    result: Any
    lease_token: str | None
    lease_expires_at: datetime | None
    arch_fp: str | None


class LedgerStore(Protocol):
    """The minimal durable-store interface."""

    async def find(self, session_id: str, execution_key: str) -> LedgerEntry | None: ...

    async def claim(
        self,
        session_id: str,
        execution_key: str,
        token: str,
        lease_s: int,
        arch_fp: str,
        agent_run_id: str | None = None,
    ) -> bool:
        """Atomically claim the key. Returns True when THIS attempt won the
        claim (either the row did not exist or its lease was stale).

        P2-C: ``agent_run_id`` rides the row so every idempotency claim is
        joinable back to its parent run without log parsing."""

    async def complete(
        self,
        session_id: str,
        execution_key: str,
        result: dict,
        token: str,
        agent_run_id: str | None = None,
    ) -> None:
        """Record the completed result and release the lease."""

    async def release(
        self,
        session_id: str,
        execution_key: str,
        token: str,
    ) -> None:
        """Release the claim lease without a result (definite failure)."""


class SqlLedgerStore:
    """PostgreSQL adapter over ``completed_executions``."""

    def __init__(self, session_factory=None) -> None:
        self._session_factory = session_factory

    def _factory(self):
        if self._session_factory is not None:
            return self._session_factory()
        from nexus.db import async_session as db_session_factory  # noqa: PLC0415

        return db_session_factory()

    async def find(self, session_id: str, execution_key: str) -> LedgerEntry | None:
        from sqlalchemy import select  # noqa: PLC0415

        from nexus.db.models.completed_execution import CompletedExecution  # noqa: PLC0415

        async with self._factory() as session:
            row = await session.execute(
                select(CompletedExecution).where(
                    CompletedExecution.session_id == session_id,
                    CompletedExecution.execution_key == execution_key,
                )
            )
            entry = row.scalar_one_or_none()
            if entry is None:
                return None
            return LedgerEntry(
                result=entry.result,
                lease_token=entry.lease_token,
                lease_expires_at=entry.lease_expires_at,
                arch_fp=entry.arch_fp,
            )

    async def claim(
        self,
        session_id: str,
        execution_key: str,
        token: str,
        lease_s: int,
        arch_fp: str,
        agent_run_id: str | None = None,
    ) -> bool:
        from sqlalchemy import update  # noqa: PLC0415
        from sqlalchemy.dialects.postgresql import insert  # noqa: PLC0415

        from nexus.db.models.completed_execution import CompletedExecution  # noqa: PLC0415

        now = datetime.now(UTC)
        expires = now + timedelta(seconds=lease_s)
        async with self._factory() as session:
            # 1. Try the fresh insert (row absent) — this attempt is the winner.
            stmt = (
                insert(CompletedExecution)
                .values(
                    session_id=session_id,
                    execution_key=execution_key,
                    lease_token=token,
                    lease_expires_at=expires,
                    arch_fp=arch_fp,
                    agent_run_id=agent_run_id,
                )
                .on_conflict_do_nothing(
                    index_elements=["session_id", "execution_key"]
                )
            )
            result = await session.execute(stmt)
            await session.commit()
            if result.rowcount == 1:
                return True
            # 2. Row exists. Win only when the lease is stale (or the row
            #    has no result yet and no live lease).
            upd = (
                update(CompletedExecution)
                .where(
                    CompletedExecution.session_id == session_id,
                    CompletedExecution.execution_key == execution_key,
                    CompletedExecution.result.is_(None),
                    (
                        (CompletedExecution.lease_expires_at.is_(None))
                        | (CompletedExecution.lease_expires_at < now)
                    ),
                )
                .values(
                    lease_token=token,
                    lease_expires_at=expires,
                    arch_fp=arch_fp,
                    agent_run_id=agent_run_id,
                )
            )
            result = await session.execute(upd)
            await session.commit()
            return result.rowcount == 1

    async def complete(
        self,
        session_id: str,
        execution_key: str,
        result: dict,
        token: str,
        agent_run_id: str | None = None,
    ) -> None:
        from sqlalchemy import update  # noqa: PLC0415

        from nexus.db.models.completed_execution import CompletedExecution  # noqa: PLC0415

        async with self._factory() as session:
            await session.execute(
                update(CompletedExecution)
                .where(
                    CompletedExecution.session_id == session_id,
                    CompletedExecution.execution_key == execution_key,
                    CompletedExecution.lease_token == token,
                )
                .values(
                    result=result,
                    lease_token=None,
                    lease_expires_at=None,
                    agent_run_id=agent_run_id,
                )
            )
            await session.commit()

    async def release(
        self,
        session_id: str,
        execution_key: str,
        token: str,
    ) -> None:
        from sqlalchemy import update  # noqa: PLC0415

        from nexus.db.models.completed_execution import CompletedExecution  # noqa: PLC0415

        async with self._factory() as session:
            await session.execute(
                update(CompletedExecution)
                .where(
                    CompletedExecution.session_id == session_id,
                    CompletedExecution.execution_key == execution_key,
                    CompletedExecution.lease_token == token,
                )
                .values(lease_token=None, lease_expires_at=None)
            )
            await session.commit()


class CompletedExecutionLedger:
    """Executor-facing ledger with degrade-safe semantics."""

    def __init__(
        self,
        store: LedgerStore | None = None,
        lease_s: int = DEFAULT_LEASE_S,
    ) -> None:
        self._store = store or SqlLedgerStore()
        self._lease_s = lease_s

    @staticmethod
    def new_token() -> str:
        return uuid.uuid4().hex

    async def find(self, session_id: str, execution_key: str) -> LedgerEntry | None:
        try:
            return await self._store.find(session_id, execution_key)
        except Exception:
            return None  # degrade: the caller falls back to execution

    async def claim(
        self,
        session_id: str,
        execution_key: str,
        arch_fp: str,
        agent_run_id: str | None = None,
    ) -> str | None:
        """Atomically claim the key; returns the lease token on success,
        None when another attempt holds the key.

        P2-C: ``agent_run_id`` is forwarded to the store so the claim row
        joins back to its parent run."""
        token = self.new_token()
        try:
            won = await self._store.claim(
                session_id, execution_key, token, self._lease_s, arch_fp,
                agent_run_id=agent_run_id,
            )
        except Exception:
            return token  # degrade: proceed without durability
        return token if won else None

    async def complete(
        self,
        session_id: str,
        execution_key: str,
        result: dict,
        token: str,
        agent_run_id: str | None = None,
    ) -> None:
        try:
            await self._store.complete(
                session_id, execution_key, result, token,
                agent_run_id=agent_run_id,
            )
        except Exception:
            pass  # degrade: durability is best-effort at this layer

    async def release(
        self, session_id: str, execution_key: str, token: str
    ) -> None:
        """D1/P0-D: release the claim lease after a DEFINITE failure so a
        retry is immediately re-claimable. NEVER called for ``uncertain``
        outcomes — the side effect may have fired; the lease expiry window
        (not an immediate release) is what prevents a duplicate."""
        try:
            await self._store.release(session_id, execution_key, token)
        except Exception:
            pass  # degrade
