import asyncio
import contextlib
import sys

CRLF = "\r\n"


class Client:
    def __init__(self) -> None:
        # self._nick: str = None
        pass

    async def _handle_server(self) -> None:
        while True:  #not self._reader.at_eof():
            try:
                binary = await self._reader.readline()
            except asyncio.CancelledError:
                break
            if not binary:
                break
            print(f"> {binary.decode('utf-8')}")

    async def _handle_stdin(self) -> None:
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader()
        srp = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: srp, sys.stdin)

        while True:
            try:
                line = (await reader.readline()).rstrip()
            except asyncio.CancelledError:
                break
            if not line:
                break  # TODO quit
            await self._send(line.decode())

    async def _send(self, line: str) -> None:
        self._writer.write(f"{line}{CRLF}".encode())
        await self._writer.drain()

    async def run(self, host: str, port: int = 6667) -> None:
        self._reader, self._writer = await asyncio.open_connection(host, port)

        server_task = asyncio.create_task(self._handle_server())
        stdin_task = asyncio.create_task(self._handle_stdin())

        _done, pending = await asyncio.wait({server_task, stdin_task}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


def main() -> int:
    client = Client()
    asyncio.run(client.run("127.0.0.1"))
    return 0


if __name__ == "__main__":
    sys.exit(main())