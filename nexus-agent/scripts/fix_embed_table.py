"""Create the embed_config table if it doesn't exist."""
import asyncio, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from sqlalchemy import text
from nexus.db.base import get_engine

async def main():
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS embed_config (
                id UUID PRIMARY KEY,
                tenant_id UUID NOT NULL REFERENCES tenant(id),
                name VARCHAR NOT NULL DEFAULT '',
                token VARCHAR NOT NULL,
                allowed_domains JSONB NOT NULL DEFAULT '[]'::jsonb,
                theme VARCHAR NOT NULL DEFAULT 'light',
                primary_color VARCHAR NOT NULL DEFAULT '#2563eb',
                welcome_message VARCHAR NOT NULL DEFAULT 'Hello! How can I help you today?',
                max_height INTEGER NOT NULL DEFAULT 600,
                max_width INTEGER NOT NULL DEFAULT 380,
                custom_css TEXT NOT NULL DEFAULT '',
                rate_limit INTEGER NOT NULL DEFAULT 30,
                analytics_enabled BOOLEAN NOT NULL DEFAULT TRUE,
                is_revoked BOOLEAN NOT NULL DEFAULT FALSE,
                message_count INTEGER NOT NULL DEFAULT 0,
                active_sessions INTEGER NOT NULL DEFAULT 0,
                last_used_at TIMESTAMP WITH TIME ZONE,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
            )
        """))
        print("Created embed_config table.")
    await engine.dispose()

asyncio.run(main())
