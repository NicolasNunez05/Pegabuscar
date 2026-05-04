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


def _parse_relative_time(text):
    now = datetime.now(timezone.utc)
    if not text:
        return None
    text = text.lower().strip()
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
        m = re.search(pattern, text)
        if m:
            if unit == "today":   return now
            if unit == "1day":    return now - timedelta(days=1)
            n = int(m.group(1))
            delta = {
                "minutes": timedelta(minutes=n),
                "hours":   timedelta(hours=n),
                "days":    timedelta(days=n),
                "weeks":   timedelta(weeks=n),
                "months":  timedelta(days=n*30),
            }[unit]
            return now - delta
    return None


# ─────────────────────────────────────────────
# GET ON BOARD (API JSON)
# ─────────────────────────────────────────────
def scrape_getonboard(queries):
    jobs, seen = [], set()
    for q in queries:
        url = f"https://www.getonbrd.com/api/v0/search/jobs?query={requests.utils.quote(q)}&per_page=20&page=0"
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
                title    = str(a.get("title", ""))
                company  = str(a.get("company_name", ""))
                modality = str(a.get("modality", ""))
                country  = str(a.get("country", "Chile"))
                location = f"{modality} {country}".strip()
                job_url  = str(a.get("url", ""))
                desc_raw = a.get("description") or a.get("functions") or ""
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
            logger.warning(f"GetOnBoard error '{q}': {e}")
        time.sleep(1)
    return jobs


# ─────────────────────────────────────────────
# INDEED CHILE
# URL patrón: cl.indeed.com/q-{query}-empleos.html
# ─────────────────────────────────────────────
def scrape_indeed(queries):
    jobs, seen = [], set()
    s = requests.Session()
    s.headers.update({
        **HEADERS,
        "Referer": "https://cl.indeed.com/",
        "Cache-Control": "no-cache",
    })
    for q in queries[:8]:
        slug = requests.utils.quote(q.replace(" ", "-"))
        url  = f"https://cl.indeed.com/q-{slug}-empleos.html"
        try:
            r = s.get(url, timeout=15)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            for card in soup.select("div.job_seen_beacon, li[class*='css-'], div[data-testid='slider_container']"):
                title_el   = card.select_one("h2.jobTitle span[title], h2.jobTitle span, span[title]")
                company_el = card.select_one("span[data-testid='company-name'], span.companyName")
                location_el= card.select_one("div[data-testid='text-location'], div.companyLocation")
                link_el    = card.select_one("a[data-jk], h2 a, a[id^='job_']")
                date_el    = card.select_one("span[data-testid='myJobsStateDate'], span.date")
                title   = title_el.get_text(strip=True)   if title_el    else ""
                company = company_el.get_text(strip=True) if company_el  else ""
                location= location_el.get_text(strip=True)if location_el else "Chile"
                href    = link_el.get("href", "")         if link_el     else ""
                if href and not href.startswith("http"):
                    href = "https://cl.indeed.com" + href
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
                            "published_at": published_at, "source": "Indeed",
                        })
        except Exception as e:
            logger.warning(f"Indeed error '{q}': {e}")
        time.sleep(3)
    return jobs


# ─────────────────────────────────────────────
# LABORUM
# URL patrón: laborum.cl/empleos-busqueda-{query}.html
# ─────────────────────────────────────────────
def scrape_laborum(queries):
    jobs, seen = [], set()
    for q in queries[:6]:
        slug = requests.utils.quote(q.replace(" ", "-"))
        url  = f"https://www.laborum.cl/empleos-busqueda-{slug}.html"
        soup = _get(url)
        if not soup:
            continue
        for card in soup.select("article[class*='aviso'], div[class*='JobCard'], li[class*='aviso'], div[class*='job-item']"):
            title_el   = card.select_one("h2, h3, a[class*='title'], [class*='jobTitle']")
            company_el = card.select_one("[class*='company'], [class*='empresa'], [class*='Company']")
            location_el= card.select_one("[class*='location'], [class*='ubicacion'], [class*='ciudad']")
            link_el    = card.select_one("a[href]")
            date_el    = card.select_one("time, [class*='date'], [class*='fecha'], [class*='time']")
            title   = title_el.get_text(strip=True)    if title_el    else ""
            company = company_el.get_text(strip=True)  if company_el  else ""
            location= location_el.get_text(strip=True) if location_el else "Chile"
            href    = link_el.get("href", "")          if link_el     else ""
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
    return jobs


# ─────────────────────────────────────────────
# CHILETRABAJOS
# URL patrón: chiletrabajos.cl/encuentra-un-empleo?action=search&2={query}
# ─────────────────────────────────────────────
def scrape_chiletrabajos(queries):
    jobs, seen = [], set()
    for q in queries[:6]:
        url  = f"https://www.chiletrabajos.cl/encuentra-un-empleo?action=search&order_by=&ord=&within=25&2={requests.utils.quote(q)}&filterSearch=Buscar"
        soup = _get(url)
        if not soup:
            continue
        for card in soup.select("div[class*='job'], article[class*='job'], div[class*='aviso'], li[class*='job']"):
            title_el   = card.select_one("h2, h3, a[class*='title'], [class*='jobTitle']")
            company_el = card.select_one("[class*='company'], [class*='empresa']")
            location_el= card.select_one("[class*='location'], [class*='ciudad'], [class*='ubicacion']")
            link_el    = card.select_one("a[href]")
            date_el    = card.select_one("time, [class*='date'], [class*='fecha']")
            title   = title_el.get_text(strip=True)    if title_el    else ""
            company = company_el.get_text(strip=True)  if company_el  else ""
            location= location_el.get_text(strip=True) if location_el else "Chile"
            href    = link_el.get("href", "")          if link_el     else ""
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
# COMPUTRABAJO
# URL patrón: cl.computrabajo.com/trabajo-de-{query}
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
            title_el   = card.select_one("h2 a, h3 a, a[class*='js-o-link'], [class*='title']")
            company_el = card.select_one("[class*='company'], p[class*='dbl']")
            location_el= card.select_one("[class*='location'], p[class*='fs16']")
            date_el    = card.select_one("p[class*='fc_base'] span, [class*='date'], time")
            title   = title_el.get_text(strip=True)    if title_el    else ""
            company = company_el.get_text(strip=True)  if company_el  else ""
            location= location_el.get_text(strip=True) if location_el else "Chile"
            href    = title_el.get("href", "")         if title_el    else ""
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
# DUOC LABORAL
# URL: duoclaboral.cl/trabajo/trabajos-en-chile
# ─────────────────────────────────────────────
def scrape_duoclaboral(queries):
    jobs, seen = [], set()
    base_url = "https://duoclaboral.cl/trabajo/trabajos-en-chile"
    soup = _get(base_url)
    if not soup:
        return jobs
    for card in soup.select("div[class*='job'], article[class*='job'], li[class*='job'], div[class*='offer']"):
        title_el   = card.select_one("h2, h3, a[class*='title'], [class*='jobTitle']")
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
    return jobs