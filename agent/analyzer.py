from __future__ import annotations

import re
from collections import Counter
from typing import Any, Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag

from .models import LinkSample, PageProbe, SiteStructure
from .warp_client import CrawlClient, abs_url, normalize_base_url


POPULAR_PATHS = ["/", "/hots", "/hot", "/rank", "/ranking", "/popular", "/top", "/comics", "/manga", "/category"]
LATEST_PATHS = ["/latest", "/update", "/updates", "/new", "/recent"]
SEARCH_PATHS = ["/search", "/search/", "/sssearch", "/comics/search", "/manga/search", "/api/search"]
API_HINTS = [r"/api/", r"/apis/", r"/v\d", r"graphql", r"/ajax/", r"chapter", r"manga", r"comic"]


class SiteAnalyzer:
    def __init__(self, client: CrawlClient, lang: str = "zh") -> None:
        self.client = client
        self.lang = lang

    def analyze(self, seed_url: str, site_name: str = "") -> SiteStructure:
        base = normalize_base_url(seed_url)
        result = SiteStructure(
            seed_url=seed_url if "://" in seed_url else f"https://{seed_url}",
            base_url=base,
            site_name=site_name or urlparse(base).netloc.split(":")[0],
            lang=self.lang,
        )

        home = self.client.fetch_smart(base + "/")
        result.raw_probes.append(_to_probe(home))
        if home.get("used_flaresolverr"):
            result.needs_flaresolverr = True
        if home.get("error"):
            result.notes.append(f"homepage error: {home['error']}")

        probes: dict[str, dict[str, Any]] = {"home": home}
        for path in POPULAR_PATHS + LATEST_PATHS + SEARCH_PATHS:
            url = base + path
            if any(p.get("url") == url for p in probes.values()):
                continue
            try:
                data = self.client.fetch_smart(url)
            except Exception as e:
                data = {
                    "url": url,
                    "status_code": 0,
                    "error": str(e),
                    "text": "",
                    "is_html": False,
                    "is_json": False,
                    "used_flaresolverr": False,
                    "content_type": "",
                    "title": "",
                    "sample": "",
                }
            probes[path] = data
            result.raw_probes.append(_to_probe(data))
            if data.get("used_flaresolverr"):
                result.needs_flaresolverr = True

        html_pages = [p for p in probes.values() if p.get("is_html") and p.get("text") and int(p.get("status_code") or 0) < 400]
        json_pages = [p for p in probes.values() if p.get("is_json") and p.get("text")]
        if json_pages and not html_pages:
            result.engine = "json_api"
        elif json_pages and html_pages:
            result.engine = "mixed"
        elif html_pages:
            result.engine = "html"
        else:
            result.engine = "unknown"
            result.notes.append("未能拿到有效 HTML/JSON，可能被强防护或域名失效")

        for p in probes.values():
            text = p.get("text") or ""
            for m in re.findall(r"https?://[^\s\"'<>]+", text):
                if any(re.search(h, m, re.I) for h in API_HINTS) and m not in result.api_endpoints:
                    result.api_endpoints.append(m)
            for m in re.findall(r"[\"'](/[^\"']*(?:api|apis|ajax|chapter|manga|comic)[^\"']*)[\"']", text, re.I):
                full = abs_url(base, m)
                if full not in result.api_endpoints:
                    result.api_endpoints.append(full)

        popular_candidate = self._pick_list_page(probes, prefer_keys=["/hots", "/hot", "/rank", "/popular", "home", "/"])
        latest_candidate = self._pick_list_page(probes, prefer_keys=["/latest", "/update", "/updates", "/new"])
        if popular_candidate:
            result.popular_url = popular_candidate["url"]
            self._fill_list_selectors(result, popular_candidate)
        if latest_candidate:
            result.latest_url = latest_candidate["url"]
            if not result.manga_item_selector:
                self._fill_list_selectors(result, latest_candidate)

        search_candidate = self._pick_search_page(probes)
        if search_candidate:
            result.search_url = search_candidate["url"]
            result.search_method = self._detect_search_method(search_candidate.get("text") or "") or "get"

        manga_url = result.manga_list_samples[0].url if result.manga_list_samples else None
        if not manga_url and popular_candidate:
            manga_url = self._first_manga_like_link(popular_candidate.get("text") or "", base)
        if manga_url:
            result.manga_details_url_pattern = _guess_pattern(base, manga_url)
            details = self.client.fetch_smart(manga_url)
            result.raw_probes.append(_to_probe(details))
            if details.get("is_html") and details.get("text"):
                self._fill_details_and_chapters(result, details, base)

        if result.chapter_samples:
            ch_url = result.chapter_samples[0].url
            pages = self.client.fetch_smart(ch_url)
            result.raw_probes.append(_to_probe(pages))
            if pages.get("is_html") and pages.get("text"):
                self._fill_page_images(result, pages)
            elif pages.get("is_json") and pages.get("text"):
                result.page_api_url = ch_url
                result.notes.append("章节页返回 JSON，需在扩展里按 API 解析图片")

        result.confidence = _score(result)
        result.api_endpoints = result.api_endpoints[:30]
        result.raw_probes = result.raw_probes[:40]
        return result

    def _pick_list_page(self, probes: dict[str, dict[str, Any]], prefer_keys: list[str]) -> Optional[dict[str, Any]]:
        ranked: list[tuple[float, dict[str, Any]]] = []
        for key, p in probes.items():
            if not p.get("is_html") or not p.get("text") or int(p.get("status_code") or 0) >= 400:
                continue
            score = self._list_page_score(p.get("text") or "")
            if key in prefer_keys:
                score += 2
            if score > 0:
                ranked.append((score, p))
        if not ranked:
            home = probes.get("home")
            return home if home and home.get("is_html") else None
        ranked.sort(key=lambda x: x[0], reverse=True)
        return ranked[0][1]

    def _list_page_score(self, html: str) -> float:
        soup = BeautifulSoup(html, "lxml")
        manga_like = sum(1 for a in soup.find_all("a", href=True) if _is_manga_path(a["href"]))
        imgs = len(soup.find_all("img"))
        score = manga_like * 0.5 + min(imgs, 30) * 0.05
        for sel in ("div.item", "div.comic-item", "li.item", "div.book-item", "div.manga-item", "div.card"):
            if soup.select(sel):
                score += 1.5
        return score

    def _fill_list_selectors(self, result: SiteStructure, page: dict[str, Any]) -> None:
        html = page.get("text") or ""
        soup = BeautifulSoup(html, "lxml")
        base = result.base_url
        candidates = self._candidate_item_selectors(soup)
        if not candidates:
            samples = [
                LinkSample(url=abs_url(base, a["href"]), text=a.get_text(" ", strip=True)[:80], score=1)
                for a in soup.find_all("a", href=True)
                if _is_manga_path(a["href"])
            ]
            result.manga_list_samples = _unique_samples(samples)[:12]
            result.manga_item_selector = "a[href*='manga'], a[href*='comic'], a[href*='book']"
            result.manga_url_selector = "a"
            result.manga_title_selector = "a"
            return

        best_sel, items = candidates[0]
        result.manga_item_selector = best_sel
        result.manga_url_selector = "a"
        result.manga_title_selector = "a"
        if items and items[0].select_one("img"):
            result.manga_thumbnail_selector = "img"
        samples: list[LinkSample] = []
        for it in items[:12]:
            link = it.select_one("a[href]")
            if not link:
                continue
            samples.append(
                LinkSample(
                    url=abs_url(base, link["href"]),
                    text=(link.get_text(" ", strip=True) or it.get_text(" ", strip=True))[:80],
                    score=1.0,
                )
            )
        result.manga_list_samples = _unique_samples(samples)
        for a in soup.find_all("a", href=True):
            t = a.get_text(strip=True)
            if t in {"下一页", "下页", "Next", "next", ">"}:
                result.next_page_selector = "a.next" if "next" in " ".join(a.get("class") or []).lower() else f"a[href='{a['href']}']"
                break

    def _candidate_item_selectors(self, soup: BeautifulSoup) -> list[tuple[str, list[Tag]]]:
        sels = [
            "div.comic-item", "div.manga-item", "div.book-item", "li.comic-item",
            "div.item", "li.item", "div.card", "div.grid-item", "div.list-item",
            "div.mh-item", "li.mh-item", ".common-comic-item",
        ]
        found: list[tuple[str, list[Tag]]] = []
        for sel in sels:
            try:
                items = [i for i in soup.select(sel) if i.select_one("a[href]")]
            except Exception:
                continue
            if len(items) >= 4:
                found.append((sel, items))
        class_counter: Counter[str] = Counter()
        for a in soup.find_all("a", href=True):
            if not _is_manga_path(a["href"]):
                continue
            parent = a.parent
            if isinstance(parent, Tag):
                for c in parent.get("class") or []:
                    class_counter[c] += 1
        for cls, cnt in class_counter.most_common(8):
            if cnt < 4:
                continue
            sel = f".{cls}"
            items = [i for i in soup.select(sel) if i.select_one("a[href]")]
            if len(items) >= 4:
                found.append((sel, items))
        uniq = {sel: items for sel, items in found}
        return sorted(uniq.items(), key=lambda x: len(x[1]), reverse=True)

    def _pick_search_page(self, probes: dict[str, dict[str, Any]]) -> Optional[dict[str, Any]]:
        for key, p in probes.items():
            if "search" in str(key) and int(p.get("status_code") or 0) and int(p.get("status_code") or 500) < 500:
                return p
            if p.get("is_html") and re.search(r"<form[^>]*(search|keyword)", (p.get("text") or ""), re.I):
                return p
        return None

    def _detect_search_method(self, html: str) -> Optional[str]:
        soup = BeautifulSoup(html, "lxml")
        for form in soup.find_all("form"):
            action = (form.get("action") or "").lower()
            if "search" in action or form.select_one("input[name*=key], input[name*=search], input[type=search]"):
                return "post" if (form.get("method") or "get").lower() == "post" else "get"
        return None

    def _first_manga_like_link(self, html: str, base: str) -> Optional[str]:
        soup = BeautifulSoup(html, "lxml")
        for a in soup.find_all("a", href=True):
            if _is_manga_path(a["href"]):
                return abs_url(base, a["href"])
        return None

    def _fill_details_and_chapters(self, result: SiteStructure, page: dict[str, Any], base: str) -> None:
        soup = BeautifulSoup(page.get("text") or "", "lxml")
        for sel in ("h1", "h2.mg-title", "h1.title", ".comic-title", ".book-title", ".manga-title"):
            el = soup.select_one(sel)
            if el and el.get_text(strip=True):
                result.details_title_selector = sel
                break
        for sel in ("p.author", ".author", "span.author", "div.author"):
            if soup.select_one(sel):
                result.details_author_selector = sel
                break
        for sel in (".desc", ".description", "#intro", ".comic-intro", ".manga-introduction"):
            if soup.select_one(sel):
                result.details_desc_selector = sel
                break
        for sel in (".cover img", ".comic-cover img", ".manga-cover img", "div.cover img", "img.cover"):
            if soup.select_one(sel):
                result.details_thumbnail_selector = sel
                break
        for sel in (".tags a", ".genre a", ".cate a", "p.mg-cate a"):
            if soup.select(sel):
                result.details_genre_selector = sel
                break
        for sel in (".status", "span.status", "p.status"):
            if soup.select_one(sel):
                result.details_status_selector = sel
                break

        chapter_sels = [
            "ul.chapter-list li", "div.chapter-list a", "li.chapter-item",
            "#chapterlistload li", ".chapter-container a", "div#chapter-list a",
            "ul#detail-list-select li", "div.comic-chapters a", "a.chapter-item",
        ]
        for sel in chapter_sels:
            items = soup.select(sel)
            if len(items) >= 1:
                result.chapter_item_selector = sel
                result.chapter_url_selector = "a" if items[0].name != "a" else ""
                result.chapter_name_selector = "a" if items[0].name != "a" else ""
                samples: list[LinkSample] = []
                for it in items[:20]:
                    a = it if it.name == "a" else it.select_one("a[href]")
                    if not a or not a.get("href"):
                        continue
                    samples.append(LinkSample(url=abs_url(base, a["href"]), text=a.get_text(" ", strip=True)[:80], score=1))
                result.chapter_samples = _unique_samples(samples)
                if result.chapter_samples:
                    break
        if not result.chapter_samples:
            # fallback: chapter-like links (含 manhuagui /comic/id/cid.html)
            samples = []
            page_path = urlparse(page.get("url") or "").path.rstrip("/")
            manga_id = ""
            m = re.search(r"/(?:comic|manga|book|manhua)/([0-9a-zA-Z_-]+)", page_path)
            if m:
                manga_id = m.group(1)
            for a in soup.find_all("a", href=True):
                href = a["href"]
                text = a.get_text(" ", strip=True)[:80]
                score = 0.0
                if re.search(r"chapter|read|ch_|/c\d+|view", href, re.I):
                    score = 0.8
                # /comic/27857/897057.html
                if manga_id and re.search(rf"/(?:comic|manga|book)/{re.escape(manga_id)}/\d+(?:\.html)?", href):
                    score = 1.0
                elif re.search(r"/(?:comic|manga|book)/\d+/\d+(?:\.html)?", href):
                    score = 0.6
                # 文本像“第x话”
                if re.search(r"第\s*[\d.]+\s*[话卷章]|开始阅读|连载|完结", text):
                    score = max(score, 0.7)
                if score > 0:
                    samples.append(LinkSample(url=abs_url(base, href), text=text, score=score))
            samples.sort(key=lambda s: s.score, reverse=True)
            # 优先同漫画 id 的章节
            result.chapter_samples = _unique_samples(samples)[:30]
            if result.chapter_samples:
                if manga_id:
                    result.chapter_item_selector = f"a[href*='/{manga_id}/']"
                else:
                    result.chapter_item_selector = "a[href*='.html']"
                result.chapter_url_selector = ""
                result.chapter_name_selector = ""
                result.notes.append("章节选择器为启发式，建议人工复核")

    def _fill_page_images(self, result: SiteStructure, page: dict[str, Any]) -> None:
        soup = BeautifulSoup(page.get("text") or "", "lxml")
        for sel in (
            "div.comicpage img", "div#cp_img img", "div.chapter-content img",
            "div.reader-main img", "div.manga-reader img", "img.comic-page",
            "div#images img", "div.page-content img", "img[data-src]",
        ):
            imgs = soup.select(sel)
            if len(imgs) >= 1:
                result.page_image_selector = sel
                # attr preference
                sample = imgs[0]
                for attr in ("data-src", "data-original", "data-lazy", "src"):
                    if sample.get(attr):
                        result.page_image_attr = attr
                        break
                result.page_samples = []
                for img in imgs[:5]:
                    for attr in (result.page_image_attr, "data-src", "src"):
                        v = img.get(attr)
                        if v and not str(v).startswith("data:"):
                            result.page_samples.append(v)
                            break
                return
        # fallback any large content images
        imgs = [i for i in soup.find_all("img") if i.get("src") or i.get("data-src")]
        if imgs:
            result.page_image_selector = "img"
            result.page_image_attr = "data-src" if imgs[0].get("data-src") else "src"
            result.notes.append("图片选择器为通用 img，可能含噪声")


