package com.zcamp.footballplayer

import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.ByteArrayInputStream
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.concurrent.TimeUnit
import java.util.zip.GZIPInputStream

private const val FOOTBALL_PAGE = "https://jack37eo.mpcourageny9i9zzipper.my/es/football.html"
private const val FOOTBALL_ORIGIN = "https://jack37eo.mpcourageny9i9zzipper.my"
private const val API_ORIGIN = "https://apis-data-defra10.tcdru136ovur.ru"
private val ABSOLUTE_API_PREFIX = Regex(
    "https?://[^\\\"'\\s<>]+/sfver[^/\\\"'\\s<>]+",
    RegexOption.IGNORE_CASE,
)
private val RELATIVE_API_PREFIX = Regex(
    "(?:^|[\\\"'(=:])(/sfver[^/\\\"'\\s<>]+)",
    RegexOption.IGNORE_CASE,
)
private val SCRIPT_SRC = Regex(
    "<script[^>]+src\\s*=\\s*[\\\"']([^\\\"']+)[\\\"']",
    RegexOption.IGNORE_CASE,
)

data class FootballMatch(
    val id: Long,
    val startsAtMs: Long,
    val competition: String,
    val home: String,
    val away: String,
    val matchSlug: String,
    val competitionSlug: String,
) {
    val localTime: String
        get() = DateTimeFormatter.ofPattern("dd/MM HH:mm")
            .withZone(ZoneId.systemDefault())
            .format(Instant.ofEpochMilli(startsAtMs))

    val pageUrl: String
        get() {
            val competitionPath = competitionSlug.ifBlank { slugify(competition) }
            val matchPath = matchSlug.ifBlank { slugify("$home vs $away") }
            return "$FOOTBALL_ORIGIN/es/football/$competitionPath-$id/$matchPath.html" +
                "?icg=RVM&ilang=es"
        }

    private fun slugify(value: String): String = value
        .lowercase()
        .replace(Regex("[^a-z0-9]+"), "-")
        .trim('-')
}

class FootballBackend {
    private val client = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(15, TimeUnit.SECONDS)
        .followRedirects(true)
        .build()

    private val headers = mapOf(
        "User-Agent" to "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/151 Mobile Safari/537.36",
        "Accept" to "application/json, text/plain, */*",
        "Accept-Language" to "es-ES,es;q=0.9",
        "Origin" to FOOTBALL_ORIGIN,
        "Referer" to "$FOOTBALL_ORIGIN/",
    )

    fun loadMatches(): List<FootballMatch> {
        val errors = mutableListOf<String>()
        for (apiBase in discoverApiBases()) {
            val result = runCatching {
                val body = get("$apiBase/api/match/live?sportType=1&language=4&stream=true")
                FootballProtoParser.parse(body)
            }
            result.onSuccess { matches ->
                if (matches.isNotEmpty()) return matches
                errors += "$apiBase: respuesta sin partidos"
            }.onFailure { error ->
                errors += "$apiBase: ${error.message ?: error::class.simpleName}"
            }
        }
        error("No se pudo cargar el calendario. " + errors.take(3).joinToString(" | "))
    }

    private fun discoverApiBases(): List<String> {
        val bases = mutableListOf<String>()
        val pageText = runCatching { get(FOOTBALL_PAGE).decodeToString() }.getOrNull()
        if (pageText != null) {
            findApiBase(pageText)?.let(bases::add)
            val pageUrl = FOOTBALL_PAGE.toHttpUrl()
            val scripts = SCRIPT_SRC.findAll(pageText)
                .map { it.groupValues[1] }
                .distinct()
                .take(40)
                .toList()
            for (src in scripts) {
                val scriptUrl = pageUrl.resolve(src)?.toString() ?: continue
                val scriptText = runCatching { get(scriptUrl).decodeToString() }.getOrNull() ?: continue
                findApiBase(scriptText)?.let { base -> if (base !in bases) bases += base }
            }
        }
        if (API_ORIGIN !in bases) bases += API_ORIGIN
        return bases
    }

    private fun findApiBase(rawText: String): String? {
        val text = rawText
            .replace("\\/", "/")
            .replace("\\u002F", "/", ignoreCase = true)
            .replace("\\u003A", ":", ignoreCase = true)
        ABSOLUTE_API_PREFIX.find(text)?.value?.let { return it.trimEnd('/') }
        val relative = RELATIVE_API_PREFIX.find(text)?.groupValues?.getOrNull(1) ?: return null
        return API_ORIGIN + relative.trimEnd('/')
    }

