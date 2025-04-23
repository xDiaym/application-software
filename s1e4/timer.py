import os
from pathlib import Path
import time
from common import emit, EventType, sys_open


def main(pipe: Path, dev: str) -> None:
    with sys_open(str(pipe), os.O_WRONLY) as fd:
        try:
            os.write(fd, emit(dev, EventType.STARTED))
            while True:
                os.write(fd, emit(dev, EventType.RUNNING))
                time.sleep(2)
                os.write(fd, emit(dev, EventType.WAITING))
                time.sleep(1)
        except KeyboardInterrupt:
            os.write(fd, emit(dev, EventType.STOPPED))
            return


if __name__ == "__main__":
    cwd = Path(__file__).resolve().parent
    main(cwd / "time.pipe", "time")
