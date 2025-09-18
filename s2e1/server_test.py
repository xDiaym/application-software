from datetime import datetime
import pytest
import aiosqlite

from server import SQLiteStorage, args_required


@pytest.fixture(scope="function")
async def connection():
    conn = await aiosqlite.connect(":memory:")
    yield conn
    await conn.close()


@pytest.fixture()
async def storage(connection):
    storage = SQLiteStorage(connection)
    await storage.init_schema()
    return storage


@pytest.mark.parametrize(
    ["n_args", "args", "called"],
    [
        (0, [], True),
        (1, ["a"], True),
        (1, ["a", "b"], False),
        (2, ["a"], False),
        (0, ["a"], False),
    ],
)
async def test_args_required(n_args, args, called):
    class Klass:
        @args_required(n_args)
        async def f(self, client, args, text):
            assert called

    await Klass().f(None, args, "")


async def test_storage_register(storage, connection):
    assert await storage.register("nick", "password")
    async with connection.execute("SELECT * FROM users WHERE nick = 'nick'") as cursor:
        assert await cursor.fetchall() == [(1, "nick", SQLiteStorage.hash("password"))]

    assert not await storage.register("nick", "pa55word")
    async with connection.execute("SELECT COUNT(*) FROM users") as cursor:
        assert await cursor.fetchall() == [(2,)]


@pytest.mark.parametrize(
    ["nick", "password", "is_authenticated"],
    [
        ("nick", "password", True),
        ("n1ck", "password", False),
        ("nick", "pa55word", False),
    ],
)
async def test_storage_verify(storage, nick, password, is_authenticated):
    await storage.register("nick", "password")
    assert await storage.verify(nick, password) == is_authenticated


async def test_storage_store_message(storage, connection):
    await storage.register("nick", "password")
    await storage.store_message("nick", "text")
    async with connection.execute("SELECT text_ FROM messages LIMIT 1") as cursor:
        assert await cursor.fetchone() == ("text",)

    await storage.store_message("n1ck", "text2")
    async with connection.execute("SELECT COUNT(*) FROM messages") as cursor:
        assert await cursor.fetchone() == (1,)


async def test_storage_get_messages(storage, connection):
    await storage.register("nick", "password")
    async with connection.execute(
        """INSERT INTO messages(author_id, chat_id, created_at, text_) VALUES
            (1, 1, '2000-01-01T00:00:00', 'a'),
            (1, 1, '2000-01-02T00:00:00', 'b'),
            (1, 1, '2000-01-03T00:00:00', 'c');"""
    ) as cursor:
        await connection.commit()

    assert await storage.get_messages(
        "#global", datetime(2000, 1, 1), datetime(2000, 1, 3)
    ) == ["a", "b", "c"]
    assert await storage.get_messages(
        "#global", datetime(2000, 1, 2), datetime(2000, 1, 3)
    ) == ["b", "c"]
    assert await storage.get_messages(
        "#global", datetime(2001, 1, 1), datetime(2001, 1, 3)
    ) == []
    assert await storage.get_messages(
        "#none", datetime(2000, 1, 1), datetime(2000, 1, 3)
    ) == []