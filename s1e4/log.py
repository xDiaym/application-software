from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
import logging
import os
from pathlib import Path
import select
import sqlite3
import textwrap
from typing import cast

from common import Event, EventType, MESSAGE_LENGTH

CWD = Path(__file__).resolve().parent


class Storage:
    _STATUS_CODES = {
        (EventType.STARTED, "C"),
        (EventType.RUNNING, "R"),
        (EventType.WAITING, "W"),
        (EventType.STOPPED, "T")
    }

    _STATUS2CHAR = {k: v for k, v in _STATUS_CODES}
    _CHAR2STATUS = {v: k for k, v in _STATUS_CODES}

    def __init__(self, conn: sqlite3.Connection):
        logging.basicConfig(level=logging.DEBUG)
        self._logger = logging.getLogger()
        self._conn = conn
        self._cursor = conn.cursor()
        self._conn.executescript(Storage._query("init.sql"))

    def log(self, event: Event) -> None:
        self._logger.info("%s", repr(event))
        self._conn.execute(
            Storage._query("insert_log.sql"),
            (
                self._get_device(event.dev),
                Storage._STATUS2CHAR[event.type],
                event.timestamp,
            )
        )
        self._conn.commit()
    
    def _get_device(self, name: str) -> int:
        self._conn.execute(Storage._query("insert_device.sql"), (name, ))
        self._conn.commit()
        cur = self._conn.execute(Storage._query("select_device.sql"), (name, ))
        return cast(int, cur.fetchone()[0])

    def stat(self, dev: str, start: datetime, end: datetime) -> float:
        assert end <= start
        cur = self._conn.execute(Storage._query("select_stat.sql"), (dev, start, end))
        return self._stat_group(cur.fetchall()) / (start - end)
    
    def _stat_group(self, logs: list[tuple[str, datetime]]):
        for ev in logs:
            pass


    
    @lru_cache
    @staticmethod
    def _query(name: str) -> str:
        path = CWD / "sql" / name
        with path.open("r") as fp:
            return fp.read()


def main(pipes: list[Path]) -> None:
    assert all(map(Path.is_fifo, pipes))

    with sqlite3.connect(CWD / "logs.sqlite") as conn, ExitStack() as es:
        storage = Storage(conn)
        ps = [os.open(str(path), os.O_RDONLY | os.O_NONBLOCK) for path in pipes] + [0]
        try:
            while True:
                read_ready, _, _ = select.select(ps, [], [])
                for fd in read_ready:
                    if fd == 0:
                        command = os.read(fd, 1024).decode()
                        match command:
                            case "quit" | "q":
                                break
                            case command.startswith("stat"):
                                _, dev, timespan = command.split(" ")
                                start, end = map(datetime.fromisoformat)
                                print(storage.stat(dev, ))
                    else:
                        data = os.read(fd, MESSAGE_LENGTH)
                        event = Event.deserialize(data)
                        storage.log(event)
        except KeyboardInterrupt:
            return
        finally:
            for fd in ps:
                os.close(fd)


if __name__ == "__main__":
    main([CWD / "text.pipe", CWD / "time.pipe"])
