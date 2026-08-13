import json
import re
import hashlib
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

RIYADH_TZ = timezone(timedelta(hours=3))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
}

TIMEOUT = 30

ROLE_TERMS = [
    "project director",
    "programme director",
    "program director",
    "senior project manager",
    "roads project manager",
    "road project manager",
    "highways project manager",
    "infrastructure project manager",
    "infrastructure manager",
    "construction director",
    "construction manager",
    "senior construction manager",
    "engineering manager",
    "engineering director",
    "resident engineer",
    "contracts manager",
    "contract manager",
    "commercial director",
    "technical manager",
    "technical director",
    "project manager",
]

DOMAIN_TERMS = [
    "road",
    "roads",
    "highway",
    "highways",
    "infrastructure",
    "bridge",
    "bridges",
    "transportation",
    "transport",
    "civil",
    "utilities",
    "utility",
    "tunnel",
    "tunnels",
    "construction",
    "pmc",
    "pmcm",
    "fidic",
    "site supervision",
    "construction supervision",
]

EXCLUDE_TERMS = [
    "saudi national",
    "saudi nationals",
    "ksa national",
    "ksa nationals",
    "saudi citizen",
    "saudi citizens",
    "saudi only",
    "saudis only",
    "for saudis only",
    "national only",
    "saudization",
    "saudisation",
    "tamheer",
    "fresh graduate",
    "graduate program",
    "graduate programme",
    "internship",
]

SAUDI_MARKERS = [
    "saudi arabia",
    "kingdom of saudi arabia",
    "ksa",
    "riyadh",
    "jeddah",
    "alula",
    "al ula",
    "dammam",
    "khobar",
    "al khobar",
    "tabuk",
    "qiddiya",
    "neom",
    "mecca",
    "makkah",
    "medina",
    "madinah",
    "yanbu",
    "jubail",
    "al qasim",
    "qassim",
]

CITY_MAP = {
    "riyadh": "الرياض",
    "jeddah": "جدة",
    "alula": "العلا",
    "al ula": "العلا",
    "dammam": "الدمام",
    "al khobar": "الخبر",
    "khobar": "الخبر",
    "tabuk": "تبوك",
    "qiddiya": "القدية",
    "neom": "نيوم",
    "mecca": "مكة",
    "makkah": "مكة",
    "medina": "المدينة المنورة",
    "madinah": "المدينة المنورة",
    "yanbu": "ينبع",
    "jubail": "الجبيل",
    "al qasim": "القصيم",
    "qassim": "القصيم",
}

SOURCES = [
    {
        "company": "Parsons",
        "seed_urls": [
            f"https://jobs.parsons.com/career-search?4525ccb0_page={i}&95f3e8b6_page={i}"
            for i in range(1, 15)
        ],
        "path_hints": ["/jobs/"],
        "allowed_hosts": ["jobs.parsons.com"],
    },

    {
        "company": "AtkinsRéalis",
        "seed_urls": [
            "https://careers.atkinsrealis.com/en/jobs"
        ] + [
            f"https://careers.atkinsrealis.com/en/jobs?page={i}"
            for i in range(2, 15)
        ],
        "path_hints": ["/en/jobs/"],
        "allowed_hosts": ["careers.atkinsrealis.com"],
    },

    {
        "company": "WSP",
        "seed_urls": [
            "https://www.wsp.com/en-me/careers/job-opportunities?country=SA",
            "https://www.wsp.com/en-me/careers/join-our-team?country=SA",
            "https://www.wsp.com/en-me/careers/job-opportunities?country=SA&query=project%20manager",
            "https://www.wsp.com/en-me/careers/job-opportunities?country=SA&query=infrastructure",
            "https://www.wsp.com/en-me/careers/job-opportunities?country=SA&query=roads",
        ],
        "path_hints": [
            "/careers/",
            "/job-opportunities/",
            "/join-our-team/",
        ],
        "allowed_hosts": ["www.wsp.com", "wsp.com"],
    },

    {
        "company": "Egis",
        "seed_urls": [
            "https://jobs.egis-group.com/",
            "https://jobs.egis-group.com/egis-middle-east",
        ],
        "path_hints": ["/job/"],
        "allowed_hosts": ["jobs.egis-group.com"],
    },

    {
        "company": "Jacobs",
        "seed_urls": [
            "https://careers.jacobs.com/en_US/careers",
            "https://careers.jacobs.com/en_US/careers/SearchJobs/"
        ],
        "path_hints": [
            "/careers/JobDetail/",
            "/careers/JobDetail?"
        ],
        "allowed_hosts": ["careers.jacobs.com"],
    },

    {
        "company": "AECOM",
        "seed_urls": [
            "https://aecom.jobs/search/?q=project+manager&locationsearch=Saudi+Arabia",
            "https://aecom.jobs/search/?q=infrastructure&locationsearch=Saudi+Arabia",
            "https://aecom.jobs/search/?q=roads&locationsearch=Saudi+Arabia",
            "https://aecom.jobs/search/?q=construction+manager&locationsearch=Saudi+Arabia",
            "https://aecom.jobs/search/?q=resident+engineer&locationsearch=Saudi+Arabia",
        ],
        "path_hints": ["/job/"],
        "allowed_hosts": ["aecom.jobs"],
    },
]

