import asyncio
from collections import defaultdict
import datetime
import functools
import hashlib
import logging
import os
import typing as t

import aiosqlite


GLOBAL_CHAT_ID = 1

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("server")


@functools.lru_cache()
def sql_script(path: str) -> str:
    with open(f"sql/{path}") as fp:
        return fp.read()


class SQLiteStorage:
    _SALT = os.environ.get("IRCLIKE_SALT", "1sud83")

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._connection = conn

    async def init_schema(self) -> None:
        script = sql_script("init.sql")
        async with self._connection.executescript(script):
            await self._connection.commit()

    async def store_message(self, author: str, text: str) -> None:
        author_id: int
        async with self._connection.execute(
            "SELECT id FROM users WHERE nick = ?", (author,)
        ) as cursor:
            if author_id := await cursor.fetchone() is None:
                logger.warning("user %s not found", author)
                return

        query = "INSERT INTO messages(author_id, chat_id, text_) VALUES (?, ?, ?)"
        async with self._connection.execute(query, (author_id, GLOBAL_CHAT_ID, text)):
            await self._connection.commit()

    async def delete_message(self) -> None:
        raise NotImplementedError

    async def delete_user(self) -> None:
        raise NotImplementedError

    async def get_messages(
        self, chat: str, begin: datetime.datetime, end: datetime.datetime
    ) -> list[str]:
        async with self._connection.execute(
            "SELECT id FROM chats WHERE name = ?", (chat,)
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                logger.warning("chat '%s' not found", chat)
                return []
            chat_id = row[0]

        async with self._connection.execute(
            "SELECT author_id, text_ FROM messages WHERE chat_id = ? AND created_at BETWEEN ? and ?",
            (chat_id, begin.isoformat(), end.isoformat()),
        ) as cursor:
            return list(x[1] for x in await cursor.fetchall())

    async def register(self, nick: str, password: str) -> bool:
        async with self._connection.execute(
            "SELECT COUNT(*) FROM users WHERE nick = ?", (nick,)
        ) as cursor:
            if result := await cursor.fetchone():
                if result[0] > 0:
                    return False

        async with self._connection.execute(
            "INSERT INTO users(nick, password_hash) VALUES (?, ?)",
            (nick, self.hash(password)),
        ):
            await self._connection.commit()
        return True

    async def verify(self, nick: str, password: str) -> bool:
        async with self._connection.execute(
            "SELECT COUNT(*) FROM users WHERE nick = ? AND password_hash = ?",
            (nick, self.hash(password)),
        ) as cursor:
            if result := await cursor.fetchone():
                return result[0] == 1
        return False

    @classmethod
    def hash(cls, password: str) -> str:
        return hashlib.sha3_512((password + cls._SALT).encode()).hexdigest()


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
    peer = property(lambda self: self._writer.get_extra_info("peername"))
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
    command_part, text = line.split(":", maxsplit=1)
    command, *args = command_part.split(" ")
    return command, args, text


class IRCServer:
    def __init__(self, storage: SQLiteStorage) -> None:
        self._channels: dict[str, set[Client]] = defaultdict(set)
        self._storage = storage

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
            # "REGISTER": self._register,
            "PRIVMSG": self._privmsg,
        }

        command, args, text = parse_command(line)
        if fn := COMMANDS.get(command):
            await fn(client, args, text)
        else:
            logger.warning("unknown command '%s'", command)

    @args_required(1)
    async def _join(self, client: Client, args: list[str], text: str) -> None:
        channel = args[0]
        self._channels[channel].add(client)
        await self.broadcast(channel, f"{client.prefix} JOIN {channel}")

    async def _quit(self, client: Client, args: list[str], text: str) -> None:
        pass

    async def _register(self, client: Client, args: list[str], text: str) -> None:
        pass

    @args_required(1)
    async def _privmsg(self, client: Client, args: list[str], text: str) -> None:
        channel_name = args[0]
        if channel_name.startswith("#") and channel_name in self._channels:
            await self._storage.store_message(client.nick, text)
            if args == []:  # do not store commmands
                await self._storage.store_message(client.nick, text)
            await self.broadcast(
                channel_name,
                f"{client.prefix} PRIVMSG {channel_name} :{text}",
                exclude=client,
            )

    async def run(self, host: str = "0.0.0.0", port: int = 6667) -> None:
        server = await asyncio.start_server(self._handle_connection, host, port)
        logger.info("server listening on port %d", port)
        async with server:
            await server.serve_forever()


async def main() -> int:
    async with aiosqlite.connect("irclike.db") as conn:
        storage = SQLiteStorage(conn)
        server = IRCServer(storage)
        await server.run()
    return 0


if __name__ == "__main__":
    asyncio.run(main())
