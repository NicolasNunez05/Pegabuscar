import hashlib, re, time, logging
from datetime import datetime, timezone, timedelta
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "es-CL,es;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
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
    text = text.lower().strip()
    patterns = [
        (r"(\d+)\s*(minuto|min)", "minutes"),
        (r"(\d+)\s*(hora|hour)", "hours"),
        (r"(\d+)\s*(día|dia|day)", "days"),
        (r"(\d+)\s*(semana|week)", "weeks"),
        (r"(\d+)\s*(mes|month)", "months"),
    ]
    for pattern, unit in patterns:
        m = re.search(pattern, text)
        if m:
            n = int(m.group(1))
            delta = {"minutes": timedelta(minutes=n), "hours": timedelta(hours=n),
                     "days": timedelta(days=n), "weeks": timedelta(weeks=n),
                     "months": timedelta(days=n*30)}[unit]
            return now - delta
    return None


def scrape_getonboard(queries):
    jobs, seen = [], set()
    for q in queries:
        url = f"https://www.getonbrd.com/api/v0/search/jobs?query={requests.utils.quote(q)}&per_page=20&page=0"
        try:
            data = SESSION.get(url, timeout=15).json()
            for item in data.get("data", []):
                a = item.get("attributes", {})
                title, company = a.get("title", ""), a.get("company_name", "")
                location = a.get("modality", "") + " " + a.get("country", "Chile")
                job_url = a.get("url", "")
                description = str(a.get("description", "") or a.get("functions", ""))[:2000]
                published_at = None
                raw = a.get("published_at", "")
                if raw:
                    try:
                        published_at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                    except Exception:
                        pass
                jid = _make_id(job_url, title)
                if jid not in seen:
                    seen.add(jid)
                    jobs.append({"id": jid, "title": title, "company": company,
                                 "location": location, "url": job_url,
                                 "description": description, "published_at": published_at,
                                 "source": "Get on Board"})
        except Exception as e:
            logger.warning(f"GetOnBoard error '{q}': {e}")
        time.sleep(1)
    return jobs


def _generic_scrape(queries, base_url_fn, base_domain, card_selector,
                    title_sel, company_sel, location_sel, link_sel, date_sel, source_name):
    jobs, seen = [], set()
    for q in queries[:6]:
        soup = _get(base_url_fn(q))
        if not soup:
            continue
        for card in soup.select(card_selector):
            def gt(sel):
                el = card.select_one(sel)
                return el.get_text(strip=True) if el else ""
            title = gt(title_sel)
            company = gt(company_sel)
            location = gt(location_sel) or "Chile"
            link_el = card.select_one(link_sel)
            href = link_el.get("href", "") if link_el else ""
            if href and not href.startswith("http"):
                href = base_domain + href
            date_text = gt(date_sel)
            published_at = _parse_relative_time(date_text)
            if title and href:
                jid = _make_id(href, title)
                if jid not in seen:
                    seen.add(jid)
                    jobs.append({"id": jid, "title": title, "company": company,
                                 "location": location, "url": href,
                                 "description": f"{title} {company} {location}",
                                 "published_at": published_at, "source": source_name})
        time.sleep(2)
    return jobs


def scrape_indeed(queries):
    jobs, seen = [], set()
    for q in queries[:8]:
        url = f"https://cl.indeed.com/jobs?q={requests.utils.quote(q)}&l=Chile&fromage=3&sort=date"
        soup = _get(url)
        if not soup:
            continue
        for card in soup.select("div.job_seen_beacon, div.jobsearch-SerpJobCard"):
            title_el = card.select_one("h2.jobTitle span, span[title]")
            company_el = card.select_one("span.companyName, span[data-testid='company-name']")
            location_el = card.select_one("div.companyLocation, span[data-testid='text-location']")
            link_el = card.select_one("a[data-jk], h2 a")
            date_el = card.select_one("span.date, span[data-testid='myJobsStateDate']")
            title = title_el.get_text(strip=True) if title_el else ""
            company = company_el.get_text(strip=True) if company_el else ""
            location = location_el.get_text(strip=True) if location_el else "Chile"
            href = link_el.get("href", "") if link_el else ""
            if href and not href.startswith("http"):
                href = "https://cl.indeed.com" + href
            published_at = _parse_relative_time(date_el.get_text(strip=True) if date_el else "")
            if title and href:
                jid = _make_id(href, title)
                if jid not in seen:
                    seen.add(jid)
                    jobs.append({"id": jid, "title": title, "company": company,
                                 "location": location, "url": href,
                                 "description": f"{title} {company} {location}",
                                 "published_at": published_at, "source": "Indeed"})
        time.sleep(2)
    return jobs


