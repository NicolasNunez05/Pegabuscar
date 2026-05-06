import re
from datetime import datetime, timezone, timedelta
from config import (
    HIGH_VALUE_SKILLS, MEDIUM_VALUE_SKILLS,
    EXCLUDE_TITLES, VALID_LOCATIONS,
    MAX_AGE_HOURS, MIN_SCORE, MAX_YEARS_EXPERIENCE,
)


def _text(job: dict) -> str:
    return (
        f"{job.get('title', '')} "
        f"{job.get('company', '')} "
        f"{job.get('description', '')} "
        f"{job.get('location', '')}"
    ).lower()


def is_excluded(job: dict) -> bool:
    title = job.get("title", "").lower()
    return any(ex in title for ex in EXCLUDE_TITLES)


def is_valid_location(job: dict) -> bool:
    loc = job.get("location", "").lower()
    return any(v in loc for v in VALID_LOCATIONS)


def is_too_old(job: dict) -> bool:
    pub = job.get("published_at")
    if pub is None:
        return False
    now = datetime.now(timezone.utc)
    return (now - pub) > timedelta(hours=MAX_AGE_HOURS)


def has_too_much_experience_required(job: dict) -> bool:
    if MAX_YEARS_EXPERIENCE is None:
        return False
    text = _text(job)
    # Regex más estricto: solo captura cuando hay contexto claro de experiencia
    matches = re.findall(
        r'\b(\d{1,2})\s*(?:\+)?\s*(?:años?|years?)\s*(?:de\s*)?(?:experiencia|experience)',
        text
    )
    if not matches:
        return False
    return any(int(m) > MAX_YEARS_EXPERIENCE for m in matches)



def score_job(job: dict) -> int:
    text = _text(job)
    score = 0
    high_hits = [s for s in HIGH_VALUE_SKILLS if s in text]
    score += min(len(high_hits) * 12, 60)
    mid_hits = [s for s in MEDIUM_VALUE_SKILLS if s in text]
    score += min(len(mid_hits) * 5, 20)
    title = job.get("title", "").lower()
    if any(w in title for w in ["junior", "jr", "trainee", "práctica", "practicante"]):
        score += 10
    if any(w in title for w in ["remoto", "remote", "híbrido", "hybrid"]):
        score += 10
    return min(score, 100)


def get_matched_skills(job: dict) -> list[str]:
    text = _text(job)
    hits = [s for s in HIGH_VALUE_SKILLS if s in text]
    hits += [s for s in MEDIUM_VALUE_SKILLS if s in text]
    return list(dict.fromkeys(hits))


def filter_and_score(jobs: list[dict]) -> list[dict]:
    results = []
    excluded = loc_fail = too_old = too_exp = low_score = 0
    for job in jobs:
        if is_excluded(job):
            excluded += 1
            continue
        if not is_valid_location(job):
            loc_fail += 1
            continue
        if is_too_old(job):
            too_old += 1
            continue
        if has_too_much_experience_required(job):
            too_exp += 1
            continue
        s = score_job(job)
        if s < MIN_SCORE:
            low_score += 1
            continue
        job["score"] = s
        job["matched_skills"] = get_matched_skills(job)
        results.append(job)

    import logging
    log = logging.getLogger("scorer")
    log.info(f"Filtros → excluidos:{excluded} ubicación:{loc_fail} muy_viejo:{too_old} mucha_exp:{too_exp} score_bajo:{low_score} → pasaron:{len(results)}")

    results.sort(key=lambda x: x["score"], reverse=True)
    return results
