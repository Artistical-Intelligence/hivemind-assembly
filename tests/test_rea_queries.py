import pytest
from hivemind_assembly.core.common import ContractError
from hivemind_assembly.domains.reverse_engineering.bridges import ReaBridge


class Capture(ReaBridge):
    def run(self, command, target, cwd, args=(), cancel=None):
        return command, list(args)


def test_rea_queries_use_typed_literal_arguments():
    bridge = Capture(None, None)
    command, args = bridge.query(
        "binary",
        ".",
        {"action": "search", "selector": "--snapshot=/outside", "kind": "procedures"},
    )
    assert command == "search"
    assert "--pattern=--snapshot=/outside" in args
    assert "--snapshot" not in args
    assert args[-2:] == ["--mode", "literal"]
    command, args = bridge.query(
        "binary",
        ".",
        {
            "action": "trace-native-values",
            "selector": "main",
            "offset": 50,
            "limit": 10,
        },
    )
    assert command == "trace-native-values" and args[0] == "main"
    assert args[-4:] == ["--offset", "50", "--limit", "10"]
    for request in (
        {"action": "attach", "selector": "123"},
        {"action": "read-bytes", "selector": "--help"},
        {"action": "search", "selector": "ok", "output": "/outside"},
        {"action": "read-bytes", "selector": "0x4000", "length": 1000000},
    ):
        with pytest.raises(ContractError):
            bridge.query("binary", ".", request)
