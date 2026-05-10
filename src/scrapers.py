import hashlib, re, time, logging
from datetime import datetime, timezone, timedelta
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "es-CL,es;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def _make_id(url, title):
    return hashlib.md5(f"{url}|{title}".lower().strip().encode()).hexdigest()


def _get(url, timeout=15):
    try:
        r = SESSION.get(url, timeout=timeout)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        logger.warning(f"GET failed {url}: {e}")
        return None


def _parse_absolute_date(text: str):
    """Parsea fechas absolutas tipo '24 de marzo de 2026'."""
    meses = {
        "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
        "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
        "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
    }
    m = re.search(r'(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})', text.lower())
    if m:
        day, mes_str, year = int(m.group(1)), m.group(2), int(m.group(3))
        mes = meses.get(mes_str)
        if mes:
            try:
                return datetime(year, mes, day, tzinfo=timezone.utc)
            except ValueError:
                pass
    # Formato DD/MM/YYYY o YYYY-MM-DD
    m2 = re.search(r'(\d{4})-(\d{2})-(\d{2})', text)
    if m2:
        try:
            return datetime(int(m2.group(1)), int(m2.group(2)), int(m2.group(3)), tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def _parse_relative_time(text):
    now = datetime.now(timezone.utc)
    if not text:
        return None
    text_clean = text.lower().strip()
    patterns = [
        (r"(\d+)\s*(minuto|min)",  "minutes"),
        (r"(\d+)\s*(hora|hour)",   "hours"),
        (r"(\d+)\s*(día|dia|day)", "days"),
        (r"(\d+)\s*(semana|week)", "weeks"),
        (r"(\d+)\s*(mes|month)",   "months"),
        (r"hace\s+un\s+(día|dia)", "1day"),
        (r"hoy|today|just posted", "today"),
    ]
    for pattern, unit in patterns:
        m = re.search(pattern, text_clean)
        if m:
            if unit == "today": return now
            if unit == "1day":  return now - timedelta(days=1)
            n = int(m.group(1))
            delta = {
                "minutes": timedelta(minutes=n),
                "hours":   timedelta(hours=n),
                "days":    timedelta(days=n),
                "weeks":   timedelta(weeks=n),
                "months":  timedelta(days=n * 30),
            }[unit]
            return now - delta
    # Intentar parsear fecha absoluta antes de rendirse
    return _parse_absolute_date(text)


# ─────────────────────────────────────────────
# GET ON BOARD (HTML scraping — API deprecada)
# ─────────────────────────────────────────────
def scrape_getonboard(queries):
    jobs, seen = [], set()
    # Categorías relevantes de la API pública real
    categories = [
        "backend-development",
        "devops-sysadmin",
        "data-engineering-bi",
        "qa-testing",
    ]
    for category in categories:
        url = f"https://www.getonbrd.com/api/v0/categories/{category}/jobs?per_page=20&page=0"
        try:
            resp = SESSION.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            items = data.get("data", [])
            for item in items:
                if not isinstance(item, dict):
                    continue
                a = item.get("attributes", {})
                if not isinstance(a, dict):
                    continue
                title       = str(a.get("title", ""))
                company     = str(a.get("company_name", ""))
                modality    = str(a.get("modality", ""))
                country     = str(a.get("country", "Chile"))
                location    = f"{modality} {country}".strip()
                job_url     = str(a.get("url", ""))
                desc_raw    = a.get("description") or a.get("functions") or ""
                description = str(desc_raw)[:2000]
                published_at = None
                raw = a.get("published_at", "")
                if raw:
                    try:
                        published_at = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                    except Exception:
                        pass
                if title and job_url:
                    jid = _make_id(job_url, title)
                    if jid not in seen:
                        seen.add(jid)
                        jobs.append({
                            "id": jid, "title": title, "company": company,
                            "location": location, "url": job_url,
                            "description": description, "published_at": published_at,
                            "source": "Get on Board",
                        })
        except Exception as e:
            logger.warning(f"GetOnBoard error category '{category}': {e}")
        time.sleep(1)
    logger.info(f"GetOnBoard: {len(jobs)} encontradas")
    return jobs


# ─────────────────────────────────────────────
# LABORUM (selectores actualizados 2026)
# ─────────────────────────────────────────────
def scrape_laborum(queries):
    jobs, seen = [], set()
    for q in queries[:6]:
        slug = requests.utils.quote(q.replace(" ", "-"))
        url  = f"https://www.laborum.cl/empleos-busqueda-{slug}.html"
        soup = _get(url)
        if not soup:
            continue

        # Selectores actualizados — estructura Laborum 2025/2026
        cards = soup.select(
            "div.items-offer__item, "
            "div[data-cy='job-card'], "
            "li.offer-item, "
            "article[class*='aviso'], "
            "div[class*='JobCard'], "
            "div[class*='job-item']"
        )
        for card in cards:
            title_el    = card.select_one(
                "h2.offer-item__title a, a[data-cy='job-title'], "
                "h2 a, h3 a, a[class*='title'], [class*='jobTitle']"
            )
            company_el  = card.select_one(
                "span.offer-item__company, [data-cy='company-name'], "
                "[class*='company'], [class*='empresa'], [class*='Company']"
            )
            location_el = card.select_one(
                "li.offer-item__location, [data-cy='location'], "
                "[class*='location'], [class*='ubicacion'], [class*='ciudad']"
            )
            link_el     = card.select_one("a[href]")
            date_el     = card.select_one(
                "time, [class*='date'], [class*='fecha'], [class*='time']"
            )
            title    = title_el.get_text(strip=True)    if title_el    else ""
            company  = company_el.get_text(strip=True)  if company_el  else ""
            location = location_el.get_text(strip=True) if location_el else "Chile"
            href     = link_el.get("href", "")          if link_el     else ""
            if href and not href.startswith("http"):
                href = "https://www.laborum.cl" + href
            date_str     = date_el.get_text(strip=True) if date_el else ""
            published_at = _parse_relative_time(date_str)
            if title and href:
                jid = _make_id(href, title)
                if jid not in seen:
                    seen.add(jid)
                    jobs.append({
                        "id": jid, "title": title, "company": company,
                        "location": location or "Chile", "url": href,
                        "description": f"{title} {company} {location}",
                        "published_at": published_at, "source": "Laborum",
                    })
        time.sleep(2)
    logger.info(f"Laborum: {len(jobs)} encontradas")
    return jobs


# ─────────────────────────────────────────────
# CHILETRABAJOS (sin cambios — funciona OK)
# ─────────────────────────────────────────────
def scrape_chiletrabajos(queries):
    jobs, seen = [], set()
    for q in queries[:6]:
        url  = f"https://www.chiletrabajos.cl/encuentra-un-empleo?action=search&order_by=&ord=&within=25&2={requests.utils.quote(q)}&filterSearch=Buscar"
        soup = _get(url)
        if not soup:
            continue
        for card in soup.select("div[class*='job'], article[class*='job'], div[class*='aviso'], li[class*='job']"):
            title_el    = card.select_one("h2, h3, a[class*='title'], [class*='jobTitle']")
            company_el  = card.select_one("[class*='company'], [class*='empresa']")
            location_el = card.select_one("[class*='location'], [class*='ciudad'], [class*='ubicacion']")
            link_el     = card.select_one("a[href]")
            date_el     = card.select_one("time, [class*='date'], [class*='fecha']")
            title    = title_el.get_text(strip=True)    if title_el    else ""
            company  = company_el.get_text(strip=True)  if company_el  else ""
            location = location_el.get_text(strip=True) if location_el else "Chile"
            href     = link_el.get("href", "")          if link_el     else ""
            if href and not href.startswith("http"):
                href = "https://www.chiletrabajos.cl" + href
            date_str     = date_el.get_text(strip=True) if date_el else ""
            published_at = _parse_relative_time(date_str)
            if title and href:
                jid = _make_id(href, title)
                if jid not in seen:
                    seen.add(jid)
                    jobs.append({
                        "id": jid, "title": title, "company": company,
                        "location": location or "Chile", "url": href,
                        "description": f"{title} {company} {location}",
                        "published_at": published_at, "source": "Chiletrabajos",
                    })
        time.sleep(2)
    return jobs


# ─────────────────────────────────────────────
# COMPUTRABAJO (sin cambios — funciona OK)
# ─────────────────────────────────────────────
def scrape_computrabajo(queries):
    jobs, seen = [], set()
    for q in queries[:6]:
        slug = q.replace(" ", "-").lower()
        url  = f"https://cl.computrabajo.com/trabajo-de-{requests.utils.quote(slug)}"
        soup = _get(url)
        if not soup:
            continue
        for card in soup.select("article[class*='box_offer'], div[class*='offerBlock'], article.job"):
            title_el    = card.select_one("h2 a, h3 a, a[class*='js-o-link'], [class*='title']")
            company_el  = card.select_one("[class*='company'], p[class*='dbl']")
            location_el = card.select_one("[class*='location'], p[class*='fs16']")
            date_el     = card.select_one("p[class*='fc_base'] span, [class*='date'], time")
            title    = title_el.get_text(strip=True)    if title_el    else ""
            company  = company_el.get_text(strip=True)  if company_el  else ""
            location = location_el.get_text(strip=True) if location_el else "Chile"
            href     = title_el.get("href", "")         if title_el    else ""
            if href and not href.startswith("http"):
                href = "https://cl.computrabajo.com" + href
            date_str     = date_el.get_text(strip=True) if date_el else ""
            published_at = _parse_relative_time(date_str)
            if title and href:
                jid = _make_id(href, title)
                if jid not in seen:
                    seen.add(jid)
                    jobs.append({
                        "id": jid, "title": title, "company": company,
                        "location": location or "Chile", "url": href,
                        "description": f"{title} {company} {location}",
                        "published_at": published_at, "source": "Computrabajo",
                    })
        time.sleep(2)
    return jobs


# ─────────────────────────────────────────────
# DUOC LABORAL (sin cambios)
# ─────────────────────────────────────────────
def scrape_duoclaboral(queries, email, password):
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    import time as _time

    opts = Options()
    opts.add_argument("--headless")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")

    jobs, seen = [], set()
    driver = None
    try:
        driver = webdriver.Chrome(options=opts)
        wait = WebDriverWait(driver, 15)
        driver.get("https://duoclaboral.cl/login")
        _time.sleep(3)
        wait.until(EC.visibility_of_element_located((By.ID, "username"))).send_keys(email)
        driver.find_element(By.ID, "password").send_keys(password)
        driver.find_element(By.ID, "userLoginSubmit").click()
        _time.sleep(5)
        if "login" in driver.current_url:
            logger.warning("Duoc Laboral: login fallido")
            return []
        for q in queries[:4]:
            url = f"https://duoclaboral.cl/trabajo/trabajos-en-chile?Search[q]={requests.utils.quote(q)}&Search[jobOfferType]=0"
            driver.get(url)
            _time.sleep(3)
            soup = BeautifulSoup(driver.page_source, "lxml")
            for card in soup.select("div[class*='job'], article[class*='job'], li[class*='job']"):
                title_el   = card.select_one("h2, h3, [class*='title']")
                company_el = card.select_one("[class*='company'], [class*='empresa']")
                link_el    = card.select_one("a[href]")
                title   = title_el.get_text(strip=True)   if title_el   else ""
                company = company_el.get_text(strip=True) if company_el else ""
                href    = link_el.get("href", "")         if link_el    else ""
                if href and not href.startswith("http"):
                    href = "https://duoclaboral.cl" + href
                if title and href:
                    jid = _make_id(href, title)
                    if jid not in seen:
                        seen.add(jid)
                        jobs.append({
                            "id": jid, "title": title, "company": company,
                            "location": "Chile", "url": href,
                            "description": f"{title} {company}",
                            "published_at": None, "source": "Duoc Laboral",
                        })
            _time.sleep(2)
    except Exception as e:
        logger.warning(f"Duoc Laboral Selenium error: {e}")
    finally:
        if driver:
            driver.quit()
    return jobs


# ─────────────────────────────────────────────
# GOOGLE JOBS via Serper.dev (2,500 búsquedas gratis/mes)
# Reemplaza SerpApi — registra en serper.dev, gratis sin tarjeta
# Secret en GitHub: SERPER_API_KEY
# ─────────────────────────────────────────────
def scrape_google_jobs(queries, api_key):
    """
    Usa Serper.dev en vez de SerpApi.
    2,500 búsquedas gratis/mes vs 100 de SerpApi.
    Con cron horario y 2 queries por run = ~1,440/mes → entra en free tier.
    """
    jobs, seen = [], set()
    # Limitado a 2 queries por run para no exceder free tier con cron horario
    for q in queries[:2]:
        try:
            resp = requests.post(
                "https://google.serper.dev/search",
                headers={
                    "X-API-KEY": api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "q": f"{q} Chile site:linkedin.com OR site:getonbrd.com OR site:computrabajo.com",
                    "gl": "cl",
                    "hl": "es",
                    "num": 10,
                    "tbs": "qdr:w",  # últimos 7 días
                },
                timeout=15,
            )
            resp.raise_for_status()
            for item in resp.json().get("organic", []):
                title   = item.get("title", "")
                href    = item.get("link", "")
                snippet = item.get("snippet", "")
                # Limpiar título de sufijos de portales
                title = re.sub(r'\s*[–\-|]\s*(LinkedIn|Computrabajo|Get on Board).*$', '', title).strip()
                if title and href:
                    jid = _make_id(href, title)
                    if jid not in seen:
                        seen.add(jid)
                        jobs.append({
                            "id": jid, "title": title, "company": "",
                            "location": "Chile", "url": href,
                            "description": f"{title} {snippet}",
                            "published_at": None, "source": "Google Jobs",
                        })
        except Exception as e:
            logger.warning(f"Serper error '{q}': {e}")
        time.sleep(1)
    logger.info(f"Google Jobs (Serper): {len(jobs)} encontradas")
    return jobs


# ─────────────────────────────────────────────
# SerpApi legacy — mantenido por compatibilidad
# NO usar si tienes SERPER_API_KEY, consume créditos rápido
# ─────────────────────────────────────────────
def scrape_google_jobs_serpapi(queries, api_key):
    jobs, seen = [], set()
    for q in queries[:2]:  # máximo 2 para no quemar los 100 gratis
        try:
            resp = SESSION.get("https://serpapi.com/search", params={
                "engine":  "google_jobs",
                "q":       f"{q} Chile",
                "hl":      "es",
                "gl":      "cl",
                "api_key": api_key,
                "no_cache": "false",  # usar cache cuando sea posible (gratis)
            }, timeout=15)
            resp.raise_for_status()
            for item in resp.json().get("jobs_results", []):
                title    = item.get("title", "")
                company  = item.get("company_name", "")
                location = item.get("location", "Chile")
                href     = item.get("share_link", "")
                if not href:
                    links = item.get("related_links", [])
                    href  = links[0].get("link", "") if links else ""
                desc = item.get("description", "")
                if title and href:
                    jid = _make_id(href, title)
                    if jid not in seen:
                        seen.add(jid)
                        jobs.append({
                            "id": jid, "title": title, "company": company,
                            "location": location, "url": href,
                            "description": desc, "published_at": None,
                            "source": "Google Jobs",
                        })
        except Exception as e:
            logger.warning(f"SerpApi error '{q}': {e}")
        time.sleep(1)
    return jobs