from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
import os
from struct import pack, unpack
import typing as tp


class EventType(int, Enum):
    STARTED = auto()
    RUNNING = auto()
    WAITING = auto()
    STOPPED = auto()


@dataclass(frozen=True, slots=True)
class Event:
    dev: str
    type: EventType
    timestamp: datetime = field(default_factory=datetime.now)

    def __post_init__(self) -> None:
        if len(self.dev) != 4:
            raise ValueError(f"dev must have length of 4, got {len(self.dev)}")

    @classmethod
    def deserialize(cls, buffer: bytes) -> "Event":
        dev, timestamp, type = unpack("<4sdi", buffer)
        return cls(dev.decode(), EventType(type), datetime.fromtimestamp(timestamp))

    def serialize(self) -> bytes:
        return pack("<4sdi", self.dev.encode(), self.timestamp.timestamp(), self.type)


def emit(dev: str, type: EventType, *args, **kwargs) -> bytes:
    return Event(dev, type, *args, **kwargs).serialize()


MESSAGE_LENGTH = len(emit("test", EventType.RUNNING))


@contextmanager
def sys_open(path: str, mode: int) -> tp.Generator[int]:
    fd = os.open(path, mode)
    try:
        yield fd
    except Exception as exc:
        os.close(fd)
