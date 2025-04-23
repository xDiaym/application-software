import os
import time
import sys
from pathlib import Path

from common import emit, EventType, sys_open


def main(pipe: Path, dev: str) -> None:
    with sys_open(str(pipe), sys.O_WRONLY) as fd:
        os.write(fd, emit(dev, EventType.STARTED))
        try:
            while True:
                os.write(fd, emit(dev, EventType.WAITING))
                sys.stdin.read(1)
                time.sleep(1)
                os.write(fd, emit(dev, EventType.RUNNING))
        except KeyboardInterrupt:
            os.write(fd, emit(dev, EventType.STOPPED))
            return


if __name__ == "__main__":
    cwd = Path(__file__).resolve().parent
    main(cwd / "text.pipe", "text")
