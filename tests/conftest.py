from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from app.main import app


class DummyPipeline:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    def incr(self, *args, **kwargs):
        return self

    def expire(self, *args, **kwargs):
        return self

    async def execute(self):
        return [1, True]


class DummyPubSub:
    async def subscribe(self, *args, **kwargs) -> None:
        return None

    async def unsubscribe(self, *args, **kwargs) -> None:
        return None

    async def get_message(self, *args, **kwargs):
        return None

    async def close(self) -> None:
        return None


class DummyRedis:
    async def ping(self) -> bool:
        return True

    async def get(self, *args, **kwargs):
        return None

    async def set(self, *args, **kwargs):
        return True

    async def setex(self, *args, **kwargs):
        return True

    async def delete(self, *args, **kwargs):
        return 1

    async def incr(self, *args, **kwargs):
        return 1

    async def expire(self, *args, **kwargs):
        return True

    async def publish(self, *args, **kwargs):
        return 1

    def pubsub(self) -> DummyPubSub:
        return DummyPubSub()

    def pipeline(self, *args, **kwargs) -> DummyPipeline:
        return DummyPipeline()

    async def close(self) -> None:
        return None


@pytest.fixture(autouse=True)
def patch_redis_and_realtime(monkeypatch: pytest.MonkeyPatch) -> None:
    dummy = DummyRedis()

    monkeypatch.setattr(
        "redis.asyncio.from_url",
        lambda *args, **kwargs: dummy,
        raising=False,
    )
    monkeypatch.setattr(
        "redis.from_url",
        lambda *args, **kwargs: dummy,
        raising=False,
    )
    monkeypatch.setattr(
        "redis.asyncio.Redis",
        lambda *args, **kwargs: dummy,
        raising=False,
    )
    monkeypatch.setattr(
        "redis.Redis",
        lambda *args, **kwargs: dummy,
        raising=False,
    )

    async def _noop(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr("app.main.realtime_hub.start", _noop, raising=False)
    monkeypatch.setattr("app.main.realtime_hub.stop", _noop, raising=False)
    monkeypatch.setattr(
        "app.main.realtime_hub.refresh_presence",
        _noop,
        raising=False,
    )
    monkeypatch.setattr(
        "app.main.realtime_hub.mark_offline",
        _noop,
        raising=False,
    )


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(app, base_url="http://localhost") as test_client:
        yield test_client