    private fun get(url: String): ByteArray {
        val builder = Request.Builder().url(url)
        headers.forEach { (name, value) -> builder.header(name, value) }
        client.newCall(builder.build()).execute().use { response ->
            if (!response.isSuccessful) error("HTTP ${response.code} en $url")
            val raw = response.body.bytes()
            return if (response.header("Content-Encoding")?.contains("gzip", true) == true) {
                GZIPInputStream(ByteArrayInputStream(raw)).readBytes()
            } else raw
        }
    }
}

private object FootballProtoParser {
    fun parse(data: ByteArray): List<FootballMatch> {
        val root = messages(data, 10).firstOrNull() ?: return emptyList()
        return messages(root, 1).mapNotNull(::parseEvent).sortedBy { it.startsAtMs }
    }

    private fun parseEvent(data: ByteArray): FootballMatch? {
        val id = firstInt(data, 1)
        val starts = firstInt(data, 3)
        val competition = messages(data, 10).firstOrNull()?.let(::localizedText).orEmpty()
        val title = messages(data, 30).firstNotNullOfOrNull {
            utf8(it, 2).takeIf(String::isNotBlank)
        }.orEmpty()
        if (id == 0L || starts == 0L || title.isBlank()) return null

        val metadata = messages(data, 150).firstOrNull() ?: byteArrayOf()
        val matchSlug = utf8(metadata, 20)
        val competitionSlug = utf8(metadata, 21)
        val parts = title.split(" vs ", limit = 2)
        return FootballMatch(
            id = id,
            startsAtMs = starts,
            competition = competition,
            home = parts.first().trim(),
            away = parts.getOrElse(1) { "" }.trim(),
            matchSlug = matchSlug,
            competitionSlug = competitionSlug,
        )
    }

    private fun localizedText(data: ByteArray): String =
        messages(data, 3).firstNotNullOfOrNull {
            utf8(it, 2).takeIf(String::isNotBlank)
        }.orEmpty()

    private fun utf8(data: ByteArray, number: Int): String =
        messages(data, number).firstNotNullOfOrNull {
            runCatching { it.toString(Charsets.UTF_8) }.getOrNull()
        }.orEmpty()

    private fun firstInt(data: ByteArray, number: Int): Long =
        fields(data).firstOrNull { it.number == number && it.wire == 0 }?.integer ?: 0L

    private fun messages(data: ByteArray, number: Int): List<ByteArray> =
        fields(data).filter { it.number == number && it.wire == 2 }.mapNotNull { it.bytes }

    private data class Field(
        val number: Int,
        val wire: Int,
        val integer: Long? = null,
        val bytes: ByteArray? = null,
    )

    private fun fields(data: ByteArray): List<Field> {
        val result = mutableListOf<Field>()
        var offset = 0
        while (offset < data.size) {
            val (key, afterKey) = varint(data, offset)
            offset = afterKey
            val number = (key ushr 3).toInt()
            val wire = (key and 7).toInt()
            when (wire) {
                0 -> {
                    val (value, next) = varint(data, offset)
                    offset = next
                    result += Field(number, wire, integer = value)
                }
                1 -> offset += 8
                2 -> {
                    val (length, next) = varint(data, offset)
                    offset = next
                    val end = offset + length.toInt()
                    require(end <= data.size) { "Campo protobuf truncado" }
                    result += Field(number, wire, bytes = data.copyOfRange(offset, end))
                    offset = end
                }
                5 -> offset += 4
                else -> error("Wire type protobuf no soportado: $wire")
            }
            require(offset <= data.size) { "Respuesta protobuf truncada" }
        }
        return result
    }

    private fun varint(data: ByteArray, start: Int): Pair<Long, Int> {
        var value = 0L
        var shift = 0
        var offset = start
        while (offset < data.size && shift <= 63) {
            val byte = data[offset++].toInt() and 0xff
            value = value or ((byte and 0x7f).toLong() shl shift)
            if (byte < 0x80) return value to offset
            shift += 7
        }
        error("Varint protobuf inválido")
    }
}
