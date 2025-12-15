from pathlib import Path
import argparse
import re
import sys
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
    "waterbank.az.gov": "https://waterbank.az.gov/",
    "www.avondaleaz.gov": "https://www.avondaleaz.gov/",
    "avondaleaz.gov": "https://www.avondaleaz.gov/",
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


def prewarm_cookies(url: str) -> None:
    """Fetch site root to set cookies for some domains that gate PDFs."""
    try:
        parsed = urlparse(url)
        root = f"{parsed.scheme}://{parsed.netloc}/"
        headers = {}
        ref = referer_for(url)
        if ref:
            headers["Referer"] = ref
        session.get(root, timeout=30, headers=headers)
    except Exception:
        pass


def get_with_headers(url: str, *, retry_403: bool = True) -> requests.Response:
    headers = {}
    ref = referer_for(url)
    if ref:
        headers["Referer"] = ref
    try:
        resp = session.get(url, stream=True, timeout=45, headers=headers)
        resp.raise_for_status()
    except requests.HTTPError as e:
        # Retry once on 403 with alternate headers and after cookie prewarm
        if retry_403 and getattr(e.response, "status_code", None) == 403:
            prewarm_cookies(url)
            alt_headers = {
                **headers,
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/120.0.0.0 Safari/537.36",
                "Accept": "*/*",
                "Upgrade-Insecure-Requests": "1",
            }
            time.sleep(1)
            resp = session.get(url, stream=True, timeout=45, headers=alt_headers)
            resp.raise_for_status()
        else:
            raise
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


def looks_like_pdf(url: str, resp: requests.Response) -> bool:
    """Decide if the response should be treated as a PDF even if content-type lies."""
    ctype = (resp.headers.get("content-type") or "").lower()
    if "pdf" in ctype:
        return True
    # Content-Disposition filename
    cd = resp.headers.get("content-disposition", "")
    if re.search(r'filename\s*=\s*"?[^"]+\.pdf"?', cd, flags=re.IGNORECASE):
        return True
    # URL ends with .pdf
    if url.lower().split("?")[0].endswith(".pdf"):
        return True
    return False


def main():
    parser = argparse.ArgumentParser(
        description="Download PDFs from knowledge_sources.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python download_pdfs.py                    # Download only missing PDFs
  python download_pdfs.py --force            # Re-download all PDFs
  python download_pdfs.py --verbose           # Show detailed progress
  python download_pdfs.py --force --verbose   # Re-download with verbose output
        """
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Force re-download of existing files"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show verbose output for each file"
    )
    parser.add_argument(
        "--output-dir", "-o",
        type=str,
        default="application/newData",
        help="Output directory for downloaded PDFs (default: application/newData)"
    )
    parser.add_argument(
        "--save-skipped",
        type=str,
        metavar="FILE",
        help="Save skipped entries to a file (CSV format)"
    )
    
    args = parser.parse_args()
    
    # Update target directory if specified
    global TARGET_DIR
    TARGET_DIR = Path(args.output_dir)
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    
    success = 0
    skipped = []
    already_exists = 0
    
    total = len(knowledge_sources)
    print(f"Found {total} entries in knowledge_sources.py")
    print(f"Target directory: {TARGET_DIR.absolute()}")
    if args.force:
        print("⚠️  Force mode enabled - will re-download existing files")
    print()
    
    for original_name, meta in tqdm(knowledge_sources.items(), desc="Downloading", unit="file"):
        url = meta.get("url", "").strip()
        if not url:
            skipped.append((original_name, "missing URL"))
            if args.verbose:
                tqdm.write(f"⚠️  Skipped {original_name}: missing URL")
            continue

        url = normalize_url(url)
        outfile = TARGET_DIR / normalize_filename(original_name)

        if outfile.exists() and not args.force:
            already_exists += 1
            if args.verbose:
                tqdm.write(f"✓  Already exists: {original_name}")
            continue

        if args.verbose:
            tqdm.write(f"📥 Downloading: {original_name}")

        try:
            # Initial request with session + optional referer
            resp = get_with_headers(url)
            content_type = (resp.headers.get("content-type") or "").lower()

            # If HTML, try to discover a direct PDF link within the page
            if "pdf" not in content_type and "html" in content_type:
                if args.verbose:
                    tqdm.write(f"  → Found HTML page, searching for PDF link...")
                # prewarm cookies on the page itself to allow embedded pdf links
                prewarm_cookies(url)
                pdf_url = find_pdf_in_html(url, resp.content)
                if pdf_url:
                    if args.verbose:
                        tqdm.write(f"  → Found PDF link: {pdf_url}")
                    try:
                        resp.close()
                    except Exception:
                        pass
                    resp = get_with_headers(pdf_url)
                    content_type = (resp.headers.get("content-type") or "").lower()
                    url = pdf_url  # for referer/debug if needed
                else:
                    if args.verbose:
                        tqdm.write(f"  ⚠️  No PDF link found in HTML")

            if not looks_like_pdf(url, resp):
                reason = f"non-PDF content-type ({content_type or 'unknown'})"
                skipped.append((original_name, reason))
                if args.verbose:
                    tqdm.write(f"  ❌ Skipped: {reason}")
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
            if args.verbose:
                file_size = outfile.stat().st_size
                tqdm.write(f"  ✓  Downloaded: {original_name} ({file_size:,} bytes)")
            try:
                resp.close()
            except Exception:
                pass
        except Exception as exc:
            reason = str(exc)
            skipped.append((original_name, reason))
            if args.verbose:
                tqdm.write(f"  ❌ Error: {reason}")
            time.sleep(1)

    # Print summary
    print(f"\n{'='*60}")
    print(f"Download Summary")
    print(f"{'='*60}")
    print(f"Total entries:     {total}")
    print(f"Downloaded:        {success}")
    print(f"Already existed:   {already_exists}")
    print(f"Skipped:           {len(skipped)}")
    print(f"Target directory:  {TARGET_DIR.absolute()}")
    print(f"{'='*60}")
    
    if skipped:
        print(f"\nSkipped entries ({len(skipped)}):")
        for name, reason in skipped[:20]:
            print(f"  - {name}: {reason}")
        if len(skipped) > 20:
            print(f"  (+ {len(skipped) - 20} more)")
        
        # Save skipped entries to file if requested
        if args.save_skipped:
            skipped_file = Path(args.save_skipped)
            with open(skipped_file, "w") as f:
                f.write("filename,reason\n")
                for name, reason in skipped:
                    # Escape commas and quotes in CSV
                    reason_escaped = reason.replace('"', '""')
                    f.write(f'"{name}","{reason_escaped}"\n')
            print(f"\nSkipped entries saved to: {skipped_file.absolute()}")
    
    # Exit with error code if there were failures
    if skipped and not args.force:
        print(f"\n⚠️  Some files were skipped. Use --force to retry or --verbose for details.")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