session = requests.Session()
session.headers.update(HEADERS)


def get(url):
    r = session.get(
        url,
        timeout=TIMEOUT,
        allow_redirects=True
    )
    r.raise_for_status()
    return r.text, r.url


def clean_text(html):
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup([
        "script",
        "style",
        "noscript",
        "svg",
    ]):
        tag.decompose()

    return " ".join(soup.stripped_strings)


def title_from_html(html):
    soup = BeautifulSoup(html, "html.parser")

    # JobPosting structured data
    for script in soup.find_all(
        "script",
        attrs={"type": "application/ld+json"}
    ):
        try:
            data = json.loads(script.string or "")

            items = data if isinstance(data, list) else [data]

            for item in items:
                if (
                    isinstance(item, dict)
                    and item.get("@type") == "JobPosting"
                    and item.get("title")
                ):
                    return str(item["title"]).strip()

        except Exception:
            pass

    h1 = soup.find("h1")

    if h1:
        value = " ".join(h1.stripped_strings).strip()

        if value:
            return value

    meta = soup.find(
        "meta",
        attrs={"property": "og:title"}
    )

    if meta and meta.get("content"):
        return meta["content"].strip()

    if soup.title:
        title = soup.title.get_text(
            " ",
            strip=True
        )

        for separator in ["|", "–", " - "]:
            if separator in title:
                title = title.split(separator)[0]

        return title.strip()

    return ""


def normalized_url(url):
    url = url.split("#")[0]
    url = url.split("?utm_")[0]
    return url.rstrip("/")


def valid_host(url, hosts):
    host = urlparse(url).netloc.lower()

    return any(
        host == h
        or host.endswith("." + h)
        for h in hosts
    )


def discover(seed, path_hints, allowed_hosts):
    html, final_url = get(seed)

    soup = BeautifulSoup(html, "html.parser")

    found = set()

    for a in soup.find_all("a", href=True):

        href = urljoin(
            final_url,
            a["href"]
        )

        href = normalized_url(href)

        if not href.startswith("http"):
            continue

        if not valid_host(
            href,
            allowed_hosts
        ):
            continue

        if any(
            hint in href
            for hint in path_hints
        ):
            found.add(href)

    return found


def is_closed(text):
    low = text.lower()

    closed_terms = [
        "no longer accepting applications",
        "job is no longer available",
        "position has been filled",
        "vacancy has been filled",
        "job has expired",
        "this position is closed",
        "applications are closed",
    ]

    return any(
        x in low
        for x in closed_terms
    )


def has_saudi_only(text):
    low = text.lower()

    return any(
        x in low
        for x in EXCLUDE_TERMS
    )


def is_relevant(title, text):
    blob = f"{title} {text}".lower()

    if has_saudi_only(blob):
        return False

    if is_closed(blob):
        return False

    if not any(
        x in blob
        for x in SAUDI_MARKERS
    ):
        return False

    title_l = title.lower()

    role_hit = any(
    x in title_l or x in blob
    for x in ROLE_TERMS
)

    domain_hit = any(
        x in blob
        for x in DOMAIN_TERMS
    )

    return role_hit and domain_hit


