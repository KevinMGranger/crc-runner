import asyncio
from typing import Any, Coroutine, TypeVar


T = TypeVar("T")


def future_coro(f: asyncio.Future[T]) -> Coroutine[Any, Any, T]:
    async def _():
        return await f

    return _()
