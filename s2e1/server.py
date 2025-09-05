import asyncio
from collections import defaultdict
import logging
import sys


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("server")


class Client:
    def __init__(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self._reader = reader
        self._writer = writer

    async def send(self, line: str) -> None:
        self._writer.write(line.encode("utf-8"))
        await self._writer.drain()


class IRCServer:
    def __init__(self) -> None:
        self._channels: dict[str, set[Client]] = defaultdict(set)

    async def broadcast(
        self, channel: str, line: str, exclude: str | None = None
    ) -> None:
        await asyncio.gather(
            *[
                client.send(line)
                for client in self._channels[channel]
                if client != exclude
            ]
        )

    async def _join_channel(
        self,
        channel: str,
        nick: str,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        self._channels[channel].add(Client(reader, writer))
        await self.broadcast(channel, f"{nick} join the channel.")

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        logger.info("connected")
        while True:
            text = await reader.readline()
            if not text:
                # TODO quit
                logger.info("disconnected")
                break
            logger.info("%s", text.decode().rstrip())
            writer.write(text)
            await writer.drain()

    async def run(self, host: str = "0.0.0.0", port: int = 6667) -> None:
        server = await asyncio.start_server(self._handle_connection, host, port)
        logger.info("server listening on port %d", port)
        async with server:
            await server.serve_forever()


def main() -> int:
    server = IRCServer()
    asyncio.run(server.run())
    return 0


if __name__ == "__main__":
    sys.exit(main())
