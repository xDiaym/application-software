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

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
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

    async def get_messages(
            self, channel: str, begin: datetime.datetime, end: datetime.datetime
    ) -> list[tuple[str, str, str]]:
        """
        Получить сообщения из канала за указанный период времени.

        Args:
            channel: имя канала (например, #global)
            begin: начальная дата/время
            end: конечная дата/время

        Returns:
            список кортежей (timestamp, nick, text)
        """
        logger.debug(f"[HISTORY] get_messages called with channel={channel}, begin={begin}, end={end}")

        async with self._connection.execute(
                "SELECT id FROM chats WHERE name = ?", (channel,)
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                logger.warning(f"[HISTORY] Chat '{channel}' not found in database")
                return []

            chat_id = row[0]
            logger.debug(f"[HISTORY] Found chat_id={chat_id} for channel {channel}")

        # Формируем датестроки для SQLite (в формате YYYY-MM-DD HH:MM:SS)
        begin_sql = begin.replace(microsecond=0).isoformat(sep=" ", timespec="seconds")
        end_sql = end.replace(microsecond=0).isoformat(sep=" ", timespec="seconds")

        logger.debug(f"[HISTORY] Converting dates for SQL query:")
        logger.debug(f"  begin: {begin} -> {begin_sql}")
        logger.debug(f"  end:   {end} -> {end_sql}")

        # Сначала проверим, какие вообще сообщения есть в этом канале
        async with self._connection.execute(
                f"SELECT COUNT(*) FROM messages WHERE chat_id = ?", (chat_id,)
        ) as cursor:
            total_count = await cursor.fetchone()
            logger.debug(f"[HISTORY] Total messages in channel {channel}: {total_count[0]}")

        # Выведем несколько первых и последних сообщений для контекста
        async with self._connection.execute(
                f"SELECT created_at FROM messages WHERE chat_id = ? ORDER BY created_at ASC LIMIT 1",
                (chat_id,)
        ) as cursor:
            first_msg = await cursor.fetchone()
            if first_msg:
                logger.debug(f"[HISTORY] First message in channel: {first_msg[0]}")

        async with self._connection.execute(
                f"SELECT created_at FROM messages WHERE chat_id = ? ORDER BY created_at DESC LIMIT 1",
                (chat_id,)
        ) as cursor:
            last_msg = await cursor.fetchone()
            if last_msg:
                logger.debug(f"[HISTORY] Last message in channel: {last_msg[0]}")

        # Выполняем основной запрос
        query = """SELECT m.created_at, u.nick, m.text_ 
                   FROM messages m 
                   JOIN users u ON m.author_id = u.id 
                   WHERE m.chat_id = ? AND m.created_at BETWEEN ? AND ? 
                   ORDER BY m.created_at ASC"""

        logger.debug(f"[HISTORY] Executing SQL query:")
        logger.debug(f"  {query}")
        logger.debug(f"  Parameters: chat_id={chat_id}, begin_sql={begin_sql}, end_sql={end_sql}")

        async with self._connection.execute(query, (chat_id, begin_sql, end_sql)) as cursor:
            rows = await cursor.fetchall()
            logger.info(f"[HISTORY] Query returned {len(rows)} messages")

            for i, row in enumerate(rows):
                logger.debug(f"[HISTORY] Message {i}: timestamp={row[0]}, nick={row[1]}, text={row[2]}")

            return [(row[0], row[1], row[2]) for row in rows]

    async def delete_message(self) -> None:
        raise NotImplementedError

    async def delete_user(self) -> None:
        raise NotImplementedError

    async def register(self, nick: str, password: str) -> bool:
        """Register a new user. Returns True on success, False if nick already exists."""
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
        """Verify user credentials. Returns True if valid, False otherwise."""
        async with self._connection.execute(
                "SELECT COUNT(*) FROM users WHERE nick = ? AND password_hash = ?",
                (nick, self.hash(password)),
        ) as cursor:
            result = await cursor.fetchone()
            if result:
                return result[0] == 1
        return False

    async def user_exists(self, nick: str) -> bool:
        """Check if user exists."""
        async with self._connection.execute(
                "SELECT COUNT(*) FROM users WHERE nick = ?", (nick,)
        ) as cursor:
            result = await cursor.fetchone()
            if result:
                return result[0] > 0
        return False

    @classmethod
    def hash(cls, password: str) -> str:
        return hashlib.sha3_512((password + cls._SALT).encode()).hexdigest()


def args_required(min_args: int = 0, max_args: int = None):
    """Проверить количество аргументов (min_args обязательно, max_args необязательно)"""

    def decorator(fn) -> t.Callable[..., t.Awaitable[None]]:
        @functools.wraps(fn)
        async def wrapper(self, client, args, text):
            if len(args) < min_args:
                logger.debug(f"[COMMAND] Not enough args for {fn.__name__}: got {len(args)}, need {min_args}")
                return
            if max_args is not None and len(args) > max_args:
                logger.debug(f"[COMMAND] Too many args for {fn.__name__}: got {len(args)}, max {max_args}")
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
        self._authenticated = False
        self._channels: set[str] = set()  # Каналы, к которым присоединен клиент

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
        logger.debug(f"[SEND] Sending to {self.ip}:{self.port}: {line}")
        self._writer.write((line + "\r\n").encode("utf-8"))
        await self._writer.drain()

    def close(self) -> None:
        self._writer.close()


def parse_command(line: str) -> tuple[str, list[str], str]:
    """Parse IRC command: COMMAND arg1 arg2 :trailing text

    Special handling for HISTORY command which has RFC 3339 dates with colons
    """
    # Проверяем, это HISTORY команда?
    if line.startswith("HISTORY "):
        parts = line.split()
        if len(parts) >= 4:
            # HISTORY start_date end_date channel [optional text]
            command = parts[0]
            args = parts[1:4]  # первые 3 аргумента (даты и канал)
            text = " ".join(parts[4:]) if len(parts) > 4 else ""
            return command, args, text

    # Для остальных команд используем старую логику
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
        """Отправить сообщение всем клиентам в канале"""
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
                    # Соединение разорвано, отключаем клиента от всех каналов
                    await self._disconnect_client(client)
                    break
                await self._process_command(client, text.decode().rstrip())
        finally:
            client.close()

    async def _disconnect_client(self, client: Client) -> None:
        """Отключить клиента от всех каналов (при разрыве соединения)"""
        channels_to_quit = list(client._channels)

        for channel in channels_to_quit:
            self._channels[channel].discard(client)
            await self.broadcast(
                channel,
                f"{client.prefix} QUIT :Connection lost",
                exclude=client,
            )

        client._channels.clear()
        logger.info("%s:%d disconnected", client.ip, client.port)

    async def _process_command(self, client: Client, line: str) -> None:
        logger.debug(f"[COMMAND] Received from {client.ip}:{client.port}: {line}")

        COMMANDS: dict[str, t.Callable[[Client, list[str], str], t.Awaitable[None]]] = {
            "JOIN": self._join,
            "PART": self._part,
            "QUIT": self._quit,
            "REG": self._reg,
            "LOGIN": self._login,
            "PRIVMSG": self._privmsg,
            "HISTORY": self._history,
        }

        command, args, text = parse_command(line)
        logger.debug(f"[COMMAND] Parsed: command={command}, args={args}, text={text}")

        # Проверка: может ли пользователь выполнить эту команду?
        # Если не аутентифицирован, разрешены только REG, LOGIN, QUIT и HISTORY
        if not client._authenticated:
            if command not in ("REG", "LOGIN", "QUIT", "HISTORY"):
                await client.send("ERR not authenticated")
                logger.warning("%s:%d tried to use %s without authentication", client.ip, client.port, command)
                return

        if fn := COMMANDS.get(command):
            logger.debug(f"[COMMAND] Executing {command} with args {args}")
            await fn(client, args, text)
        else:
            logger.warning("unknown command '%s'", command)

    @args_required(min_args=1, max_args=1)
    async def _join(self, client: Client, args: list[str], text: str) -> None:
        """Присоединение к каналу"""
        channel = args[0]

        # Если уже в этом канале, ничего не делаем
        if channel in client._channels:
            logger.warning("%s:%d already in channel %s", client.ip, client.port, channel)
            return

        # Добавляем клиента в канал
        self._channels[channel].add(client)
        client._channels.add(channel)

        logger.info("%s:%d joined channel %s", client.ip, client.port, channel)

        # Отправляем сообщение о присоединении ТОЛЬКО другим клиентам (exclude=client)
        await self.broadcast(
            channel,
            f"{client.prefix} JOIN {channel}",
            exclude=client
        )

    @args_required(min_args=1, max_args=1)
    async def _part(self, client: Client, args: list[str], text: str) -> None:
        """Выход из канала (PART <channel> [:message])"""
        channel = args[0]

        # Если не в этом канале, ничего не делаем
        if channel not in client._channels:
            await client.send(f"ERR not in channel {channel}")
            logger.warning("%s:%d tried to part channel %s without being in it",
                           client.ip, client.port, channel)
            return

        # Удаляем клиента из канала
        self._channels[channel].discard(client)
        client._channels.discard(channel)

        logger.info("%s:%d left channel %s", client.ip, client.port, channel)

        # Отправляем сообщение о выходе только ДРУГИМ клиентам в канале
        part_message = text if text else "leaving"
        await self.broadcast(
            channel,
            f"{client.prefix} PART {channel} :{part_message}",
            exclude=client
        )

    @args_required(min_args=0)
    async def _quit(self, client: Client, args: list[str], text: str) -> None:
        """
        Выход из всех каналов или только текущего (если аргумент не указан или '-c')
        /QUIT - выход из текущего канала (alias для /PART)
        /QUIT -a - полное отключение от сервера
        """
        # Если есть флаг -a, то полное отключение
        if args and args[0] == "-a":
            quit_message = text if text else "Client quit"
            await self._disconnect_client(client)
            # Отправляем сигнал клиенту о полном выходе
            await client.send(f"QUIT :{quit_message}")
            client.close()
            logger.info("%s:%d quit completely from server", client.ip, client.port)
            return

        # По умолчанию - выход из последнего активного канала (если он есть)
        # Эта логика должна быть в клиенте, но мы можем вывести ошибку
        if not client._channels:
            await client.send("ERR not in any channel")
            logger.warning("%s:%d tried to quit without being in a channel", client.ip, client.port)
            return

        # Берем последний канал из списка (Python 3.7+ гарантирует порядок в set через defaultdict)
        channel = next(iter(client._channels))

        # Удаляем клиента из канала
        self._channels[channel].discard(client)
        client._channels.discard(channel)

        logger.info("%s:%d quit from channel %s", client.ip, client.port, channel)

        # Отправляем сообщение о выходе только ДРУГИМ клиентам в канале
        quit_message = text if text else "leaving"
        await self.broadcast(
            channel,
            f"{client.prefix} QUIT :{quit_message}",
            exclude=client
        )

    @args_required(min_args=2, max_args=2)
    async def _reg(self, client: Client, args: list[str], _text: str) -> None:
        """Регистрация нового пользователя"""
        nick, password = args

        # Если уже аутентифицирован, не позволяем переристрироваться
        if client._authenticated:
            await client.send("ERR already authenticated")
            logger.warning("%s:%d tried to register while authenticated as %s", client.ip, client.port, client.nick)
            return

        result = await self._storage.register(nick, password)
        if result:
            client._nick = nick
            client._authenticated = True
            logger.info("new user registered and authenticated. nick=%s from %s:%d", nick, client.ip, client.port)
            await client.send(f"REGD {nick}")
        else:
            await client.send("ERR nick already taken")
            logger.warning("%s:%d tried to register with taken nick %s", client.ip, client.port, nick)

    @args_required(min_args=2, max_args=2)
    async def _login(self, client: Client, args: list[str], _text: str) -> None:
        """Логин существующего пользователя"""
        nick, password = args

        # Если уже аутентифицирован, не позволяем переавторизоваться
        if client._authenticated:
            await client.send("ERR already authenticated")
            logger.warning("%s:%d tried to login while authenticated as %s", client.ip, client.port, client.nick)
            return

        # Проверяем, существует ли пользователь и верен ли пароль
        result = await self._storage.verify(nick, password)
        if result:
            client._nick = nick
            client._authenticated = True
            logger.info("user logged in. nick=%s from %s:%d", nick, client.ip, client.port)
            await client.send(f"LOGIN {nick}")
        else:
            # Не различаем "пользователь не существует" и "неверный пароль" для безопасности
            await client.send("ERR invalid nick or password")
            logger.warning("%s:%d failed login attempt with nick %s", client.ip, client.port, nick)

    @args_required(min_args=1, max_args=1)
    async def _privmsg(self, client: Client, args: list[str], text: str) -> None:
        """Отправка сообщения в канал"""
        channel_name = args[0]

        # Проверяем, присоединен ли клиент к этому каналу
        if channel_name not in client._channels:
            await client.send(f"ERR not in channel {channel_name}")
            logger.warning("%s:%d tried to send message to channel %s without being in it",
                           client.ip, client.port, channel_name)
            return

        # Проверяем, существует ли канал
        if channel_name not in self._channels:
            await client.send(f"ERR channel {channel_name} does not exist")
            return

        # Сохраняем сообщение в БД
        await self._storage.store_message(client.nick, text)
        logger.info("%s:%d sent message to %s", client.ip, client.port, channel_name)

        # Отправляем сообщение ТОЛЬКО другим клиентам в канале (exclude=client)
        await self.broadcast(
            channel_name,
            f"{client.prefix} PRIVMSG {channel_name} :{text}",
            exclude=client,
        )

    @args_required(min_args=3, max_args=3)
    async def _history(self, client: Client, args: list[str], text: str) -> None:
        """
        Получить историю сообщений из канала
        HISTORY <start_date> <end_date> <channel>
        Даты в формате RFC 3339: 2025-11-16T19:00:00Z

        Команда работает только для авторизованных пользователей
        Пользователь НЕ обязан быть в канале
        """
        start_str, end_str, channel = args

        logger.info(f"\n{'=' * 80}")
        logger.info(f"[HISTORY] COMMAND RECEIVED from {client.ip}:{client.port}")
        logger.info(f"[HISTORY] start_str = '{start_str}'")
        logger.info(f"[HISTORY] end_str = '{end_str}'")
        logger.info(f"[HISTORY] channel = '{channel}'")
        logger.info(f"[HISTORY] Client nick: {client.nick}")
        logger.info(f"{'=' * 80}\n")

        # Валидируем даты (простая проверка формата)
        try:
            logger.debug(f"[HISTORY] Attempting to parse dates...")
            # Пытаемся распарсить даты в формате RFC 3339
            start_str_iso = start_str.replace('Z', '+00:00')
            end_str_iso = end_str.replace('Z', '+00:00')

            logger.debug(f"[HISTORY] After Z replacement:")
            logger.debug(f"  start_str_iso = '{start_str_iso}'")
            logger.debug(f"  end_str_iso = '{end_str_iso}'")

            start = datetime.datetime.fromisoformat(start_str_iso)
            end = datetime.datetime.fromisoformat(end_str_iso)

            logger.info(f"[HISTORY] Successfully parsed dates:")
            logger.info(f"  start = {start} (type: {type(start)})")
            logger.info(f"  end = {end} (type: {type(end)})")

        except ValueError as e:
            logger.error(f"[HISTORY] Date parsing FAILED: {e}")
            logger.error(f"[HISTORY] Sending error to client...")
            await client.send("ERR invalid date format. Use RFC 3339 (e.g., 2025-11-16T19:00:00Z)")
            return

        # Получаем сообщения из БД (пользователь не обязан быть в канале!)
        logger.info(f"[HISTORY] Calling storage.get_messages()...")
        messages = await self._storage.get_messages(channel, start, end)
        logger.info(f"[HISTORY] Returned {len(messages)} messages from storage")

        if not messages:
            logger.warning(f"[HISTORY] No messages found, sending empty response")
            await client.send(f"HISTORY {channel} :no messages")
            logger.info("%s:%d requested empty history for %s", client.ip, client.port, channel)
            return

        # Отправляем каждое сообщение клиенту
        logger.info(f"[HISTORY] Sending HISTORY_START...")
        await client.send(f"HISTORY_START {channel} {len(messages)}")

        for i, (timestamp, nick, text_msg) in enumerate(messages):
            logger.debug(f"[HISTORY] Sending message {i + 1}/{len(messages)}: [{timestamp}] {nick}: {text_msg}")
            await client.send(f"HISTORY_MSG {channel} {timestamp} {nick} :{text_msg}")

        logger.info(f"[HISTORY] Sending HISTORY_END...")
        await client.send(f"HISTORY_END {channel}")

        logger.info(f"[HISTORY] History request completed successfully\n")

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
