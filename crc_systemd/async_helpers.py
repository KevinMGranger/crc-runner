import asyncio
from asyncio.subprocess import Process
import collections.abc as abc
import signal
import typing

sigterm = asyncio.Event()


def handle_sigterm():
    sigterm.set()


class SignalError(Exception):
    def __init__(self, *args: object, signal: signal.Signals):
        super().__init__(signal.name, *args)
        self.signal = signal


class SigTermError(SignalError):
    def __init__(self, *args: object):
        super().__init__(*args, signal=signal.SIGTERM)


T = typing.TypeVar("T")


async def check_signal(
    awaitable: abc.Coroutine[typing.Any, typing.Any, T] | asyncio.Task[T]
) -> T:
    """
    Run a coroutine, throwing an exception if
    a SIGTERM is recieved while doing so.
    """
    queue_task = asyncio.create_task(sigterm.wait())
    match awaitable:
        case asyncio.Task():
            awaitable_task = awaitable
        case _ if asyncio.iscoroutine(awaitable):
            # TODO why doesn't the type propogate?
            awaitable_task: asyncio.Task[T] = asyncio.create_task(awaitable)
        case _:
            raise TypeError("awaitable must be a coroutine or task")

    while True:
        done, _pending = await asyncio.wait(
            (queue_task, awaitable_task), return_when=asyncio.FIRST_COMPLETED
        )
        if queue_task in done:
            raise SigTermError
        elif awaitable_task in done:
            return awaitable_task.result()


async def term_on_cancel(proc: Process) -> int:
    "Terminate the given process if this coroutine is cancelled."
    try:
        return await proc.wait()
    except asyncio.CancelledError:
        proc.terminate()
        raise
