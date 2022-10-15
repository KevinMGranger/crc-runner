# https://gist.github.com/twisteroidambassador/f35c7b17d4493d492fe36ab3e5c92202


import asyncio
from typing import Coroutine, Any, TypeVar

T = TypeVar("T")


class CancelledFromOutside(asyncio.CancelledError):
    pass


class CancelledFromInside(asyncio.CancelledError):
    pass


async def distinguish_cancellation(fut: Coroutine[T, Any, Any] | asyncio.Task[T]) -> T:
    """Wait for a future. If cancelled, raise different exceptions depending
    on who did the cancellation.
    If fut was cancelled, propagate cancellation outward by raising
    CancelledFromInside.
    If this function was cancelled, cancel fut, and raise CancelledFromOutside.
    """
    if isinstance(fut, asyncio.Task):
        task = fut
    else:
        task = asyncio.create_task(fut)

    try:
        # will only return once task is cancelled.
        await asyncio.wait((task,))
    except asyncio.CancelledError:
        # if this was raised, that means _this_ function was cancelled, not `task`.

        # TODO: can we / do we need to optionally disable this?
        # will shielding fut cancel it, so we can leave it up to the caller?
        task.cancel()
        raise CancelledFromOutside

    assert task.done()

    # this means it returned because `task` was cancelled.
    if task.cancelled():
        raise CancelledFromInside

    return task.result()
