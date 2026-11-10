"""Idempotent dataset preparation for local development and backend deployment.

Run after installing requirements: python backend/prepare_data.py
Never called by the HTTP API; run as a separate deployment/setup step.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
MARKER = PROCESSED / ".prepared.json"
SPLITS = ("train.csv", "validation.csv", "test.csv")


def prepare():
    from download_data import SHA256, download

    raw = download(RAW_DIR)  # verifies SHA256 even when the file already exists
    signature = {"raw_sha256": SHA256, "pipeline_sha256": hashlib.sha256(
        (ROOT / "backend" / "preprocessing.py").read_bytes()
        + (ROOT / "backend" / "data_loader.py").read_bytes()
    ).hexdigest()}
    if MARKER.is_file() and all((PROCESSED / f).is_file() and (PROCESSED / f).stat().st_size > 0 for f in SPLITS):
        try:
            if json.loads(MARKER.read_text()) == signature:
                print("Dataset verified; processed splits already current.")
                return
        except (ValueError, OSError):
            pass
    MARKER.unlink(missing_ok=True)
    subprocess.run([sys.executable, str(ROOT / "backend" / "preprocessing.py")], cwd=ROOT, check=True)
    if not all((PROCESSED / f).is_file() and (PROCESSED / f).stat().st_size > 0 for f in SPLITS):
        raise RuntimeError("Dataset preprocessing did not create all three split files")
    MARKER.write_text(json.dumps(signature, indent=2) + "\n")
    print("Dataset preparation complete:", raw)


if __name__ == "__main__":
    prepare()
