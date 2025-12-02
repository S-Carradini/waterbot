from pathlib import Path
import re
import time
from urllib.parse import urlparse, urlunparse, urljoin

import requests
from tqdm import tqdm

from application.mappings.knowledge_sources import knowledge_sources

TARGET_DIR = Path("application/newData")
TARGET_DIR.mkdir(parents=True, exist_ok=True)

# Create a single session with browser-like headers to reduce 403s
session = requests.Session()
session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "application/pdf,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
})

# Domains that often require a Referer
REFERERS = {
    "wateruseitwisely.com": "https://wateruseitwisely.com/",
    "www.calwater.com": "https://www.calwater.com/",
    "azdeq.gov": "https://azdeq.gov/",
    "globalfutures.asu.edu": "https://globalfutures.asu.edu/",
    "verderiver.org": "https://verderiver.org/",
    "azeconcenter.org": "https://azeconcenter.org/",
    "www.gao.gov": "https://www.gao.gov/",
    "nifa.usda.gov": "https://nifa.usda.gov/",
}


def normalize_filename(name: str) -> str:
    if not name.lower().endswith(".pdf"):
        name = f"{name}.pdf"
    return "".join(c if c not in {"\\", "/"} else "_" for c in name)


def normalize_url(raw_url: str) -> str:
    parsed = urlparse(raw_url.strip())
    if not parsed.scheme:
        parsed = parsed._replace(scheme="https")
    parsed = parsed._replace(path=parsed.path.replace(" ", "%20"))
    return urlunparse(parsed)


def referer_for(url: str) -> str | None:
    for domain, ref in REFERERS.items():
        if domain in url:
            return ref
    return None


def get_with_headers(url: str) -> requests.Response:
    headers = {}
    ref = referer_for(url)
    if ref:
        headers["Referer"] = ref
    resp = session.get(url, stream=True, timeout=45, headers=headers)
    resp.raise_for_status()
    return resp


def find_pdf_in_html(base_url: str, html_bytes: bytes) -> str | None:
    # Simple regex to find anchor tags with hrefs ending in .pdf
    try:
        html = html_bytes.decode("utf-8", errors="ignore")
    except Exception:
        return None
    # Look for .pdf links (case-insensitive)
    for match in re.finditer(r'href=["\']([^"\']+\.pdf(?:\?.*?)?)["\']', html, flags=re.IGNORECASE):
        href = match.group(1).strip()
        return normalize_url(urljoin(base_url, href))
    return None


success, skipped = 0, []

for original_name, meta in tqdm(knowledge_sources.items(), desc="Downloading", unit="file"):
    url = meta.get("url", "").strip()
    if not url:
        skipped.append((original_name, "missing URL"))
        continue

    url = normalize_url(url)
    outfile = TARGET_DIR / normalize_filename(original_name)

    if outfile.exists():
        continue

    try:
        # Initial request with session + optional referer
        resp = get_with_headers(url)
        content_type = resp.headers.get("content-type", "").lower()

        # If HTML, try to discover a direct PDF link within the page
        if "pdf" not in content_type and "html" in content_type:
            pdf_url = find_pdf_in_html(url, resp.content)
            if pdf_url:
                try:
                    resp.close()
                except Exception:
                    pass
                resp = get_with_headers(pdf_url)
                content_type = resp.headers.get("content-type", "").lower()
                url = pdf_url  # for referer/debug if needed

        if "pdf" not in content_type:
            skipped.append((original_name, f"non-PDF content-type ({content_type or 'unknown'})"))
            try:
                resp.close()
            except Exception:
                pass
            continue

        with open(outfile, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        success += 1
        try:
            resp.close()
        except Exception:
            pass
    except Exception as exc:
        skipped.append((original_name, str(exc)))
        time.sleep(1)

print(f"\nDownloaded {success} file(s) to {TARGET_DIR}")
if skipped:
    print("Skipped entries:")
    for name, reason in skipped[:20]:
        print(f"  - {name}: {reason}")
    if len(skipped) > 20:
        print(f"  (+ {len(skipped) - 20} more)")
