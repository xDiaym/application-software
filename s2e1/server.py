import asyncio
from collections import defaultdict
import functools
import logging
import sys
import typing as t


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("server")


def args_required(num_args: int):
    def decorator(fn) -> t.Callable[..., t.Awaitable[None]]:
        @functools.wraps(fn)    
        async def wrapper(self, client, args, text):
            if len(args) != num_args:
                return
            return await fn(self, client, args, text)
        return wrapper
    return decorator


class Client:
    def __init__(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._nick: str | None = None
        self._registered = False
    
    nick = property(lambda self: self.nick)
    peer = property(lambda self: self._writer.get_extra_info('peername'))
    ip = property(lambda self: self.peer[0])
    port = property(lambda self: self.peer[1])

    @property
    def prefix(self) -> str:
        if self._nick:
            return f"!{self._nick}"
        return ":?"

    async def send(self, line: str) -> None:
        self._writer.write(line.encode("utf-8"))
        await self._writer.drain()


def parse_command(line: str) -> tuple[str, list[str], str]:
    command_part, text = line.split(':', maxsplit=1)
    command, *args = command_part.split(' ')
    return command, args, text


class IRCServer:
    def __init__(self) -> None:
        self._channels: dict[str, set[Client]] = defaultdict(set)

    async def broadcast(
        self, channel: str, line: str, exclude: Client | None = None
    ) -> None:
        await asyncio.gather(
            *[
                client.send(line)
                for client in self._channels[channel]
                if client != exclude
            ]
        )

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        client = Client(reader, writer)
        logger.info("%s:%d connected", client.ip, client.port)

        while True:
            text = await reader.readline()
            if not text:
                await self._quit(client, [], "")
                break
            await self._process_command(client, text.decode().rstrip())

    async def _process_command(self, client: Client, line: str) -> None:
        COMMANDS: dict[str, t.Callable[[Client, list[str], str], t.Awaitable[None]]] = {
            "JOIN": self._join,
            "QUIT": self._quit,
            "NICK": self._nick,
            "PRIVMSG": self._privmsg,
        }

        command, args, text = parse_command(line)
        if fn := COMMANDS.get(command):
            await fn(client, args, text)
        else:
            logger.warning('unknown command \'%s\'', command)

    @args_required(1)
    async def _join(self, client: Client, args: list[str], text: str) -> None:
        channel = args[0]
        self._channels[channel].add(client)
        await self.broadcast(channel, f"{client.prefix} JOIN {channel}")

    async def _quit(self, client: Client, args: list[str], text: str) -> None:
        pass

    async def _nick(self, client: Client, args: list[str], text: str) -> None:
        pass

    @args_required(1)
    async def _privmsg(self, client: Client, args: list[str], text: str) -> None:
        channel_name = args[0]
        if channel_name.startswith('#') and channel_name in self._channels:
            await self.broadcast(channel_name, f'{client.prefix} PRIVMSG {channel_name} :{text}', exclude=client)

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
