import json
import os
import shutil
import subprocess
import time
import urllib.request
from datetime import datetime
from playwright.sync_api import sync_playwright

URL = "https://www.linkedin.com/jobs/search/?currentJobId=4434495464&f_TPR=r86400&f_WT=2%2C3&keywords=Social%20Media%20Manager&location=Medell%C3%ADn%2C%20Antioquia%2C%20Colombia&origin=JOB_SEARCH_PAGE_JOB_FILTER&sortBy=DD"

CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CHROME_PROFILE = "/Users/dianagomez/Library/Application Support/Google/Chrome"
TMP_DIR = "/Users/dianagomez/.chrome_debug_profile"
DEBUG_PORT = 9222
SEEN_FILE = "/Users/dianagomez/.linkedin_seen_jobs.json"
INTERVAL_SECONDS = 180  # 3 minutos
EMAIL_TO = "dianagomezbo@gmail.com"


def chrome_debug_running():
    try:
        urllib.request.urlopen(f"http://localhost:{DEBUG_PORT}/json/version", timeout=2)
        return True
    except Exception:
        return False


def launch_chrome():
    if not os.path.exists(TMP_DIR):
        print("Copiando perfil de Chrome...")
        default_src = os.path.join(CHROME_PROFILE, "Default")
        default_dst = os.path.join(TMP_DIR, "Default")
        shutil.copytree(default_src, default_dst, ignore=shutil.ignore_patterns(
            "Cache", "Code Cache", "GPUCache", "Service Worker",
            "blob_storage", "IndexedDB", "*.log", "*.tmp"
        ))
        local_state = os.path.join(CHROME_PROFILE, "Local State")
        if os.path.exists(local_state):
            shutil.copy2(local_state, TMP_DIR)

    print("Lanzando Chrome con debug remoto...")
    subprocess.Popen([
        CHROME_PATH,
        f"--remote-debugging-port={DEBUG_PORT}",
        f"--user-data-dir={TMP_DIR}",
    ], stderr=subprocess.DEVNULL)
    time.sleep(4)


def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE) as f:
            return json.load(f)
    return []


def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(seen, f)


def send_email(new_jobs):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    jobs_html = ""
    for j in new_jobs:
        link = j["link"] if j["link"] else "#"
        jobs_html += f'<li><strong><a href="{link}">{j["title"]}</a></strong><br>Empresa: {j["company"]}<br>Ubicación: {j["location"]}</li>'

    body = f"""<html><body>
<h2>Nuevos trabajos encontrados - {now}</h2>
<p>Se encontraron <strong>{len(new_jobs)}</strong> nueva(s) oferta(s):</p>
<ol>{jobs_html}</ol>
<br><p>— LinkedIn Job Monitor</p>
</body></html>"""

    subject = f"LinkedIn: {len(new_jobs)} nuevo(s) trabajo(s) - Social Media Manager"

    body_escaped = body.replace('"', '\\"').replace("\n", "")

    applescript = f'''
    tell application "Mail"
        set newMessage to make new outgoing message with properties {{subject:"{subject}", content:"placeholder", visible:false}}
        tell newMessage
            set html content to "{body_escaped}"
            make new to recipient at end of to recipients with properties {{address:"{EMAIL_TO}"}}
            send
        end tell
    end tell
    '''

    try:
        subprocess.run(["osascript", "-e", applescript], check=True, capture_output=True)
        print(f"  Correo enviado a {EMAIL_TO}")
    except Exception as e:
        print(f"  Error enviando correo: {e}")


def extract_job(job):
    title_el = (
        job.query_selector("a.job-card-list__title--link strong") or
        job.query_selector("a.job-card-container__link strong") or
        job.query_selector("[class*='job-card'] strong") or
        job.query_selector("strong")
    )
    company_el = (
        job.query_selector(".artdeco-entity-lockup__subtitle span") or
        job.query_selector("[class*='subtitle'] span") or
        job.query_selector(".job-card-container__primary-description")
    )
    location_el = (
        job.query_selector(".artdeco-entity-lockup__caption span") or
        job.query_selector("[class*='caption'] span") or
        job.query_selector(".job-card-container__metadata-wrapper li")
    )
    link_el = (
        job.query_selector("a.job-card-list__title--link") or
        job.query_selector("a.job-card-container__link") or
        job.query_selector("a[href*='/jobs/view/']")
    )

    title = title_el.inner_text().strip() if title_el else "Sin título"
    company = company_el.inner_text().strip() if company_el else "Sin empresa"
    location = location_el.inner_text().strip() if location_el else "Sin ubicación"
    link = link_el.get_attribute("href") if link_el else ""
    if link and not link.startswith("http"):
        link = "https://www.linkedin.com" + link

    return {"title": title, "company": company, "location": location, "link": link}


def check_jobs():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if not chrome_debug_running():
        launch_chrome()

    print(f"\n[{now}] Revisando ofertas de LinkedIn...")

    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(f"http://localhost:{DEBUG_PORT}")
            context = browser.contexts[0]
            page = context.new_page()
            page.goto(URL, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(5000)

            jobs = page.query_selector_all("li.ember-view.occludable-update")
            if not jobs:
                jobs = page.query_selector_all("[data-occludable-job-id]")
            if not jobs:
                jobs = page.query_selector_all(".job-card-container")
            if not jobs:
                jobs = page.query_selector_all(".jobs-search-results__list-item")

            seen = load_seen()
            new_jobs = []

            for job in jobs:
                info = extract_job(job)
                job_id = info["link"].split("/jobs/view/")[1].split("/")[0] if "/jobs/view/" in info["link"] else info["title"]
                if job_id not in seen:
                    new_jobs.append(info)
                    seen.append(job_id)

            if new_jobs:
                print(f"\n  ** {len(new_jobs)} NUEVO(S) TRABAJO(S) ENCONTRADO(S) **\n")
                for i, j in enumerate(new_jobs, 1):
                    print(f"  {i}. {j['title']}")
                    print(f"     Empresa:   {j['company']}")
                    print(f"     Ubicación: {j['location']}")
                    if j["link"]:
                        print(f"     Link:      {j['link']}")
                    print()
                save_seen(seen)
                send_email(new_jobs)
            else:
                print("  Sin nuevas ofertas desde la última revisión.")

            page.close()
    except Exception as e:
        print(f"  Error: {e}")


# --- LOOP INFINITO ---
print("=" * 60)
print("  LinkedIn Job Monitor - Social Media Manager")
print(f"  Revisando cada {INTERVAL_SECONDS} segundos")
print(f"  Correos a: {EMAIL_TO}")
print("  Presiona Ctrl+C para detener")
print("=" * 60)

while True:
    check_jobs()
    time.sleep(INTERVAL_SECONDS)
