import asyncio
from collections import UserDict
import collections.abc as abc
import signal
from typing import TypeVar, Any


class _SignalListenerMap(UserDict[int, asyncio.Event]):
    def handle(self):
        for event in self.data.values():
            event.set()
            # TODO: it says set _immediately_ wakes them up, so is immediate clearing okay?
            event.clear()

    def __getitem__(self, id: int) -> asyncio.Event:
        if id not in self.data:
            self.data[id] = event = asyncio.Event()
            return event
        else:
            return self.data[id]


class _SignalMap(UserDict[signal.Signals, _SignalListenerMap]):
    def listener_map_for(self, signal: signal.Signals) -> _SignalListenerMap:
        "Idempotently register the handler for the given signal. Returns the map."
        if signal in self:
            return self[signal]
        task_mapper = _SignalListenerMap()
        self[signal] = task_mapper

        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal, task_mapper.handle)

        return task_mapper


_SIGNAL_MAP = _SignalMap()


class SignalError(Exception):
    __match_args__ = ("signal",)

    def __init__(self, signal: signal.Signals):
        super().__init__(signal)
        self.signal = signal


T = TypeVar("T")


async def check_signal(
    awaitable: abc.Coroutine[Any, Any, T] | asyncio.Task[T],
    signal: signal.Signals,
) -> T:
    """
    Run a coroutine, raising an exception if a signal is recieved while doing so.
    """

    match awaitable:
        case asyncio.Task():
            awaitable_task = awaitable
        case _ if asyncio.iscoroutine(awaitable):
            # TODO why doesn't the type propogate?
            # answer: because iscoroutine is a type guard that doesn't have an overload
            awaitable_task: asyncio.Task[T] = asyncio.create_task(awaitable)
        case _:
            raise TypeError("awaitable must be a coroutine or task")

    task_id = id(awaitable_task)
    signal_listener_map = _SIGNAL_MAP.listener_map_for(signal)
    event = signal_listener_map[task_id]
    event_task = asyncio.create_task(event.wait())

    done, _pending = await asyncio.wait(
        (event_task, awaitable_task), return_when=asyncio.FIRST_COMPLETED
    )

    del signal_listener_map[task_id]

    if event_task in done:
        raise SignalError(signal=signal)
    elif awaitable_task in done:
        return awaitable_task.result()
    else:
        raise RuntimeError("asyncio.wait returned even though no tasks were done")
