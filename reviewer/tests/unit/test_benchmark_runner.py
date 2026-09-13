"""Unit tests for the benchmark runner's own default review function (T023).

Every other test that reaches `run_benchmark` injects a `review_fn`, and so does
`swreview.cli.benchmark_run`, which means `_default_review_fn` - the wiring a caller gets
when it asks for none - has never been executed by the suite. A wrong keyword there (the
runner takes `key_source=`, not `key=`) would ship green. `--provider fake` needs no
credential, so exercising it costs nothing but still runs the whole path: settings,
adapter, turn, `session.json`.
"""

from __future__ import annotations

import json
from pathlib import Path

from swreview.agent.providers import ProviderName
from swreview.agent.settings import DEFAULT_EFFORT, default_model
from swreview.benchmark.runner import run_benchmark

FAKE_MODEL = default_model(ProviderName.FAKE)


def write_set(path: Path, package_dir: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "name": "pilot",
                "packages": [{"package_id": "cover", "path": str(package_dir), "held_out": True}],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_run_benchmark_without_a_review_fn_reviews_the_set_on_the_named_provider(
    tmp_path: Path, tmp_package_dir: Path
) -> None:
    set_path = write_set(tmp_path / "sets" / "pilot.json", tmp_package_dir)
    out_dir = tmp_path / "runs" / "default-review-fn"

    package_dirs = run_benchmark(
        set_path,
        out_dir,
        provider=ProviderName.FAKE.value,
        model=FAKE_MODEL,
        effort=DEFAULT_EFFORT,
    )

    assert package_dirs == [out_dir / "cover"]
    session = json.loads((out_dir / "cover" / "session.json").read_text(encoding="utf-8"))
    assert session["model"] == FAKE_MODEL
    assert session["provider_info"]["provider"] == ProviderName.FAKE.value
    assert session["provider_info"]["key_source"] == "none"
    assert session["timing"]["unattended_runtime_minutes"] >= 0
    assert (out_dir / "cover" / "events.jsonl").is_file()
