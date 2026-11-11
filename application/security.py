"""
HTTP-level security helpers: signed session IDs, rate limits, admin login
lockout, admin password checks, and Content-Security-Policy values.
"""
import hashlib
import hmac
import os
import re
import secrets
import threading
import time
from collections import deque

import bcrypt

# ---------------------------------------------------------------------------
# Signed session identifiers
# ---------------------------------------------------------------------------
SESSION_SIG_COOKIE = "USER_SESSION_SIG"
_UUID4 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


class SessionSigner:
    """HMAC-signs server-issued session IDs so a browser cannot pick its own."""

    def __init__(self, secret: str):
        self._key = hashlib.sha256(("waterbot-session:" + secret).encode("utf-8")).digest()

    def sign(self, session_id: str) -> str:
        return hmac.new(self._key, session_id.encode("utf-8"), hashlib.sha256).hexdigest()

    def verify(self, session_id: str | None, signature: str | None) -> bool:
        if not session_id or not signature or not _UUID4.match(session_id):
            return False
        return hmac.compare_digest(self.sign(session_id), signature)


def is_riverbot_path(path: str) -> bool:
    """Riverbot pages, assets and APIs keep their original behaviour."""
    return path.startswith("/riverbot")


# ---------------------------------------------------------------------------
# Transcript download links: expiring and bound to the session that made them
# ---------------------------------------------------------------------------
TRANSCRIPT_LINK_SECONDS = 1800


class TranscriptLinkSigner:
    def __init__(self, secret: str):
        self._key = hashlib.sha256(("waterbot-transcript:" + secret).encode("utf-8")).digest()

    def _sign(self, key: str, session_id: str, expires: int) -> str:
        message = f"{key}\n{session_id}\n{expires}".encode("utf-8")
        return hmac.new(self._key, message, hashlib.sha256).hexdigest()

    def query(self, key: str, session_id: str, now: float | None = None) -> str:
        """Query string (expires, sig) for a download link valid for TRANSCRIPT_LINK_SECONDS."""
        expires = int((now if now is not None else time.time()) + TRANSCRIPT_LINK_SECONDS)
        return f"expires={expires}&sig={self._sign(key, session_id, expires)}"

    def verify(self, key: str, session_id: str | None, expires: str | None, sig: str | None,
               now: float | None = None) -> bool:
        if not session_id or not expires or not sig or not expires.isdigit():
            return False
        if int(expires) < (now if now is not None else time.time()):
            return False
        return hmac.compare_digest(self._sign(key, session_id, int(expires)), sig)


# ---------------------------------------------------------------------------
# Cross-site request check
# ---------------------------------------------------------------------------
DEFAULT_ALLOWED_ORIGINS = ["https://waterbot-production.up.railway.app"]
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def parse_origins(value: str | None) -> list[str]:
    """Comma-separated CORS_ALLOWED_ORIGINS, or the production default when unset."""
    origins = [o.strip().rstrip("/") for o in (value or "").split(",") if o.strip()]
    return origins or list(DEFAULT_ALLOWED_ORIGINS)


def is_cross_site_request(request, allowed_origins) -> bool:
    """True for a state-changing browser request sent by another website.

    Browsers always send Origin and/or Sec-Fetch-Site on POSTs and a web page
    cannot forge them. Requests with neither (scripts, curl, the export tool)
    are not browser cross-site requests and are allowed.
    """
    if request.method.upper() in _SAFE_METHODS:
        return False
    origin = (request.headers.get("origin") or "").rstrip("/")
    fetch_site = (request.headers.get("sec-fetch-site") or "").lower()
    if origin and origin in allowed_origins:
        return False
    if fetch_site in ("same-origin", "none"):
        return False
    if origin and origin != "null":
        origin_host = origin.split("://", 1)[-1]
        hosts = {request.headers.get("host", ""), request.headers.get("x-forwarded-host", "")}
        if origin_host in {h.split(",")[0].strip() for h in hosts if h}:
            return False
        return True
    # Origin "null" (sandboxed frames, file pages) or a browser that reported another site.
    return origin == "null" or fetch_site in ("cross-site", "same-site")


# ---------------------------------------------------------------------------
# Client address
# ---------------------------------------------------------------------------
TRUSTED_PROXY_HOPS = int(os.getenv("TRUSTED_PROXY_HOPS", "1"))


