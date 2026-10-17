"""Owner 112A: CLI defaults come from the simulator at command invocation."""

from types import SimpleNamespace

from typer.testing import CliRunner

from swreview import cli
from swreview.benchmark import simulate


def test_simulate_cli_uses_shared_defaults(monkeypatch):
    expected = {"seed": 123, "sims": 17, "cap": 6}
    for field, value in expected.items():
        monkeypatch.setattr(simulate, "DEFAULT_" + field.upper(), value, raising=False)
    calls = []

    def search(scenario, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(as_dict=lambda: {})

    monkeypatch.setattr(simulate, "search", search)
    monkeypatch.setattr(simulate, "scenario_inputs", lambda *args, **kwargs: kwargs)
    monkeypatch.setattr(simulate, "render_result", lambda *args, **kwargs: "fictional result")
    result = CliRunner().invoke(cli.app, [
        "benchmark", "simulate", "--scenario", next(iter(simulate.SCENARIOS)), "--json",
    ], catch_exceptions=False)
    assert result.exit_code == 0, result.output
    assert calls == [expected]
