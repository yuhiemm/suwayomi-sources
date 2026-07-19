from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .models import SiteStructure
from .warp_client import slugify_pkg


EXT_TEMPLATE_KT = '''package eu.kanade.tachiyomi.extension.{lang}.{pkg}

import eu.kanade.tachiyomi.network.GET
import eu.kanade.tachiyomi.source.model.FilterList
import eu.kanade.tachiyomi.source.model.Page
import eu.kanade.tachiyomi.source.model.SChapter
import eu.kanade.tachiyomi.source.model.SManga
import eu.kanade.tachiyomi.source.online.ParsedHttpSource
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.Request
import org.jsoup.nodes.Document
import org.jsoup.nodes.Element

class {class_name} : ParsedHttpSource() {{

    override val name = "{display_name}"
    override val baseUrl = "{base_url}"
    override val lang = "{lang}"
    override val supportsLatest = {supports_latest}

    // ===== Popular =====
    override fun popularMangaRequest(page: Int): Request {{
        val url = "{popular_url}".toHttpUrl().newBuilder()
        // TODO: 按站点分页参数调整，常见 pn/page/pageNum
        if (page > 1) url.addQueryParameter("page", page.toString())
        return GET(url.build(), headers)
    }}

    override fun popularMangaSelector() = "{manga_item_selector}"
    override fun popularMangaNextPageSelector() = {next_page_sel}

    override fun popularMangaFromElement(element: Element): SManga = SManga.create().apply {{
        val a = element.selectFirst("{manga_url_selector}") ?: element.selectFirst("a")
        setUrlWithoutDomain(a?.attr("href") ?: element.attr("href"))
        title = (a?.text()?.ifBlank {{ null }} ?: element.selectFirst("{manga_title_selector}")?.text() ?: a?.attr("title") ?: "").trim()
        thumbnail_url = element.selectFirst("{manga_thumbnail_selector}")?.let {{ img ->
            absUrl(img, "data-src", "data-original", "src")
        }}
    }}

    // ===== Latest =====
    override fun latestUpdatesRequest(page: Int): Request {{
        val url = "{latest_url}".toHttpUrl().newBuilder()
        if (page > 1) url.addQueryParameter("page", page.toString())
        return GET(url.build(), headers)
    }}

    override fun latestUpdatesSelector() = popularMangaSelector()
    override fun latestUpdatesNextPageSelector() = popularMangaNextPageSelector()
    override fun latestUpdatesFromElement(element: Element) = popularMangaFromElement(element)

    // ===== Search =====
    override fun searchMangaRequest(page: Int, query: String, filters: FilterList): Request {{
        val url = "{search_url}".toHttpUrl().newBuilder()
            .addQueryParameter("q", query)
            .addQueryParameter("page", page.toString())
            .build()
        return GET(url, headers)
    }}

    override fun searchMangaSelector() = popularMangaSelector()
    override fun searchMangaNextPageSelector() = popularMangaNextPageSelector()
    override fun searchMangaFromElement(element: Element) = popularMangaFromElement(element)

    // ===== Details =====
    override fun mangaDetailsParse(document: Document): SManga = SManga.create().apply {{
        title = document.selectFirst("{details_title_selector}")?.text()?.trim().orEmpty()
        author = document.selectFirst("{details_author_selector}")?.text()?.trim()
        description = document.selectFirst("{details_desc_selector}")?.text()?.trim()
        genre = document.select("{details_genre_selector}").joinToString {{ it.text().trim() }}
        thumbnail_url = document.selectFirst("{details_thumbnail_selector}")?.let {{ img ->
            absUrl(img, "data-src", "data-original", "src")
        }}
        status = when {{
            document.selectFirst("{details_status_selector}")?.text()?.contains("完") == true -> SManga.COMPLETED
            document.selectFirst("{details_status_selector}")?.text()?.contains("连载") == true -> SManga.ONGOING
            else -> SManga.UNKNOWN
        }}
    }}

    // ===== Chapters =====
    override fun chapterListSelector() = "{chapter_item_selector}"

    override fun chapterFromElement(element: Element): SChapter = SChapter.create().apply {{
        val a = element.selectFirst("{chapter_url_selector}") ?: element.selectFirst("a") ?: element
        name = (element.selectFirst("{chapter_name_selector}")?.text() ?: a.text()).trim()
        setUrlWithoutDomain(a.attr("href"))
    }}

    // ===== Pages =====
    override fun pageListParse(document: Document): List<Page> {{
        return document.select("{page_image_selector}").mapIndexed {{ idx, img ->
            val url = absUrl(img, "{page_image_attr}", "data-src", "data-original", "src")
            Page(idx, document.location(), url)
        }}.filter {{ it.imageUrl?.isNotBlank() == true }}
    }}

    override fun imageUrlParse(document: Document) = throw UnsupportedOperationException()

    private fun absUrl(el: Element, vararg attrs: String): String {{
        for (attr in attrs) {{
            val v = el.attr(attr)
            if (v.isNotBlank() && !v.startsWith("data:")) {{
                return when {{
                    v.startsWith("http") -> v
                    v.startsWith("//") -> "https:$v"
                    else -> baseUrl.trimEnd('/') + "/" + v.trimStart('/')
                }}
            }}
        }}
        return el.absUrl("src")
    }}
}}
'''


