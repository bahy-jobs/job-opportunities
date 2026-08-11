import json, re, hashlib, time
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

RIYADH_TZ = timezone(timedelta(hours=3))
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; JobOpportunityDashboard/1.0)"}
TIMEOUT = 25

ROLE_TERMS = [
    "project director", "senior project manager", "roads project manager",
    "road project manager", "infrastructure manager", "construction manager",
    "engineering manager", "resident engineer", "contracts manager",
    "technical manager", "technical director", "project manager"
]
DOMAIN_TERMS = [
    "road", "roads", "highway", "highways", "infrastructure", "bridge", "bridges",
    "transportation", "transport", "civil", "utilities", "tunnel", "tunnels",
    "construction", "pmc", "fidic"
]
EXCLUDE_TERMS = [
    "saudi national", "saudi nationals", "ksa national", "saudi only",
    "for saudis only", "saudization", "tamheer", "fresh graduate", "graduate program"
]
SAUDI_MARKERS = ["saudi arabia", "riyadh", "jeddah", "alula", "al ula", "dammam", "khobar", "tabuk", "qiddiya", "neom", "mecca", "makkah", "medina", "madinah"]
CITY_MAP = {
    "riyadh":"الرياض", "jeddah":"جدة", "alula":"العلا", "al ula":"العلا",
    "dammam":"الدمام", "khobar":"الخبر", "tabuk":"تبوك", "qiddiya":"القدية",
    "neom":"نيوم", "mecca":"مكة", "makkah":"مكة", "medina":"المدينة", "madinah":"المدينة"
}

SOURCES = [
    {
        "company": "Parsons",
        "seed_urls": [f"https://jobs.parsons.com/career-search?4525ccb0_page={i}&95f3e8b6_page={i}" for i in range(1, 13)],
        "job_path": "/jobs/"
    },
    {
        "company": "AtkinsRéalis",
        "seed_urls": ["https://careers.atkinsrealis.com/en/jobs"] + [f"https://careers.atkinsrealis.com/en/jobs?page={i}" for i in range(2, 13)],
        "job_path": "/en/jobs/"
    },
    {
        "company": "AECOM",
        "seed_urls": [
            "https://aecom.jobs/search/?q=project+manager&locationsearch=Saudi+Arabia",
            "https://aecom.jobs/search/?q=infrastructure&locationsearch=Saudi+Arabia",
            "https://aecom.jobs/search/?q=construction+manager&locationsearch=Saudi+Arabia"
        ],
        "job_path": "/job/"
    }
]

session = requests.Session()
session.headers.update(HEADERS)

def get(url):
    r = session.get(url, timeout=TIMEOUT, allow_redirects=True)
    r.raise_for_status()
    return r.text, r.url

def clean_text(html):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return " ".join(soup.stripped_strings)

def title_from_html(html):
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    if h1:
        return " ".join(h1.stripped_strings)
    if soup.title:
        return soup.title.get_text(" ", strip=True).split("|")[0].strip()
    return ""

def discover(seed, path_hint):
    html, final_url = get(seed)
    soup = BeautifulSoup(html, "html.parser")
    found = set()
    for a in soup.find_all("a", href=True):
        href = urljoin(final_url, a["href"])
        if path_hint in href and href.startswith("http"):
            found.add(href.split("#")[0])
    return found

def is_relevant(title, text):
    blob = f"{title} {text}".lower()
    if any(x in blob for x in EXCLUDE_TERMS):
        return False
    if not any(x in blob for x in SAUDI_MARKERS):
        return False
    title_l = title.lower()
    role_hit = any(x in title_l for x in ROLE_TERMS)
    domain_hit = any(x in blob for x in DOMAIN_TERMS)
    return role_hit and domain_hit

