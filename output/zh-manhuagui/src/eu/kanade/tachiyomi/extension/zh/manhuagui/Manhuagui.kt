package eu.kanade.tachiyomi.extension.zh.manhuagui

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

class Manhuagui : ParsedHttpSource() {

    override val name = "manhuagui"
    override val baseUrl = "https://www.manhuagui.com"
    override val lang = "zh"
    override val supportsLatest = true

    // ===== Popular =====
    override fun popularMangaRequest(page: Int): Request {
        val url = "https://www.manhuagui.com/update".toHttpUrl().newBuilder()
        // TODO: 按站点分页参数调整，常见 pn/page/pageNum
        if (page > 1) url.addQueryParameter("page", page.toString())
        return GET(url.build(), headers)
    }

    override fun popularMangaSelector() = ".ell"
    override fun popularMangaNextPageSelector() = null

    override fun popularMangaFromElement(element: Element): SManga = SManga.create().apply {
        val a = element.selectFirst("a") ?: element.selectFirst("a")
        setUrlWithoutDomain(a?.attr("href") ?: element.attr("href"))
        title = (a?.text()?.ifBlank { null } ?: element.selectFirst("a")?.text() ?: a?.attr("title") ?: "").trim()
        thumbnail_url = element.selectFirst("img")?.let { img ->
            absUrl(img, "data-src", "data-original", "src")
        }
    }

    // ===== Latest =====
    override fun latestUpdatesRequest(page: Int): Request {
        val url = "https://www.manhuagui.com/update".toHttpUrl().newBuilder()
        if (page > 1) url.addQueryParameter("page", page.toString())
        return GET(url.build(), headers)
    }

    override fun latestUpdatesSelector() = popularMangaSelector()
    override fun latestUpdatesNextPageSelector() = popularMangaNextPageSelector()
    override fun latestUpdatesFromElement(element: Element) = popularMangaFromElement(element)

    // ===== Search =====
    override fun searchMangaRequest(page: Int, query: String, filters: FilterList): Request {
        val url = "https://www.manhuagui.com/search".toHttpUrl().newBuilder()
            .addQueryParameter("q", query)
            .addQueryParameter("page", page.toString())
            .build()
        return GET(url, headers)
    }

    override fun searchMangaSelector() = popularMangaSelector()
    override fun searchMangaNextPageSelector() = popularMangaNextPageSelector()
    override fun searchMangaFromElement(element: Element) = popularMangaFromElement(element)

    // ===== Details =====
    override fun mangaDetailsParse(document: Document): SManga = SManga.create().apply {
        title = document.selectFirst("h1")?.text()?.trim().orEmpty()
        author = document.selectFirst(".author")?.text()?.trim()
        description = document.selectFirst(".desc")?.text()?.trim()
        genre = document.select(".genre a").joinToString { it.text().trim() }
        thumbnail_url = document.selectFirst("img")?.let { img ->
            absUrl(img, "data-src", "data-original", "src")
        }
        status = when {
            document.selectFirst(".status")?.text()?.contains("完") == true -> SManga.COMPLETED
            document.selectFirst(".status")?.text()?.contains("连载") == true -> SManga.ONGOING
            else -> SManga.UNKNOWN
        }
    }

    // ===== Chapters =====
    override fun chapterListSelector() = "div.chapter-list a"

    override fun chapterFromElement(element: Element): SChapter = SChapter.create().apply {
        val a = element.selectFirst("a") ?: element.selectFirst("a") ?: element
        name = (element.selectFirst("a")?.text() ?: a.text()).trim()
        setUrlWithoutDomain(a.attr("href"))
    }

    // ===== Pages =====
    override fun pageListParse(document: Document): List<Page> {
        return document.select("img").mapIndexed { idx, img ->
            val url = absUrl(img, "src", "data-src", "data-original", "src")
            Page(idx, document.location(), url)
        }.filter { it.imageUrl?.isNotBlank() == true }
    }

    override fun imageUrlParse(document: Document) = throw UnsupportedOperationException()

    private fun absUrl(el: Element, vararg attrs: String): String {
        for (attr in attrs) {
            val v = el.attr(attr)
            if (v.isNotBlank() && !v.startsWith("data:")) {
                return when {
                    v.startsWith("http") -> v
                    v.startsWith("//") -> "https:$v"
                    else -> baseUrl.trimEnd('/') + "/" + v.trimStart('/')
                }
            }
        }
        return el.absUrl("src")
    }
}