BUILD_GRADLE = '''plugins {{
    id("com.android.application")
    kotlin("android")
}}

android {{
    namespace = "eu.kanade.tachiyomi.extension.{lang}.{pkg}"
    compileSdk = 34

    defaultConfig {{
        applicationId = "eu.kanade.tachiyomi.extension.{lang}.{pkg}"
        minSdk = 21
        targetSdk = 34
        versionCode = {version_code}
        versionName = "1.4.{version_code}"
        manifestPlaceholders["appName"] = "Tachiyomi: {display_name}"
    }}

    sourceSets {{
        named("main") {{
            manifest.srcFile("AndroidManifest.xml")
            java.setSrcDirs(listOf("src"))
            res.setSrcDirs(listOf("res"))
            assets.setSrcDirs(listOf("assets"))
        }}
    }}

    compileOptions {{
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }}
    kotlinOptions {{
        jvmTarget = "17"
    }}
}}

dependencies {{
    compileOnly(libs.bundles.common)
}}
'''


MANIFEST = '''<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
    <application android:icon="@mipmap/ic_launcher" android:label="${{appName}}" android:supportsRtl="true">
        <meta-data android:name="tachiyomi.extension.class" android:value=".{class_name}" />
        <meta-data android:name="tachiyomi.extension.nsfw" android:value="false" />
    </application>
</manifest>
'''


class ExtensionGenerator:
    """根据 SiteStructure 生成可提交到 GitHub 编译的扩展源码骨架。"""

    def __init__(self, output_dir: str | Path) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate(self, structure: SiteStructure, display_name: str | None = None, pkg: str | None = None) -> dict[str, Any]:
        name = display_name or structure.site_name or "Generated"
        pkg_name = pkg or slugify_pkg(name)
        class_name = re.sub(r"[^A-Za-z0-9]", "", name.title()) or "GeneratedSource"
        if class_name[0].isdigit():
            class_name = "S" + class_name
        lang = structure.lang or "zh"
        version_code = 1

        root = self.output_dir / f"{lang}-{pkg_name}"
        src_dir = root / "src" / "eu" / "kanade" / "tachiyomi" / "extension" / lang / pkg_name
        src_dir.mkdir(parents=True, exist_ok=True)
        (root / "res" / "mipmap-hdpi").mkdir(parents=True, exist_ok=True)
        (root / "assets").mkdir(parents=True, exist_ok=True)

        popular = structure.popular_url or structure.base_url
        latest = structure.latest_url or popular
        search = structure.search_url or (structure.base_url + "/search")
        next_sel = f'"{structure.next_page_selector}"' if structure.next_page_selector else "null"

        kt = EXT_TEMPLATE_KT.format(
            lang=lang,
            pkg=pkg_name,
            class_name=class_name,
            display_name=name,
            base_url=structure.base_url,
            supports_latest="true" if structure.latest_url else "false",
            popular_url=popular,
            latest_url=latest,
            search_url=search,
            manga_item_selector=structure.manga_item_selector or "a",
            manga_url_selector=structure.manga_url_selector or "a",
            manga_title_selector=structure.manga_title_selector or "a",
            manga_thumbnail_selector=structure.manga_thumbnail_selector or "img",
            next_page_sel=next_sel,
            details_title_selector=structure.details_title_selector or "h1",
            details_author_selector=structure.details_author_selector or ".author",
            details_desc_selector=structure.details_desc_selector or ".desc",
            details_genre_selector=structure.details_genre_selector or ".genre a",
            details_thumbnail_selector=structure.details_thumbnail_selector or "img",
            details_status_selector=structure.details_status_selector or ".status",
            chapter_item_selector=structure.chapter_item_selector or "a",
            chapter_url_selector=structure.chapter_url_selector or "a",
            chapter_name_selector=structure.chapter_name_selector or "a",
            page_image_selector=structure.page_image_selector or "img",
            page_image_attr=structure.page_image_attr or "src",
        )
        (src_dir / f"{class_name}.kt").write_text(kt, encoding="utf-8")
        (root / "AndroidManifest.xml").write_text(
            MANIFEST.format(class_name=class_name), encoding="utf-8"
        )
        (root / "build.gradle.kts").write_text(
            BUILD_GRADLE.format(
                lang=lang,
                pkg=pkg_name,
                display_name=name,
                version_code=version_code,
            ),
            encoding="utf-8",
        )
        report = {
            "package": f"eu.kanade.tachiyomi.extension.{lang}.{pkg_name}",
            "class_name": class_name,
            "display_name": name,
            "lang": lang,
            "pkg": pkg_name,
            "path": str(root),
            "structure": structure.summary(),
            "notes": structure.notes
            + [
                "此为自动生成骨架，分页参数/搜索字段/反爬细节可能需人工微调",
                "推荐放到 keiyoushi/extensions-source 风格 monorepo 由 CI 编译",
            ],
        }
        (root / "analysis.json").write_text(
            json.dumps(structure.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (root / "generator-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return report
