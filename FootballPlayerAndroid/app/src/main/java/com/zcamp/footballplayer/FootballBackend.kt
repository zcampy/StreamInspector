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
private val M3U8 = Regex(
    "https?://[^\\s\\\"'<>]+\\.m3u8(?:\\?[^\\s\\\"'<>]*)?",
    RegexOption.IGNORE_CASE,
)


data class FootballMatch(
    val id: Long,
    val startsAtMs: Long,
    val competition: String,
    val home: String,
    val away: String,
    val streamUrl: String? = null,
    val state: MatchState = MatchState.Pending,
) {
    val localTime: String
        get() = DateTimeFormatter.ofPattern("dd/MM HH:mm")
            .withZone(ZoneId.systemDefault())
            .format(Instant.ofEpochMilli(startsAtMs))
}

enum class MatchState { Pending, Searching, Available, NotDirect, Error }

class FootballBackend {
    private val client = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(15, TimeUnit.SECONDS)
        .followRedirects(true)
        .build()

    private val headers = mapOf(
        "User-Agent" to "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/151 Mobile Safari/537.36",
        "Accept" to "*/*",
        "Accept-Language" to "es-ES,es;q=0.9",
        "Referer" to FOOTBALL_PAGE,
    )

    fun loadMatches(): Pair<String, List<FootballMatch>> {
        val apiBase = discoverApiBase()
        val body = get("$apiBase/api/match/live?sportType=1&language=4&stream=true")
        return apiBase to FootballProtoParser.parse(body)
    }

    fun discoverDirectStream(apiBase: String, matchId: Long): String? {
        val detailUrl = "$apiBase/api/match/detail?matchId=$matchId&sportType=1&language=4&stream=true"
        val body = get(detailUrl)
        val text = body.decodeToString().replace("\\/", "/")
        return M3U8.find(text)?.value
    }

    fun playbackHeaders(): Map<String, String> = headers + mapOf(
        "Origin" to FOOTBALL_PAGE.substringBefore("/es/")
    )

    private fun discoverApiBase(): String {
        val pageBytes = get(FOOTBALL_PAGE)
        val pageText = pageBytes.decodeToString()
        findApiBase(pageText, FOOTBALL_PAGE)?.let { return it }

        val pageUrl = FOOTBALL_PAGE.toHttpUrl()
        val scripts = SCRIPT_SRC.findAll(pageText)
            .map { it.groupValues[1] }
            .distinct()
            .take(40)
            .toList()

        var downloaded = 0
        for (src in scripts) {
            val scriptUrl = pageUrl.resolve(src)?.toString() ?: continue
            val scriptText = runCatching { get(scriptUrl).decodeToString() }.getOrNull() ?: continue
            downloaded += 1
            findApiBase(scriptText, scriptUrl)?.let { return it }
        }

        error(
            "No se encontró el prefijo dinámico de la API " +
                "(scripts detectados: ${scripts.size}, descargados: $downloaded)",
        )
    }

    private fun findApiBase(rawText: String, sourceUrl: String): String? {
        val text = rawText
            .replace("\\/", "/")
            .replace("\\u002F", "/", ignoreCase = true)
            .replace("\\u003A", ":", ignoreCase = true)

        ABSOLUTE_API_PREFIX.find(text)?.value?.let { return it.trimEnd('/') }

        val relative = RELATIVE_API_PREFIX.find(text)?.groupValues?.getOrNull(1) ?: return null
        val source = sourceUrl.toHttpUrl()
        return source.resolve(relative)?.toString()?.trimEnd('/')
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
        val parts = title.split(" vs ", limit = 2)
        return FootballMatch(
            id = id,
            startsAtMs = starts,
            competition = competition,
            home = parts.first().trim(),
            away = parts.getOrElse(1) { "" }.trim(),
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
