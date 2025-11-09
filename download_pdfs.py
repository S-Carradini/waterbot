from pathlib import Path
import time
from urllib.parse import urlparse, urlunparse

import requests
from tqdm import tqdm

from application.mappings.knowledge_sources import knowledge_sources

TARGET_DIR = Path("application/newData")
TARGET_DIR.mkdir(parents=True, exist_ok=True)

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
        with requests.get(url, stream=True, timeout=45) as resp:
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "").lower()
            if "pdf" not in content_type:
                skipped.append((original_name, f"non-PDF content-type ({content_type or 'unknown'})"))
                continue
            with open(outfile, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
        success += 1
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
