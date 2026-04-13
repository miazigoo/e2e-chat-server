import os
from collections.abc import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.postgres import PostgresContainer

from alembic import command
from alembic.config import Config

TABLES_TO_TRUNCATE = [
    "account_deletion_queue",
    "attachments",
    "upload_sessions",
    "conversation_events",
    "message_visibility_overrides",
    "message_recipient_states",
    "messages",
    "conversation_participants",
    "conversations",
    "login_attempts",
    "auth_email_codes",
    "auth_sessions",
    "device_prekeys",
    "devices",
    "users",
]


def _normalize_sqlalchemy_url(url: str) -> str:
    if url.startswith("postgresql+psycopg2://"):
        return url.replace("postgresql+psycopg2://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer, None, None]:
    with PostgresContainer("postgres:16") as postgres:
        yield postgres


@pytest.fixture(scope="session")
def database_url(postgres_container: PostgresContainer) -> str:
    raw_url = postgres_container.get_connection_url()
    return _normalize_sqlalchemy_url(raw_url)


@pytest.fixture(scope="session")
def migrated_database(database_url: str) -> str:
    previous_database_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url

    try:
        alembic_cfg = Config("alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", database_url)
        command.upgrade(alembic_cfg, "head")
        return database_url
    finally:
        if previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_database_url


@pytest_asyncio.fixture(scope="session")
async def engine(migrated_database: str) -> AsyncGenerator[AsyncEngine, None]:
    test_engine = create_async_engine(
        migrated_database,
        future=True,
        pool_pre_ping=True,
    )
    yield test_engine
    await test_engine.dispose()


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    async_session = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session() as test_session:
        yield test_session

    async with engine.begin() as conn:
        truncate_sql = (
            f"TRUNCATE TABLE {', '.join(TABLES_TO_TRUNCATE)} "
            "RESTART IDENTITY CASCADE;"
        )
        await conn.execute(text(truncate_sql))
