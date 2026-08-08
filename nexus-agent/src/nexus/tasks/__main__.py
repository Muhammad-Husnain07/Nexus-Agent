"""nexus worker — CLI entry point for the background task worker."""

from __future__ import annotations

import asyncio

from nexus.tasks.worker import run_worker_loop


def main() -> None:
    """Run the worker loop until interrupted."""
    try:
        asyncio.run(run_worker_loop())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
