import os, sys, logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import SEARCH_QUERIES
from scrapers import (scrape_getonboard, scrape_laborum,
                      scrape_chiletrabajos, scrape_computrabajo,
                      scrape_duoclaboral, scrape_google_jobs)
from enricher import enrich_jobs
from scorer import filter_and_score
from deduplicator import filter_new, save_seen
from emailer import send_email

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger("main")


def run():
    logger.info("=" * 50)
    logger.info("Pegabuscar iniciado")
    logger.info("=" * 50)

    all_jobs = []
    scrapers = [
        ("Get on Board",  lambda: scrape_getonboard(SEARCH_QUERIES)),
        ("Laborum",       lambda: scrape_laborum(SEARCH_QUERIES[:6])),
        ("Chiletrabajos", lambda: scrape_chiletrabajos(SEARCH_QUERIES[:6])),
        ("Computrabajo",  lambda: scrape_computrabajo(SEARCH_QUERIES[:6])),
    ]

    duoc_email = os.environ.get("DUOC_EMAIL", "")
    duoc_pass  = os.environ.get("DUOC_PASSWORD", "")
    if duoc_email and duoc_pass:
        scrapers.append(("Duoc Laboral", lambda: scrape_duoclaboral(SEARCH_QUERIES, duoc_email, duoc_pass)))
    else:
        logger.info("Duoc Laboral: credenciales no configuradas, saltando.")

    serpapi_key = os.environ.get("SERPAPI_KEY", "")
    if serpapi_key:
        scrapers.append(("Google Jobs", lambda: scrape_google_jobs(SEARCH_QUERIES[:5], serpapi_key)))
    else:
        logger.info("Google Jobs: SERPAPI_KEY no configurada, saltando.")

    for name, fn in scrapers:
        logger.info(f"Scrapeando {name}...")
        try:
            jobs = fn()
            logger.info(f"  → {len(jobs)} encontradas")
            all_jobs.extend(jobs)
        except Exception as e:
            logger.error(f"  ✗ {name} falló: {e}")

    total = len(all_jobs)
    logger.info(f"Total scrapeado: {total}")

    logger.info("Enriqueciendo descripciones...")
    all_jobs = enrich_jobs(all_jobs)

    scored = filter_and_score(all_jobs)
    logger.info(f"Pasaron filtros: {len(scored)}")

    new_jobs, updated_seen = filter_new(scored)
    logger.info(f"Nuevas esta hora: {len(new_jobs)}")

    save_seen(updated_seen)
    send_email(new_jobs, total)
    logger.info(f"✅ Listo. {len(new_jobs)} nuevas enviadas.")


if __name__ == "__main__":
    run()