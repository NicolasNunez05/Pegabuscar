import time
import logging
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("enricher")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

def _fetch(url: str) -> str:
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        # Elimina scripts y estilos del HTML
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()
        # Intenta encontrar la sección de descripción
        for selector in [
            "[class*='description']", "[class*='job-detail']",
            "[class*='oferta']", "[class*='detalle']",
            "article", "main", ".content", "#content",
        ]:
            el = soup.select_one(selector)
            if el and len(el.get_text(strip=True)) > 100:
                return el.get_text(separator=" ", strip=True)[:3000]
        # Fallback: todo el body
        body = soup.find("body")
        return body.get_text(separator=" ", strip=True)[:3000] if body else ""
    except Exception as e:
        logger.debug(f"Enrich failed for {url}: {e}")
        return ""

def enrich_jobs(jobs: list[dict], max_jobs: int = 150) -> list[dict]:
    """Entra a la URL de cada job y agrega la descripción real."""
    enriched = 0
    for job in jobs[:max_jobs]:
        if job.get("description") and len(job["description"]) > 200:
            continue  # ya tiene descripción (Google Jobs la da)
        url = job.get("url", "")
        if not url:
            continue
        desc = _fetch(url)
        if desc:
            job["description"] = desc
            enriched += 1
        time.sleep(0.8)  # no abusar
    logger.info(f"Enriquecidos: {enriched}/{len(jobs)} trabajos")
    return jobs