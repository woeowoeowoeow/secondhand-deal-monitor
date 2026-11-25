"""Small stdlib HTTP client with retries, backoff and Retry-After handling."""
from __future__ import annotations

import json
import logging
import random
import time
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger(__name__)

RETRY_STATUS = {429, 500, 502, 503, 504}


class HttpError(Exception):
    def __init__(self, status: int, body: str, url: str):
        super().__init__(f"HTTP {status} for {url.split('?')[0]}: {body[:200]}")
        self.status = status
        self.body = body


def request(method: str, url: str, *, headers: dict | None = None, params: dict | None = None,
            data: bytes | dict | None = None, timeout: float = 25, retries: int = 3,
            max_wait: float = 60) -> bytes:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    if isinstance(data, dict):
        data = urllib.parse.urlencode(data).encode()
    attempt = 0
    while True:
        req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            if e.code not in RETRY_STATUS or attempt >= retries:
                raise HttpError(e.code, body, url) from None
            ra = e.headers.get("Retry-After")
            wait = float(ra) if ra and ra.isdigit() else 2 ** attempt + random.random()
            if wait > max_wait:
                raise HttpError(e.code, f"rate limited, Retry-After={ra}", url) from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt >= retries:
                raise
            wait = 2 ** attempt + random.random()
            log.warning("network error %s; retrying", e)
        attempt += 1
        log.info("retry %d for %s in %.1fs", attempt, url.split("?")[0], wait)
        time.sleep(wait)


def get_json(url: str, **kw) -> dict:
    return json.loads(request("GET", url, **kw))


def post_json(url: str, payload: dict, headers: dict | None = None, **kw) -> dict:
    h = {"Content-Type": "application/json", **(headers or {})}
    body = request("POST", url, headers=h, data=json.dumps(payload).encode(), **kw)
    return json.loads(body) if body else {}
