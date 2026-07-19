from __future__ import annotations

import json
import re
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_fixed


class ProxyRequiredError(RuntimeError):
    pass


class CrawlClient:
    """源站爬取客户端：强制走代理（代理池/WARP），禁止直连。"""

    def __init__(
        self,
        proxy: str,
        proxy_label: str = "",
        user_agent: str = "",
        timeout: float = 30.0,
        flaresolverr_url: str = "http://127.0.0.1:8191",
        force_proxy: bool = True,
    ) -> None:
        if force_proxy and not proxy:
            raise ProxyRequiredError("force_proxy=True 但未配置代理")
        self.proxy = proxy
        self.proxy_label = proxy_label or "***"
        self.force_proxy = force_proxy
        self.flaresolverr_url = flaresolverr_url.rstrip("/")
        self.headers = {
            "User-Agent": user_agent
            or (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        self.timeout = timeout
        self._client = httpx.Client(
            proxy=proxy if force_proxy else None,
            headers=self.headers,
            timeout=timeout,
            follow_redirects=True,
            verify=True,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "CrawlClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def verify_exit(self) -> dict[str, Any]:
        """核验代理出口（只返回 IP/地区，不打印代理密码）。"""
        ip = ""
        try:
            r = self._client.get("https://api.ipify.org", timeout=20)
            ip = r.text.strip()
        except Exception as e:
            return {"ok": False, "error": str(e), "proxy": self.proxy_label}
        warp = ""
        loc = ""
        try:
            t = self._client.get("https://www.cloudflare.com/cdn-cgi/trace", timeout=15).text
            for line in t.splitlines():
                if line.startswith("warp="):
                    warp = line.split("=", 1)[1]
                if line.startswith("loc="):
                    loc = line.split("=", 1)[1]
                if line.startswith("ip=") and not ip:
                    ip = line.split("=", 1)[1]
        except Exception:
            pass
        return {
            "ok": bool(ip),
            "ip": ip,
            "loc": loc,
            "warp": warp or "n/a",
            "proxy": self.proxy_label,
        }

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(1), reraise=True)
    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self._client.get(url, **kwargs)

    def flaresolve(self, url: str, max_timeout: int = 60000) -> dict[str, Any]:
        payload = {"cmd": "request.get", "url": url, "maxTimeout": max_timeout}
        with httpx.Client(timeout=max_timeout / 1000 + 10) as local:
            r = local.post(f"{self.flaresolverr_url}/v1", json=payload)
            r.raise_for_status()
            data = r.json()
        if data.get("status") != "ok":
            raise RuntimeError(f"FlareSolverr failed: {data.get('message') or data}")
        return data.get("solution") or {}

    def fetch_smart(self, url: str) -> dict[str, Any]:
        used_fs = False
        error = ""
        status = 0
        content_type = ""
        text = ""
        try:
            resp = self.get(url)
            status = resp.status_code
            content_type = resp.headers.get("content-type", "")
            text = resp.text
            if status in (403, 503) or _looks_like_cf(text):
                sol = self.flaresolve(url)
                used_fs = True
                status = int(sol.get("status") or status)
                text = sol.get("response") or text
                content_type = "text/html"
        except Exception as e:
            error = str(e)
            try:
                sol = self.flaresolve(url)
                used_fs = True
                status = int(sol.get("status") or 0)
                text = sol.get("response") or ""
                content_type = "text/html"
                error = ""
            except Exception as e2:
                error = f"{error}; flaresolverr: {e2}"

        is_json = "json" in content_type.lower() or _looks_like_json(text)
        is_html = "html" in content_type.lower() or _looks_like_html(text)
        title = ""
        if is_html and text:
            soup = BeautifulSoup(text, "lxml")
            if soup.title and soup.title.string:
                title = soup.title.string.strip()
        return {
            "url": url,
            "status_code": status,
            "content_type": content_type,
            "title": title,
            "is_json": is_json,
            "is_html": is_html,
            "used_flaresolverr": used_fs,
            "error": error,
            "text": text,
            "sample": text[:2000],
            "proxy": self.proxy_label,
        }


# 兼容旧名
WarpClient = CrawlClient


def _looks_like_cf(text: str) -> bool:
    t = (text or "").lower()
    return any(
        x in t
        for x in (
            "cdn-cgi/challenge",
            "just a moment",
            "cf-browser-verification",
            "attention required",
            "cloudflare",
            "无法显示此网页",
        )
    )


def _looks_like_json(text: str) -> bool:
    s = (text or "").lstrip()
    if not s or s[0] not in "{[":
        return False
    try:
        json.loads(s)
        return True
    except Exception:
        return False


def _looks_like_html(text: str) -> bool:
    s = (text or "").lstrip().lower()
    return s.startswith("<!doctype html") or s.startswith("<html") or "<body" in s[:2000]


def normalize_base_url(url: str) -> str:
    p = urlparse(url if "://" in url else f"https://{url}")
    scheme = p.scheme or "https"
    netloc = p.netloc or p.path
    return f"{scheme}://{netloc}".rstrip("/")


def abs_url(base: str, href: str) -> str:
    return urljoin(base if base.endswith("/") else base + "/", href)


def slugify_pkg(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "", name).lower()
    if not s:
        s = "site"
    if s[0].isdigit():
        s = "s" + s
    return s[:32]
