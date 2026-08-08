from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent

INPUT_DIR = ROOT_DIR / "input"
OUTPUT_DIR = ROOT_DIR / "output"
WORK_DIR = ROOT_DIR / ".m3talist"

DB_FILE = WORK_DIR / "catalog.db"
CONFIG_FILE = ROOT_DIR / "config.toml"
CALIBRATE_DIR = OUTPUT_DIR / "_calibrate"


def prepare_paths() -> None:
    for directory in (INPUT_DIR, OUTPUT_DIR, WORK_DIR):
        directory.mkdir(parents=True, exist_ok=True)
