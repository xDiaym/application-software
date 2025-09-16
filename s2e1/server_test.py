import hashlib
import pytest
import aiosqlite

from server import SQLiteStorage, args_required


@pytest.fixture(scope="module")
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
    ['n_args', 'args', 'called'],
    [
        (0, [], True),
        (1, ["a"], True),
        (1, ["a", "b"], False),
        (2, ["a"], False),
        (0, ["a"], False),
    ]
)
async def test_args_required(n_args, args, called):
    class Klass:
        @args_required(n_args)
        async def f(self, client, args, text):
            assert called
    await Klass().f(None, args, "")


async def test_storage_register(storage, connection):
    assert await storage.register("nick", "password") == True
    async with connection.execute("SELECT * FROM users") as cursor:
        assert await cursor.fetchall() == [(1, 'nick', SQLiteStorage.hash("password"))]

    assert await storage.register("nick", "pa55word") == False
    async with connection.execute("SELECT COUNT(*) FROM users") as cursor:
        assert await cursor.fetchall() == [(1, )]


@pytest.mark.parametrize(
    ['nick', 'password', 'is_authenticated'],
    [
        ('nick', 'password', True),
        ('n1ck', 'password', False),
        ('nick', 'pa55word', False),
    ]
)
async def test_storage_verify(storage, connection, nick, password, is_authenticated):
    await storage.register("nick", "password")
    assert await storage.verify(nick, password) == is_authenticated


async def test_store_message(storage, connection):
    await storage.register("nick", "password")
    await storage.store_message("nick", "text")
    async with connection.execute("SELECT text_ FROM messages LIMIT 1") as cursor:
        assert await cursor.fetchone() == ("text", )

    await storage.store_message("n1ck", "text2")
    async with connection.execute("SELECT COUNT(*) FROM messages") as cursor:
        assert await cursor.fetchone() == (1, )