def score(title, text):
    t = title.lower()
    blob = f"{title} {text}".lower()

    s = 50

    if (
        "project director" in t
        or "programme director" in t
        or "program director" in t
    ):
        s += 31

    elif "senior project manager" in t:
        s += 28

    elif "technical director" in t:
        s += 27

    elif "construction director" in t:
        s += 26

    elif "resident engineer" in t:
        s += 24

    elif "technical manager" in t:
        s += 23

    elif "senior construction manager" in t:
        s += 23

    elif "construction manager" in t:
        s += 21

    elif "engineering manager" in t:
        s += 21

    elif "contracts manager" in t:
        s += 20

    elif "commercial director" in t:
        s += 19

    elif "project manager" in t:
        s += 19

    if any(
        x in blob
        for x in [
            "road",
            "roads",
            "highway",
            "highways",
        ]
    ):
        s += 11

    if "infrastructure" in blob:
        s += 7

    if any(
        x in blob
        for x in [
            "bridge",
            "bridges",
        ]
    ):
        s += 4

    if any(
        x in blob
        for x in [
            "pmc",
            "pmcm",
            "construction supervision",
            "site supervision",
        ]
    ):
        s += 3

    if "fidic" in blob:
        s += 2

    if re.search(
        r"\b(25|30)\+?\s*(?:years|yrs)",
        blob
    ):
        s += 5

    elif re.search(
        r"\b(20|21|22|23|24)\+?\s*(?:years|yrs)",
        blob
    ):
        s += 4

    elif re.search(
        r"\b1[5-9]\+?\s*(?:years|yrs)",
        blob
    ):
        s += 2

    return max(
        50,
        min(99, s)
    )


def city_of(text):
    low = text.lower()

    # longest terms first
    for key in sorted(
        CITY_MAP,
        key=len,
        reverse=True
    ):
        if key in low:
            return CITY_MAP[key]

    return "السعودية"


def eligibility_of(text):
    low = text.lower()

    if has_saudi_only(low):
        return "سعوديين فقط"

    positive_terms = [
        "relocation",
        "international candidates",
        "international applicants",
        "expatriate",
        "expat",
        "visa",
        "transferable iqama",
    ]

    if any(
        x in low
        for x in positive_terms
    ):
        return "متاحة/مرجحة لغير السعوديين"

    return "لا يظهر شرط الجنسية السعودية"


def reason_of(title, text):
    bits = []

    low = (
        title + " " + text
    ).lower()

    if any(
        x in low
        for x in [
            "road",
            "roads",
            "highway",
            "highways",
        ]
    ):
        bits.append(
            "الطرق والطرق السريعة"
        )

    if "infrastructure" in low:
        bits.append(
            "البنية التحتية"
        )

    if any(
        x in low
        for x in [
            "bridge",
            "bridges",
        ]
    ):
        bits.append(
            "الجسور"
        )

    if any(
        x in low
        for x in [
            "construction supervision",
            "site supervision",
            "pmc",
            "pmcm",
        ]
    ):
        bits.append(
            "إدارة والإشراف على التنفيذ"
        )

    if "fidic" in low:
        bits.append(
            "عقود FIDIC"
        )

    if any(
        x in title.lower()
        for x in [
            "director",
            "senior",
        ]
    ):
        bits.append(
            "مستوى قيادي متقدم"
        )

    if not bits:
        bits.append(
            "إدارة المشاريع الهندسية"
        )

    return (
        "تطابق قوي مع الخبرة في "
        + "، ".join(bits[:4])
        + "."
    )


def stable_id(company, url):
    key = company + "|" + normalized_url(url)

    return (
        company.lower()
        .replace(" ", "-")
        + "-"
        + hashlib.sha1(
            key.encode("utf-8")
        ).hexdigest()[:12]
    )


