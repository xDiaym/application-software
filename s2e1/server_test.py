import pytest

from server import args_required


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