def scrape_laborum(queries):
    return _generic_scrape(
        queries,
        lambda q: f"https://www.laborum.cl/empleos/{requests.utils.quote(q.replace(' ','-'))}?publicationDate=3",
        "https://www.laborum.cl",
        "article.aviso, div[class*='JobCard'], li[class*='aviso']",
        "h2, h3, a[class*='title']",
        "[class*='company'], [class*='empresa']",
        "[class*='location'], [class*='ubicacion']",
        "a[href]",
        "[class*='date'], [class*='fecha'], time",
        "Laborum"
    )


def scrape_chiletrabajos(queries):
    return _generic_scrape(
        queries,
        lambda q: f"https://www.chiletrabajos.cl/empleo/buscar?q={requests.utils.quote(q)}&fecha=3",
        "https://www.chiletrabajos.cl",
        "div.aviso, div[class*='jobOffer'], article",
        "h2, h3, a.title, [class*='title']",
        "[class*='company'], [class*='empresa']",
        "[class*='location'], [class*='ciudad']",
        "a[href]",
        "time, [class*='date'], [class*='fecha']",
        "Chiletrabajos"
    )


def scrape_trabajoschile(queries):
    return _generic_scrape(
        queries,
        lambda q: f"https://www.trabajando.cl/trabajo/{requests.utils.quote(q.replace(' ','-'))}",
        "https://www.trabajando.cl",
        "div[class*='jobOffer'], article[class*='job'], div.job-item",
        "h2, h3, [class*='title']",
        "[class*='company'], [class*='empresa']",
        "[class*='location'], [class*='ciudad']",
        "a[href]",
        "time, [class*='date']",
        "TrabajosChile"
    )


def scrape_duoclaboral(queries, email, password):
    jobs, seen = [], set()
    s = requests.Session()
    s.headers.update(HEADERS)
    try:
        soup = BeautifulSoup(s.get("https://laboral.duoc.cl/login", timeout=15).text, "html.parser")
        csrf_input = soup.select_one("input[name='_token'], input[name='csrf_token']")
        csrf = csrf_input["value"] if csrf_input else ""
        r = s.post("https://laboral.duoc.cl/login",
                   data={"email": email, "password": password, "_token": csrf}, timeout=15)
        if r.status_code not in (200, 302):
            logger.warning(f"Duoc login failed: {r.status_code}")
            return []
        for q in queries[:4]:
            soup = _get(f"https://laboral.duoc.cl/empleos?q={requests.utils.quote(q)}")
            if not soup:
                continue
            for card in soup.select("div[class*='job'], article, div[class*='oferta']"):
                title_el = card.select_one("h2, h3, [class*='title']")
                company_el = card.select_one("[class*='company'], [class*='empresa']")
                link_el = card.select_one("a[href]")
                title = title_el.get_text(strip=True) if title_el else ""
                company = company_el.get_text(strip=True) if company_el else ""
                href = link_el.get("href", "") if link_el else ""
                if href and not href.startswith("http"):
                    href = "https://laboral.duoc.cl" + href
                if title and href:
                    jid = _make_id(href, title)
                    if jid not in seen:
                        seen.add(jid)
                        jobs.append({"id": jid, "title": title, "company": company,
                                     "location": "Chile", "url": href,
                                     "description": f"{title} {company}",
                                     "published_at": None, "source": "Duoc Laboral"})
            time.sleep(2)
    except Exception as e:
        logger.warning(f"Duoc Laboral error: {e}")
    return jobs


def scrape_google_jobs(queries):
    jobs, seen = [], set()
    s = requests.Session()
    s.headers.update({**HEADERS, "Accept-Encoding": "gzip, deflate"})
    for q in queries[:4]:
        search_q = f"{q} Chile site:linkedin.com OR site:getonbrd.com OR site:laborum.cl"
        url = f"https://www.google.com/search?q={requests.utils.quote(search_q)}&hl=es&gl=cl&num=10"
        try:
            soup = BeautifulSoup(s.get(url, timeout=15).text, "html.parser")
            for res in soup.select("div.g, div[class*='tF2Cxc']"):
                title_el = res.select_one("h3")
                link_el = res.select_one("a[href]")
                snippet_el = res.select_one("div[class*='VwiC3b']")
                title = title_el.get_text(strip=True) if title_el else ""
                href = link_el.get("href", "") if link_el else ""
                if href.startswith("/url?q="):
                    href = href.split("/url?q=")[1].split("&")[0]
                snippet = snippet_el.get_text(strip=True) if snippet_el else ""
                if title and href and "http" in href:
                    jid = _make_id(href, title)
                    if jid not in seen:
                        seen.add(jid)
                        jobs.append({"id": jid, "title": title, "company": "",
                                     "location": "Chile", "url": href,
                                     "description": snippet,
                                     "published_at": None, "source": "Google Jobs"})
        except Exception as e:
            logger.warning(f"Google Jobs error '{q}': {e}")
        time.sleep(3)
    return jobs