def load_existing():
    try:
        with open(
            "jobs.json",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

            result = {}

            for j in data.get(
                "jobs",
                []
            ):
                url = j.get("url")

                if url:
                    result[
                        normalized_url(url)
                    ] = j

            return result

    except Exception:
        return {}


def verify_previous_job(job):
    url = job.get("url")

    if not url:
        return False

    try:
        html, _ = get(url)

        text = clean_text(html)

        if is_closed(text):
            return False

        if has_saudi_only(text):
            return False

        return True

    except Exception:
        # Keep it if verification temporarily fails.
        return True


def main():

    existing = load_existing()

    discovered = []

    errors = []

    source_stats = {}

    for src in SOURCES:

        seen = set()

        source_stats[
            src["company"]
        ] = {
            "discovered": 0,
            "errors": 0,
        }

        for seed in src["seed_urls"]:

            try:

                links = discover(
                    seed,
                    src["path_hints"],
                    src["allowed_hosts"],
                )

                for url in links:

                    if url not in seen:

                        seen.add(url)

                        discovered.append(
                            (
                                src["company"],
                                url
                            )
                        )

                source_stats[
                    src["company"]
                ]["discovered"] = len(seen)

            except Exception as e:

                source_stats[
                    src["company"]
                ]["errors"] += 1

                errors.append(
                    f"discover {src['company']} {seed}: {e}"
                )

            time.sleep(0.25)

    jobs = []

    checked = set()

    found_urls = set()

    for company, url in discovered:

        url_key = normalized_url(url)

        if url_key in checked:
            continue

        checked.add(url_key)

        try:

            html, final_url = get(url)

            final_key = normalized_url(
                final_url
            )

            title = title_from_html(html)

            text = clean_text(html)

            if not title:
                continue

            if not is_relevant(
                title,
                text
            ):
                continue

            old = (
                existing.get(final_key)
                or existing.get(url_key)
                or {}
            )

            job = {
                "id": (
                    old.get("id")
                    or stable_id(
                        company,
                        final_url
                    )
                ),

                "company": company,

                "title": title,

                "city": city_of(text),

                "match": score(
                    title,
                    text
                ),

                "eligibility": eligibility_of(
                    text
                ),

                "status": old.get(
                    "status",
                    "جديدة"
                ),

                "date": old.get(
                    "date"
                ) or datetime.now(
                    RIYADH_TZ
                ).date().isoformat(),

                "url": normalized_url(
                    final_url
                ),

                "reason": reason_of(
                    title,
                    text
                ),

                "notes": old.get(
                    "notes",
                    ""
                ),

                "source": (
                    f"{company} Careers"
                ),
            }

            jobs.append(job)

            found_urls.add(
                normalized_url(
                    final_url
                )
            )

        except Exception as e:

            errors.append(
                f"job {company} {url}: {e}"
            )

        time.sleep(0.18)

    # Preserve existing jobs that were not rediscovered today,
    # unless their pages clearly say they are closed.
    for old_url, old_job in existing.items():

        if old_url in found_urls:
            continue

        if old_job.get(
            "status"
        ) in [
            "تم التقديم",
            "مقابلة",
            "عرض وظيفي",
        ]:
            jobs.append(old_job)
            continue

        if verify_previous_job(
            old_job
        ):
            jobs.append(old_job)

    # Deduplicate by normalized URL.
    unique = {}

    for job in jobs:

        key = normalized_url(
            job.get(
                "url",
                ""
            )
        )

        if not key:
            continue

        if (
            key not in unique
            or job.get(
                "match",
                0
            )
            > unique[key].get(
                "match",
                0
            )
        ):
            unique[key] = job

    jobs = list(
        unique.values()
    )

    # Keep only strong matches.
    jobs = [
        j
        for j in jobs
        if j.get(
            "match",
            0
        ) >= 78
    ]

    jobs = sorted(
        jobs,
        key=lambda j: (
            j.get(
                "match",
                0
            ),
            j.get(
                "date",
                ""
            ),
        ),
        reverse=True,
    )[:200]
    if not jobs and existing:
        jobs = list(existing.values())
        print("No new qualifying jobs found; preserving existing jobs.")
    payload = {
        "updated_at": datetime.now(
            RIYADH_TZ
        ).isoformat(
            timespec="seconds"
        ),

        "jobs": jobs,

        "meta": {
            "discovered": len(
                discovered
            ),

            "kept": len(
                jobs
            ),

            "sources": source_stats,

            "errors": errors[:30],
        },
    }

    with open(
        "jobs.json",
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            payload,
            f,
            ensure_ascii=False,
            indent=2,
        )

    print(
        f"Updated jobs.json: "
        f"{len(jobs)} jobs "
        f"from {len(discovered)} "
        f"discovered links"
    )

    print(
        json.dumps(
            source_stats,
            ensure_ascii=False,
            indent=2,
        )
    )

    if errors:

        print(
            "Warnings:"
        )

        for error in errors[:15]:
            print(
                "-",
                error
            )


if __name__ == "__main__":
    main()
