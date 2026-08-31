package com.binnight.app.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray
import org.json.JSONObject
import org.json.JSONTokener
import java.net.URLEncoder
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.time.format.TextStyle
import java.util.Locale
import java.util.concurrent.TimeUnit

/**
 * Talks to the council's Seamless waste API (see [SeamlessConfig]) and turns the
 * responses into a [BinSchedule]. Parsing is deliberately forgiving so that
 * small differences between our reconstructed API and the real one don't break
 * the app — see [extractServices] and [parseFlexibleDate].
 */
class BinRepository(
    private val client: OkHttpClient = defaultClient(),
) {

    /** Resolve a typed/geocoded address into candidate properties. */
    suspend fun searchAddress(query: String): List<PropertyMatch> =
        withContext(Dispatchers.IO) {
            val url = SeamlessConfig.ADDRESS_SEARCH_URL
                .replace("{query}", URLEncoder.encode(query.trim(), "UTF-8"))
            val body = get(url)
            parsePropertyMatches(body)
        }

    /** Fetch and interpret the collection days for a resolved property. */
    suspend fun collectionDays(property: PropertyMatch): BinSchedule =
        withContext(Dispatchers.IO) {
            val url = SeamlessConfig.COLLECTION_DAYS_URL
                .replace("{propertyKey}", URLEncoder.encode(property.propertyKey, "UTF-8"))
            val body = get(url)
            buildSchedule(property.address, body)
        }

    // --- HTTP ---------------------------------------------------------------

    private fun get(url: String): String {
        val builder = Request.Builder().url(url).get()
        SeamlessConfig.HEADERS.forEach { (k, v) -> builder.header(k, v) }
        client.newCall(builder.build()).execute().use { resp ->
            val text = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) {
                throw BinApiException("Council API returned HTTP ${resp.code}.")
            }
            return text
        }
    }

    // --- Address search parsing --------------------------------------------

    internal fun parsePropertyMatches(body: String): List<PropertyMatch> {
        val root = runCatching { JSONTokener(body).nextValue() }.getOrNull()
            ?: return emptyList()
        val out = LinkedHashMap<String, PropertyMatch>()
        walk(root) { obj ->
            val key = firstStringField(obj, SeamlessConfig.PROPERTY_KEY_FIELDS)
            val label = firstStringField(obj, SeamlessConfig.ADDRESS_LABEL_FIELDS)
            if (!key.isNullOrBlank() && !label.isNullOrBlank()) {
                out.putIfAbsent(key, PropertyMatch(key, label))
            }
        }
        return out.values.toList()
    }

    // --- Collection-days parsing -------------------------------------------

    internal fun buildSchedule(address: String, body: String): BinSchedule {
        val services = extractServices(body)
        val today = LocalDate.now()

        // Keep the soonest *upcoming* date per bin type.
        val byType = LinkedHashMap<BinType, BinCollection>()
        for (s in services) {
            if (s.nextDate.isBefore(today)) continue
            val existing = byType[s.type]
            if (existing == null || s.nextDate.isBefore(existing.nextDate)) {
                byType[s.type] = s
            }
        }

        val upcoming = byType.values.sortedBy { it.nextDate }
        val nextDate = upcoming.firstOrNull()?.nextDate
        val dueNext = upcoming.filter { it.nextDate == nextDate }
        return BinSchedule(address, nextDate, dueNext, upcoming)
    }

    /**
     * Walk the response and collect every (service name, date) pair we can find,
     * whether the API nests them as objects (`{name, nextDate}`) or keys them by
     * service (`{"GeneralWaste": "2026-09-02"}`), or returns an HTML fragment.
     */
    internal fun extractServices(body: String): List<BinCollection> {
        val found = LinkedHashSet<Pair<String, LocalDate>>()

        val root = runCatching { JSONTokener(body).nextValue() }.getOrNull()
        if (root != null) {
            walk(root) { obj ->
                // Pattern A: an object carrying both a name and a date field.
                val name = firstStringField(obj, SeamlessConfig.SERVICE_NAME_FIELDS)
                val dateStr = firstStringField(obj, SeamlessConfig.SERVICE_DATE_FIELDS)
                if (!name.isNullOrBlank() && dateStr != null) {
                    parseFlexibleDate(dateStr)?.let { found += name to it }
                }
                // Pattern B: keys named like a bin, values that are dates.
                for (k in obj.keys()) {
                    val v = obj.opt(k)
                    if (v is String && BinType.fromServiceName(k) != BinType.OTHER) {
                        parseFlexibleDate(v)?.let { found += k to it }
                    }
                }
            }
        }

        // Fallback: HTML/text fragment (some councils return rendered markup).
        if (found.isEmpty() && body.contains('<')) {
            found += scanText(stripTags(body))
        }

        return found.map { (name, date) ->
            BinCollection(BinType.fromServiceName(name), name, date)
        }
    }

    // --- Generic JSON helpers ----------------------------------------------

    /** Depth-first walk, invoking [onObject] for every JSONObject encountered. */
    private fun walk(node: Any?, onObject: (JSONObject) -> Unit) {
        when (node) {
            is JSONObject -> {
                onObject(node)
                for (k in node.keys()) walk(node.opt(k), onObject)
            }
            is JSONArray -> for (i in 0 until node.length()) walk(node.opt(i), onObject)
        }
    }

    private fun firstStringField(obj: JSONObject, candidates: List<String>): String? {
        // Match candidate names case-insensitively.
        val lower = HashMap<String, String>()
        for (k in obj.keys()) lower[k.lowercase()] = k
        for (c in candidates) {
            val actual = lower[c.lowercase()] ?: continue
            val v = obj.opt(actual)
            val s = when (v) {
                is String -> v
                is Number, is Boolean -> v.toString()
                else -> null
            }
            if (!s.isNullOrBlank()) return s
        }
        return null
    }

    // --- Date parsing -------------------------------------------------------

    /**
     * Parse the many date shapes councils emit: ISO, ISO-datetime, dd/MM/yyyy,
     * "Wednesday 2 September 2026", "Wed 2 Sep", ".NET /Date(ms)/", or a bare
     * epoch. Year-less strings resolve to the next such date from today.
     */
    internal fun parseFlexibleDate(raw: String): LocalDate? {
        val s = raw.trim()
        if (s.isEmpty()) return null

        // .NET "/Date(1693612800000)/" or a bare epoch (seconds or millis).
        Regex("""(\d{10,13})""").find(s)?.let { m ->
            if (s.length <= 15 || s.startsWith("/Date")) {
                val n = m.value.toLong()
                val millis = if (m.value.length <= 10) n * 1000 else n
                return java.time.Instant.ofEpochMilli(millis)
                    .atZone(java.time.ZoneId.systemDefault()).toLocalDate()
            }
        }

        // ISO datetime -> keep the date portion.
        val isoDatePart = if (s.contains('T')) s.substringBefore('T') else s
        for (fmt in ISO_FORMATS) {
            runCatching { return LocalDate.parse(isoDatePart, fmt) }
        }
        for (fmt in DMY_FORMATS) {
            runCatching { return LocalDate.parse(s, fmt) }
        }
        for (fmt in NAMED_FORMATS) {
            runCatching { return LocalDate.parse(s, fmt) }
        }

        // Year-less "Wed 2 Sep" / "2 September" -> pick the next occurrence.
        parseYearless(s)?.let { return it }
        return null
    }

    private fun parseYearless(s: String): LocalDate? {
        val m = Regex(
            """(\d{1,2})\s+([A-Za-z]{3,})""",
        ).find(s) ?: return null
        val day = m.groupValues[1].toIntOrNull() ?: return null
        val monthWord = m.groupValues[2].lowercase()
        val month = (1..12).firstOrNull { mth ->
            val full = java.time.Month.of(mth)
                .getDisplayName(TextStyle.FULL, Locale.ENGLISH).lowercase()
            val short = java.time.Month.of(mth)
                .getDisplayName(TextStyle.SHORT, Locale.ENGLISH).lowercase()
            full.startsWith(monthWord) || short == monthWord || monthWord.startsWith(short)
        } ?: return null
        val today = LocalDate.now()
        return runCatching {
            var d = LocalDate.of(today.year, month, day)
            if (d.isBefore(today)) d = d.plusYears(1)
            d
        }.getOrNull()
    }

    // --- HTML fallback ------------------------------------------------------

    private fun stripTags(html: String): String =
        html.replace(Regex("(?s)<[^>]*>"), " ").replace(Regex("\\s+"), " ").trim()

    /** Pair each bin keyword with the nearest date that follows it in the text. */
    private fun scanText(text: String): List<Pair<String, LocalDate>> {
        val out = ArrayList<Pair<String, LocalDate>>()
        val dateRegex = Regex(
            """(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})""" +
                """|(\d{1,2}\s+[A-Za-z]{3,}(?:\s+\d{4})?)""" +
                """|([A-Za-z]{3,}\s+\d{1,2}(?:,?\s+\d{4})?)""",
        )
        val keywords = listOf("recycl", "organic", "garden", "fogo", "general",
            "garbage", "rubbish", "waste")
        val lower = text.lowercase()
        for (kw in keywords) {
            var idx = lower.indexOf(kw)
            while (idx >= 0) {
                val window = text.substring(idx, minOf(text.length, idx + 60))
                dateRegex.find(window)?.value?.let { ds ->
                    parseFlexibleDate(ds)?.let { out += kw to it }
                }
                idx = lower.indexOf(kw, idx + kw.length)
            }
        }
        return out
    }

    companion object {
        private val ISO_FORMATS = listOf(DateTimeFormatter.ISO_LOCAL_DATE)
        private val DMY_FORMATS = listOf(
            DateTimeFormatter.ofPattern("d/M/yyyy", Locale.ENGLISH),
            DateTimeFormatter.ofPattern("dd/MM/yyyy", Locale.ENGLISH),
            DateTimeFormatter.ofPattern("d-M-yyyy", Locale.ENGLISH),
        )
        private val NAMED_FORMATS = listOf(
            DateTimeFormatter.ofPattern("EEEE d MMMM yyyy", Locale.ENGLISH),
            DateTimeFormatter.ofPattern("EEE d MMM yyyy", Locale.ENGLISH),
            DateTimeFormatter.ofPattern("d MMMM yyyy", Locale.ENGLISH),
            DateTimeFormatter.ofPattern("d MMM yyyy", Locale.ENGLISH),
            DateTimeFormatter.ofPattern("MMMM d yyyy", Locale.ENGLISH),
            DateTimeFormatter.ofPattern("MMMM d, yyyy", Locale.ENGLISH),
        )

        fun defaultClient(): OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(15, TimeUnit.SECONDS)
            .build()
    }
}

/** Thrown on a non-2xx response so the UI can show a friendly message. */
class BinApiException(message: String) : Exception(message)
