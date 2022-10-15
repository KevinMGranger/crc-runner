import typing
import asyncio

T = typing.TypeVar("T")


def ensure_task(awaitable: typing.Awaitable[T]) -> asyncio.Task[T]:
    if isinstance(awaitable, asyncio.Task):
        return awaitable

    async def why_is_this_necessary():
        return await awaitable

    return asyncio.create_task(why_is_this_necessary())
