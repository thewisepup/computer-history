import pytest

import computer_history
from computer_history import cli

STUB_COMMANDS = list(cli.COMMANDS)


def test_package_imports() -> None:
    assert computer_history.__name__ == "computer_history"


def test_help_lists_commands(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for command in STUB_COMMANDS:
        assert command in out
    assert "--db-path" in out


@pytest.mark.parametrize("command", STUB_COMMANDS)
def test_stub_commands_exit_nonzero(command: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--db-path", "/unused.db", command]) != 0
    assert "not implemented yet" in capsys.readouterr().err
