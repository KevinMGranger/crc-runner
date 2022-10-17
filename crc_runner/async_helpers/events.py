"Abstraction(s) for reacting to events."
from typing import Awaitable, TypeVar, Callable
from asyncio import create_task, Event, Task, wait, FIRST_COMPLETED


T = TypeVar("T")
Exc = TypeVar("Exc", bound=BaseException)


async def check_event(
    awaitable: Awaitable[T],
    event: Event,
    exc_factory: Callable[[Task[T]], Exc],
) -> T:
    """
    Run a coroutine, raising an exception from the given factory
    if the event gets set.

    The idea is that the event represents some sort of interruption, signal, etc.,
    and thus should be represented as an exception.

    Returns the result of the other task, or raises its exception / cancellationerror.
    TODO: is that actually a good abstraction?
    """

    if isinstance(awaitable, Task):
        task = awaitable
    else:

        async def why_is_this_necessary():
            return await awaitable

        task = create_task(why_is_this_necessary())

    event_task = create_task(event.wait())

    await wait((event_task, task), return_when=FIRST_COMPLETED)

    if event_task.done():
        # should only be finished or still pending, never cancelled or excepted
        raise exc_factory(task)
    elif task.done():
        event_task.cancel()
        return task.result()
    else:
        raise RuntimeError("asyncio.wait returned even though no tasks were done")
