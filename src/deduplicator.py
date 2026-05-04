import json
from pathlib import Path

SEEN_FILE = Path(__file__).parent.parent / "data" / "seen_jobs.json"


def load_seen() -> set:
    if SEEN_FILE.exists():
        with open(SEEN_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_seen(seen: set):
    SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen), f)


def filter_new(jobs: list[dict]):
    seen = load_seen()
    new_jobs = [j for j in jobs if j["id"] not in seen]
    updated_seen = seen | {j["id"] for j in jobs}
    return new_jobs, updated_seen