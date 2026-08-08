"""nexus scheduler — CLI entry point for the recurring-task scheduler."""

from __future__ import annotations

import asyncio

from nexus.tasks.scheduler import Scheduler


def main() -> None:
    """Run the scheduler loop until interrupted."""
    try:
        asyncio.run(Scheduler().run_forever())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
