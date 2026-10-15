"""Run the unchanged owner-mapped generators with their recorded runtime inputs."""

from __future__ import annotations

import argparse
import contextlib
import io
import os
import sys
import tempfile
import traceback
from collections.abc import Sequence
from pathlib import Path

import pytest

REVIEWER = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REVIEWER))
sys.path.insert(0, str(REVIEWER / "src"))

from tests.support.mechanical import load_generator  # noqa: E402
from tests.support.recordings import RECORDING_NAMES, recording_folder  # noqa: E402
from tests.support.replay_inputs import ReplayBaseline, seed_replay_inputs  # noqa: E402


def main(argv: Sequence[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    try:
        recordings = {name: recording_folder(name) for name in RECORDING_NAMES}
    except pytest.skip.Exception:
        print("Replay verification skipped: the owner mapping or a mapped recording is absent.")
        return 0
    except pytest.fail.Exception:
        print("Replay verification refused: the owner mapping is invalid.", file=sys.stderr)
        return 1
    baselines = {
        name: ReplayBaseline.from_folder(REVIEWER / "tests/fixtures/replay" / name)
        for name in RECORDING_NAMES
    }
    generator = load_generator(REVIEWER / "tests/fixtures/replay/generate_fixtures.py")
    log_root = Path(tempfile.mkdtemp(prefix="swreview-replay-verification-"))
    previous = Path.cwd()
    try:
        os.chdir(REVIEWER)
        for name in RECORDING_NAMES:
            args = ["--recorded", str(recordings[name]), "--name", name]
            if name == "big-assembly":
                args += ["--groups", "113"]
            private = io.StringIO()
            result = 1
            try:
                with contextlib.redirect_stdout(private), contextlib.redirect_stderr(private):
                    with seed_replay_inputs(baselines[name]):
                        result = generator.main(args)
            except (Exception, SystemExit):
                result = 1
                private.write(traceback.format_exc())
            finally:
                (log_root / f"{name}.log").write_text(private.getvalue(), encoding="utf-8")
            if result != 0:
                print(f"{name}: verification refused; private diagnostic log retained.")
                return result
            print(f"{name}: unchanged generator completed with seeded runtime inputs.")
    finally:
        os.chdir(previous)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
