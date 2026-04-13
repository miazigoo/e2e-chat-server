from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def test_migrations_created_core_tables(session: AsyncSession) -> None:
    result = await session.execute(
        text(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name IN (
                'users',
                'devices',
                'device_prekeys',
                'conversations',
                'messages',
                'conversation_events'
              )
            ORDER BY table_name
            """
        )
    )

    table_names = {row[0] for row in result.fetchall()}

    assert "users" in table_names
    assert "devices" in table_names
    assert "device_prekeys" in table_names
    assert "conversations" in table_names
    assert "messages" in table_names
    assert "conversation_events" in table_names
