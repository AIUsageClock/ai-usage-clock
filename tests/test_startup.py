from aiusageclock.startup import _startup_command


def test_startup_command_uses_module_launcher():
    command = _startup_command()
    assert "-m aiusageclock" in command
    assert command.startswith('"')