def score(title, text):
    t = title.lower(); blob = (title + " " + text).lower()
    s = 55
    if "project director" in t: s += 28
    elif "senior project manager" in t: s += 25
    elif "resident engineer" in t: s += 23
    elif "technical director" in t: s += 24
    elif "technical manager" in t: s += 22
    elif "construction manager" in t: s += 20
    elif "engineering manager" in t: s += 19
    elif "contracts manager" in t: s += 18
    elif "project manager" in t: s += 18
    if any(x in blob for x in ["road", "roads", "highway", "highways"]): s += 10
    if "infrastructure" in blob: s += 6
    if "bridge" in blob or "bridges" in blob: s += 3
    if "fidic" in blob: s += 2
    if re.search(r"\b(20|25|30)\+?\s+years", blob): s += 4
    elif re.search(r"\b1[5-9]\+?\s+years", blob): s += 2
    return max(50, min(99, s))

def city_of(text):
    low = text.lower()
    for key, ar in CITY_MAP.items():
        if key in low:
            return ar
    return "السعودية"

def reason_of(title, text):
    bits=[]; low=(title+" "+text).lower()
    if any(x in low for x in ["road","roads","highway","highways"]): bits.append("طرق وطرق سريعة")
    if "infrastructure" in low: bits.append("بنية تحتية")
    if "bridge" in low: bits.append("جسور")
    if "construction" in low: bits.append("إدارة/تنفيذ إنشائي")
    if "fidic" in low: bits.append("عقود FIDIC")
    if "project director" in title.lower() or "senior" in title.lower(): bits.append("مستوى قيادي متقدم")
    if not bits: bits.append("إدارة مشاريع هندسية")
    return "تطابق قوي مع الخبرة في " + "، ".join(bits[:4]) + "."

def stable_id(company, url):
    return company.lower().replace(" ", "-") + "-" + hashlib.sha1(url.encode()).hexdigest()[:12]

def load_existing():
    try:
        with open("jobs.json", encoding="utf-8") as f:
            data=json.load(f)
            return {j.get("url"):j for j in data.get("jobs",[]) if j.get("url")}
    except Exception:
        return {}

def main():
    existing=load_existing()
    urls=[]
    errors=[]
    for src in SOURCES:
        seen=set()
        for seed in src["seed_urls"]:
            try:
                for u in discover(seed, src["job_path"]):
                    if u not in seen:
                        seen.add(u); urls.append((src["company"],u))
            except Exception as e:
                errors.append(f"discover {seed}: {e}")
            time.sleep(.2)

    jobs=[]; checked=set()
    for company,url in urls:
        if url in checked: continue
        checked.add(url)
        try:
            html, final_url=get(url)
            title=title_from_html(html)
            text=clean_text(html)
            if not is_relevant(title,text):
                continue
            old=existing.get(url,{})
            job={
                "id": old.get("id") or stable_id(company,url),
                "company": company,
                "title": title,
                "city": city_of(text),
                "match": score(title,text),
                "eligibility": "لا يظهر شرط الجنسية السعودية",
                "status": old.get("status","جديدة"),
                "date": old.get("date") or datetime.now(RIYADH_TZ).date().isoformat(),
                "url": final_url,
                "reason": reason_of(title,text),
                "notes": old.get("notes",""),
                "source": f"{company} Careers"
            }
            jobs.append(job)
        except Exception as e:
            errors.append(f"job {url}: {e}")
        time.sleep(.15)

    # If a source temporarily fails, keep previous qualifying jobs rather than returning an empty dashboard.
    if not jobs:
        jobs=list(existing.values())
    jobs=sorted(jobs,key=lambda j:(j.get("match",0),j.get("date","")),reverse=True)[:150]
    payload={
        "updated_at": datetime.now(RIYADH_TZ).isoformat(timespec="seconds"),
        "jobs": jobs,
        "meta": {"discovered": len(urls), "kept": len(jobs), "errors": errors[:20]}
    }
    with open("jobs.json","w",encoding="utf-8") as f:
        json.dump(payload,f,ensure_ascii=False,indent=2)
    print(f"Updated jobs.json: {len(jobs)} jobs from {len(urls)} discovered links")
    if errors:
        print("Warnings:")
        for e in errors[:10]: print("-",e)

if __name__ == "__main__":
    main()
