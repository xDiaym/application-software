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


def sql_script(path: str) -> str:
    """Load SQL script - using embedded script instead of file."""
    if path == "init.sql":
        return """CREATE TABLE IF NOT EXISTS users(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nick VARCHAR(16) UNIQUE NOT NULL,
    password_hash VARCHAR(256) NOT NULL
);

INSERT OR IGNORE INTO users(id, nick, password_hash) VALUES (0, 'deleted user', '');

CREATE TABLE IF NOT EXISTS chats(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(16) UNIQUE NOT NULL
);

INSERT OR IGNORE INTO chats(name) VALUES ("#global");

CREATE TABLE IF NOT EXISTS messages(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    author_id INTEGER NOT NULL REFERENCES users(id),
    chat_id INTEGER NOT NULL REFERENCES chats(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    text_ TEXT NOT NULL
);"""
    raise ValueError(f"Unknown script: {path}")


class SQLiteStorage:
    _SALT = os.environ.get("IRCLIKE_SALT", "1sud83")

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._connection = conn

    async def init_schema(self) -> None:
        script = sql_script("init.sql")
        await self._connection.executescript(script)
        await self._connection.commit()

    async def store_message(self, author: str, text: str) -> None:
        async with self._connection.execute(
                "SELECT id FROM users WHERE nick = ?", (author,)
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                logger.warning("user %s not found", author)
                return
            author_id = row[0]

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
            result = await cursor.fetchone()
            if result and result[0] > 0:
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
            result = await cursor.fetchone()
            if result:
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

    @property
    def nick(self) -> str | None:
        return self._nick

    @property
    def peer(self) -> tuple:
        return self._writer.get_extra_info("peername")

    @property
    def ip(self) -> str:
        return self.peer[0]

    @property
    def port(self) -> int:
        return self.peer[1]

    @property
    def prefix(self) -> str:
        if self._nick:
            return f":{self._nick}!"
        return ":?"

    async def send(self, line: str) -> None:
        self._writer.write((line + "\r\n").encode("utf-8"))
        await self._writer.drain()

    def close(self) -> None:
        self._writer.close()


def parse_command(line: str) -> tuple[str, list[str], str]:
    """Parse IRC command: COMMAND arg1 arg2 :trailing text"""
    if ":" not in line:
        parts = line.split()
        return parts[0] if parts else "", parts[1:] if len(parts) > 1 else [], ""

    command_part, text = line.split(":", maxsplit=1)
    command, *args = command_part.split()
    return command, args, text.strip()


class IRCServer:
    def __init__(self, storage: SQLiteStorage) -> None:
        self._channels: dict[str, set[Client]] = defaultdict(set)
        self._storage = storage

    async def broadcast(
            self, channel: str, line: str, exclude: Client | None = None
    ) -> None:
        tasks = [
            client.send(line)
            for client in self._channels[channel]
            if client != exclude
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _handle_connection(
            self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        client = Client(reader, writer)
        logger.info("%s:%d connected", client.ip, client.port)
        try:
            while True:
                text = await reader.readline()
                if not text:
                    await self._quit(client, [], "")
                    break
                await self._process_command(client, text.decode().rstrip())
        finally:
            client.close()

    async def _process_command(self, client: Client, line: str) -> None:
        COMMANDS: dict[str, t.Callable[[Client, list[str], str], t.Awaitable[None]]] = {
            "JOIN": self._join,
            "QUIT": self._quit,
            "REG": self._reg,
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
        logger.info("%s:%d joined channel %s", client.ip, client.port, channel)
        # Broadcast JOIN to all clients in the channel (including the one that just joined)
        await self.broadcast(channel, f"{client.prefix} JOIN {channel}")

    async def _quit(self, client: Client, args: list[str], text: str) -> None:
        channels_to_quit = [ch for ch, clients in self._channels.items() if client in clients]
        for channel in channels_to_quit:
            self._channels[channel].discard(client)
            await self.broadcast(
                channel,
                f"{client.prefix} QUIT :{text or 'Client quit'}",
                exclude=client,
            )
        client.close()
        logger.info("%s:%d quit", client.ip, client.port)

    @args_required(2)
    async def _reg(self, client: Client, args: list[str], _text: str) -> None:
        nick, password = args
        result = await self._storage.register(nick, password)
        if result:
            client._nick = nick
            client._registered = True
            logger.info("new user registered. nick=%s", nick)
            await client.send(f"REGD {nick}")
        else:
            await client.send("ERR nick already taken")

    @args_required(1)
    async def _privmsg(self, client: Client, args: list[str], text: str) -> None:
        channel_name = args[0]
        if channel_name.startswith("#") and channel_name in self._channels:
            await self._storage.store_message(client.nick, text)
            logger.info("%s:%d sent message to %s", client.ip, client.port, channel_name)
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
        await storage.init_schema()
        server = IRCServer(storage)
        await server.run()
    return 0


if __name__ == "__main__":
    asyncio.run(main())