def _to_probe(data: dict[str, Any]) -> PageProbe:
    return PageProbe(
        url=str(data.get("url") or ""),
        status_code=int(data.get("status_code") or 0),
        content_type=str(data.get("content_type") or ""),
        title=str(data.get("title") or ""),
        is_json=bool(data.get("is_json")),
        is_html=bool(data.get("is_html")),
        used_flaresolverr=bool(data.get("used_flaresolverr")),
        error=str(data.get("error") or ""),
        sample=str(data.get("sample") or "")[:500],
    )


def _is_manga_path(href: str) -> bool:
    h = (href or "").lower()
    if not h or h.startswith("javascript:") or h == "#" or h.startswith("mailto:"):
        return False
    # 常见漫画详情路径；排除章节/图片页
    if re.search(r"/(chapter|read|viewer|view|page|pages)/", h):
        return False
    if re.search(r"/(manga|comic|book|manhua|mh|series|title|detail)/[a-z0-9_-]+", h):
        # /comic/123/ 算详情；/comic/123/456.html 更像章节，降权但仍可作入口
        return True
    # manhuagui: /comic/12345/
    if re.search(r"/comic/\d+/?$", h):
        return True
    return False


def _unique_samples(samples: list[LinkSample]) -> list[LinkSample]:
    seen = set()
    out = []
    for s in samples:
        if s.url in seen:
            continue
        seen.add(s.url)
        out.append(s)
    return out


def _guess_pattern(base: str, url: str) -> str:
    path = urlparse(url).path
    parts = [p for p in path.split("/") if p]
    if not parts:
        return base + "/"
    # replace last id-like segment
    if re.fullmatch(r"[0-9a-fA-F-]{4,}|[0-9]+", parts[-1]):
        parts[-1] = "{id}"
    return base + "/" + "/".join(parts)


def _score(result: SiteStructure) -> float:
    score = 0.0
    if result.manga_item_selector:
        score += 0.2
    if result.manga_list_samples:
        score += 0.2
    if result.details_title_selector:
        score += 0.15
    if result.chapter_item_selector or result.chapter_samples:
        score += 0.25
    if result.page_image_selector or result.page_api_url:
        score += 0.2
    if result.needs_flaresolverr:
        score -= 0.05
    return max(0.0, min(1.0, score))
