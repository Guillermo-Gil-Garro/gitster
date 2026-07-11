from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class RunPaths:
    run_id: str
    run_dir: Path
    raw_dir: Path
    processed_dir: Path
    reports_dir: Path
    renders_dir: Path


def generate_run_id(seed: int = 666) -> str:
    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    rng = random.Random(seed + int(datetime.now().timestamp()))
    suffix = "".join(rng.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(6))
    return f"{now}_{suffix}"


def create_run_paths(runs_root: Path, run_id: str | None = None, seed: int = 666) -> RunPaths:
    final_run_id = run_id or generate_run_id(seed=seed)

    run_dir = runs_root / final_run_id
    paths = RunPaths(
        run_id=final_run_id,
        run_dir=run_dir,
        raw_dir=run_dir / "raw",
        processed_dir=run_dir / "processed",
        reports_dir=run_dir / "reports",
        renders_dir=run_dir / "renders",
    )
    for directory in (paths.raw_dir, paths.processed_dir, paths.reports_dir):
        directory.mkdir(parents=True, exist_ok=True)
    return paths


def write_run_manifest(
    paths: RunPaths,
    *,
    config_path: str,
    identity_version: str,
    seed: int,
    owners: list[dict],
) -> None:
    manifest = {
        "run_id": paths.run_id,
        "config_path": config_path,
        "identity_version": identity_version,
        "owners": owners,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    params = {"seed": seed, "identity_version": identity_version}

    (paths.run_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (paths.run_dir / "params.json").write_text(
        json.dumps(params, indent=2, ensure_ascii=False), encoding="utf-8"
    )