def client_ip(request) -> str:
    """Best-effort client IP behind Railway's proxy.

    The proxy appends the real client address to X-Forwarded-For, so the entry
    TRUSTED_PROXY_HOPS from the right is used; entries further left can be
    forged by the client and are ignored.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    hops = [h.strip() for h in forwarded.split(",") if h.strip()]
    if hops and TRUSTED_PROXY_HOPS > 0:
        return hops[-min(TRUSTED_PROXY_HOPS, len(hops))]
    return request.client.host if request.client else "unknown"


# ---------------------------------------------------------------------------
# Sliding-window rate limiter (per process)
# ---------------------------------------------------------------------------
class RateLimiter:
    def __init__(self, limit: int, window_seconds: float):
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()
        self._last_sweep = time.monotonic()

    def allow(self, key: str) -> bool:
        if self.limit <= 0:
            return True
        now = time.monotonic()
        with self._lock:
            if now - self._last_sweep > self.window:
                self._sweep(now)
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True

    def _sweep(self, now: float):
        for key in [k for k, h in self._hits.items() if not h or now - h[-1] > self.window]:
            del self._hits[key]
        self._last_sweep = now


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


# Requests that reach the AI service (chat, follow-up buttons, translate, text-to-speech).
SESSION_LIMITER = RateLimiter(_env_int("RATE_LIMIT_PER_SESSION", 30), 300)
IP_LIMITER = RateLimiter(_env_int("RATE_LIMIT_PER_IP", 120), 300)
GLOBAL_LIMITER = RateLimiter(_env_int("RATE_LIMIT_GLOBAL_PER_MINUTE", 600), 60)


def allow_ai_request(session_id: str, ip: str) -> bool:
    return (
        SESSION_LIMITER.allow("s:" + session_id)
        and IP_LIMITER.allow("i:" + ip)
        and GLOBAL_LIMITER.allow("global")
    )


# ---------------------------------------------------------------------------
# Admin login
# ---------------------------------------------------------------------------
class LoginThrottle:
    """Locks out an IP after repeated failures, plus a global cap against spraying."""

    def __init__(self, per_ip: int = 5, global_limit: int = 50, window_seconds: float = 900):
        self.per_ip = per_ip
        self.global_limit = global_limit
        self.window = window_seconds
        self._failures: dict[str, deque] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str, now: float) -> deque:
        hits = self._failures.setdefault(key, deque())
        while hits and now - hits[0] > self.window:
            hits.popleft()
        return hits

    def locked(self, ip: str) -> bool:
        now = time.monotonic()
        with self._lock:
            return (len(self._recent("ip:" + ip, now)) >= self.per_ip
                    or len(self._recent("global", now)) >= self.global_limit)

    def record_failure(self, ip: str):
        now = time.monotonic()
        with self._lock:
            self._recent("ip:" + ip, now).append(now)
            self._recent("global", now).append(now)

    def reset(self, ip: str):
        with self._lock:
            self._failures.pop("ip:" + ip, None)


LOGIN_THROTTLE = LoginThrottle()

# A real bcrypt hash of a random value, so failed lookups take the same time.
_DUMMY_HASH = bcrypt.hashpw(secrets.token_bytes(16), bcrypt.gensalt())


def admin_credentials_ok(username: str | None, password: str | None) -> bool:
    """Check admin credentials against ADMIN_USERNAME / ADMIN_PASSWORD_HASH (bcrypt).

    Admin access is disabled when either variable is missing.
    """
    expected_user = os.getenv("ADMIN_USERNAME", "")
    expected_hash = os.getenv("ADMIN_PASSWORD_HASH", "")
    supplied_user = (username or "").encode("utf-8")
    supplied_password = (password or "").encode("utf-8")[:72]  # bcrypt input limit
    try:
        hash_bytes = expected_hash.encode("utf-8") if expected_hash else _DUMMY_HASH
        password_ok = bcrypt.checkpw(supplied_password, hash_bytes)
    except ValueError:  # malformed hash in configuration
        bcrypt.checkpw(supplied_password, _DUMMY_HASH)
        password_ok = False
    user_ok = hmac.compare_digest(supplied_user, expected_user.encode("utf-8"))
    return bool(expected_user and expected_hash and user_ok and password_ok)


# ---------------------------------------------------------------------------
# Content-Security-Policy
# ---------------------------------------------------------------------------
CSP_MODE = os.getenv("CSP_MODE", "enforce").lower()  # enforce | report-only | off
# Which sites may show our pages in a frame. 'self' blocks clickjacking by other sites;
# set e.g. "'self' https://partner.example" if the chat is embedded elsewhere.
CSP_FRAME_ANCESTORS = os.getenv("CSP_FRAME_ANCESTORS", "'self'")

SPA_CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self' https://cdnjs.cloudflare.com",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdnjs.cloudflare.com",
    "font-src 'self' data: https://fonts.gstatic.com https://cdnjs.cloudflare.com",
    "img-src 'self' data: blob: https:",
    "media-src 'self' data: blob:",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    f"frame-ancestors {CSP_FRAME_ANCESTORS}",
])
# Admin pages use a small inline script and Bootstrap from jsDelivr; they never render bot output.
ADMIN_CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline'",
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
    "img-src 'self' data:",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])


def csp_header(path: str):
    """(header name, value) for an HTML response on `path`, or None."""
    if CSP_MODE == "off" or is_riverbot_path(path):
        return None
    name = "Content-Security-Policy-Report-Only" if CSP_MODE == "report-only" else "Content-Security-Policy"
    return name, ADMIN_CSP if path.startswith("/admin") else SPA_CSP


# Sent on every non-Riverbot response.
BASELINE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}

# ---------------------------------------------------------------------------
# Request size
# ---------------------------------------------------------------------------
# Largest legitimate body is a translate request (50,000 characters); 1 MB leaves room.
MAX_REQUEST_BYTES = _env_int("MAX_REQUEST_BYTES", 1_000_000)


def csv_safe(value):
    """Stop spreadsheet apps from running visitor text as a formula (CSV injection)."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value
