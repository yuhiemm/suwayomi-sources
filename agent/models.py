from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class LinkSample(BaseModel):
    url: str
    text: str = ""
    score: float = 0.0


class PageProbe(BaseModel):
    url: str
    status_code: int = 0
    content_type: str = ""
    title: str = ""
    is_json: bool = False
    is_html: bool = False
    used_flaresolverr: bool = False
    error: str = ""
    sample: str = ""


class SiteStructure(BaseModel):
    """分析结果：足够生成一个 ParsedHttpSource / HttpSource 扩展。"""

    seed_url: str
    base_url: str
    site_name: str = ""
    lang: str = "zh"
    engine: Literal["html", "json_api", "mixed", "unknown"] = "unknown"

    # 列表
    popular_url: str = ""
    latest_url: str = ""
    search_url: str = ""
    search_method: Literal["get", "post", "unknown"] = "unknown"
    manga_list_selector: str = ""
    manga_item_selector: str = ""
    manga_title_selector: str = ""
    manga_url_selector: str = ""
    manga_thumbnail_selector: str = ""
    next_page_selector: str = ""
    manga_list_samples: list[LinkSample] = Field(default_factory=list)

    # 详情
    manga_details_url_pattern: str = ""
    details_title_selector: str = ""
    details_author_selector: str = ""
    details_desc_selector: str = ""
    details_thumbnail_selector: str = ""
    details_genre_selector: str = ""
    details_status_selector: str = ""

    # 章节
    chapter_list_selector: str = ""
    chapter_item_selector: str = ""
    chapter_name_selector: str = ""
    chapter_url_selector: str = ""
    chapter_samples: list[LinkSample] = Field(default_factory=list)

    # 图片页
    page_image_selector: str = ""
    page_image_attr: str = "src"
    page_api_url: str = ""
    page_samples: list[str] = Field(default_factory=list)

    # API 线索
    api_endpoints: list[str] = Field(default_factory=list)
    headers_needed: dict[str, str] = Field(default_factory=dict)
    needs_flaresolverr: bool = False
    notes: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    raw_probes: list[PageProbe] = Field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "site_name": self.site_name,
            "base_url": self.base_url,
            "engine": self.engine,
            "popular_url": self.popular_url,
            "latest_url": self.latest_url,
            "search_url": self.search_url,
            "manga_item_selector": self.manga_item_selector,
            "chapter_item_selector": self.chapter_item_selector,
            "page_image_selector": self.page_image_selector,
            "api_endpoints": self.api_endpoints,
            "needs_flaresolverr": self.needs_flaresolverr,
            "confidence": self.confidence,
            "notes": self.notes,
        }
