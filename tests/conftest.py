from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))


def run_module(
    *arguments: str, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    return subprocess.run(
        [sys.executable, "-m", "skillroll", *arguments],
        cwd=ROOT if cwd is None else cwd,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
