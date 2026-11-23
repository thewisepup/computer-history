import importlib.util


def test_setproctitle_is_not_installed():
    assert importlib.util.find_spec("setproctitle") is None, (
        "setproctitle is installed, so pytest-xdist renames every worker before every test; "
        "on macOS each rename goes through LaunchServices and parallel runs freeze every open "
        "app. Remove it with: python -m pip uninstall -y setproctitle "
        "(mutmut, which pulls it in, belongs to the mutation extra, not dev)"
    )
