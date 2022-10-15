from collections import UserDict
from asyncio import Event, get_running_loop, Task, create_task
from signal import Signals
from typing import TypeVar, Awaitable
from functools import partial
from .events import check_event

T = TypeVar("T")


class _SignalListenerMap(UserDict[int, Event]):
    def handle(self):
        for event in self.data.values():
            event.set()
            # TODO: it says set _immediately_ wakes them up, so is immediate clearing okay?
            event.clear()

    def __getitem__(self, id: int) -> Event:
        if id not in self.data:
            self.data[id] = event = Event()
            return event
        else:
            return self.data[id]


class _SignalMap(UserDict[Signals, _SignalListenerMap]):
    def listener_map_for(self, signal: Signals) -> _SignalListenerMap:
        "Idempotently register the handler for the given signal. Returns the map."
        if signal in self:
            return self[signal]
        task_mapper = _SignalListenerMap()
        self[signal] = task_mapper

        loop = get_running_loop()
        loop.add_signal_handler(signal, task_mapper.handle)

        return task_mapper


_SIGNAL_MAP = _SignalMap()


class SignalError(Exception):
    __match_args__ = ("signal",)

    def __init__(self, signal: Signals, task: Task[T]):
        super().__init__(signal)
        self.signal = signal
        self.task = task


async def check_signal(
    awaitable: Awaitable[T],
    signal: Signals,
) -> T:
    """
    Run a coroutine, raising an exception if a signal is recieved while doing so.
    """

    if isinstance(awaitable, Task):
        task = awaitable
    else:

        async def why_is_this_necessary():
            return await awaitable

        task = create_task(why_is_this_necessary())

    task_id = id(task)
    signal_listener_map = _SIGNAL_MAP.listener_map_for(signal)
    event = signal_listener_map[task_id]

    try:
        return await check_event(task, event, partial(SignalError, signal))
    finally:
        del signal_listener_map[task_id]
