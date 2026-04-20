from types import SimpleNamespace

import pytest
from fastapi import Request

from app.core.exceptions import TooManyRequestsError
from app.core.rate_limit import rate_limit_dependency, rate_limiter


class FakePipeline:
    def __init__(self, redis_obj: "FakeRedis") -> None:
        self.redis_obj = redis_obj
        self.ops: list[tuple[str, tuple, dict]] = []

    async def __aenter__(self) -> "FakePipeline":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    def incr(self, key: str) -> None:
        self.ops.append(("incr", (key,), {}))

    def expire(self, key: str, seconds: int, nx: bool = False) -> None:
        self.ops.append(("expire", (key, seconds), {"nx": nx}))

    async def execute(self) -> list[int | bool]:
        results: list[int | bool] = []
        for name, args, kwargs in self.ops:
            if name == "incr":
                key = args[0]
                self.redis_obj.storage[key] = self.redis_obj.storage.get(key, 0) + 1
                results.append(self.redis_obj.storage[key])
            elif name == "expire":
                results.append(True)
        return results


class FakeRedis:
    def __init__(self) -> None:
        self.storage: dict[str, int] = {}

    def pipeline(self, transaction: bool = True) -> FakePipeline:
        return FakePipeline(self)


@pytest.mark.asyncio
async def test_rate_limiter_blocks_when_limit_exceeded() -> None:
    fake_redis = FakeRedis()
    rate_limiter._redis = fake_redis  # type: ignore[attr-defined]

    await rate_limiter.hit(key="rl:test:key", limit=2, window_seconds=60)
    await rate_limiter.hit(key="rl:test:key", limit=2, window_seconds=60)

    with pytest.raises(TooManyRequestsError) as exc:
        await rate_limiter.hit(key="rl:test:key", limit=2, window_seconds=60)

    assert exc.value.status_code == 429
    assert exc.value.code == "RATE_LIMITED"

    rate_limiter._redis = None  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_rate_limit_dependency_uses_request_identity() -> None:
    fake_redis = FakeRedis()
    rate_limiter._redis = fake_redis  # type: ignore[attr-defined]

    dependency = rate_limit_dependency(
        prefix="auth:login",
        limit=1,
        window_seconds=60,
    )

    request = SimpleNamespace(
        client=SimpleNamespace(host="127.0.0.1"),
        headers={
            "User-Agent": "pytest",
            "X-Device-Fingerprint": "device-fp",
            "X-Device-UUID": "device-uuid",
        },
    )
    await dependency(request)  # type: ignore[arg-type]

    with pytest.raises(TooManyRequestsError):
        await dependency(request)  # type: ignore[arg-type]

    rate_limiter._redis = None  # type: ignore[attr-defined]
