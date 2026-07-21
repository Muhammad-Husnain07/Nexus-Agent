"""Rebuild embedding columns to a new dimension and recreate pgvector indexes.

Usage:
    uv run python scripts/rebuild_embedding_dim.py 1536

This alters the ``tool.embedding`` and ``memory.embedding`` columns to
``VECTOR(<new_dim>)``, drops and recreates the corresponding ivfflat indexes.
Run this AFTER changing ``NEXUS_LLM__EMBEDDING_DIMENSIONS`` in your ``.env``.

WARNING: Existing embeddings will be lost (casting is not supported by pgvector).
"""

from __future__ import annotations

import sys

from sqlalchemy import text


def main() -> None:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <new_dimension>")
        sys.exit(1)

    try:
        new_dim = int(sys.argv[1])
    except ValueError:
        print(f"Invalid dimension: {sys.argv[1]}")
        sys.exit(1)

    if new_dim < 1:
        print(f"Dimension must be >= 1, got {new_dim}")
        sys.exit(1)

    print(f"WARNING: This will rebuild embedding columns to VECTOR({new_dim}).")
    print("Existing embeddings will be lost. Continue? [y/N] ", end="")
    ans = input().strip().lower()
    if ans != "y":
        print("Aborted.")
        sys.exit(0)

    import asyncio

    from nexus.db.base import async_session

    async def run() -> None:
        async with async_session() as session:
            tables = [
                ("tool", "embedding", "idx_tool_embedding"),
                ("memory", "embedding", "idx_memory_embedding"),
            ]
            for table, col, idx in tables:
                print(f"Dropping index {idx}...")
                await session.execute(text(f"DROP INDEX IF EXISTS {idx}"))
                print(f"Altering {table}.{col} to VECTOR({new_dim})...")
                await session.execute(
                    text(f"ALTER TABLE {table} ALTER COLUMN {col} TYPE VECTOR({new_dim})")
                )
                print(f"Creating index {idx}...")
                await session.execute(
                    text(
                        f"CREATE INDEX IF NOT EXISTS {idx} "
                        f"ON {table} USING ivfflat ({col} vector_cosine_ops) "
                        f"WITH (lists = 100)"
                    )
                )
            await session.commit()
            print("Done. Columns and indexes rebuilt.")

    asyncio.run(run())


if __name__ == "__main__":
    main()
