package com.zcamp.footballplayer

import android.annotation.SuppressLint
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.webkit.CookieManager
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.media3.common.MediaItem
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.hls.HlsMediaSource
import androidx.media3.ui.PlayerView
import java.util.concurrent.atomic.AtomicBoolean

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent { MaterialTheme { FootballApp() } }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun FootballApp(vm: FootballViewModel = viewModel()) {
    val state by vm.state.collectAsStateWithLifecycle()
    val streamUrl = state.selectedStreamUrl
    if (streamUrl != null) {
        PlayerScreen(streamUrl, state.selectedStreamHeaders, vm::closePlayer)
        return
    }

    val pageUrl = state.selectedPageUrl
    if (pageUrl != null) {
        HiddenMatchResolver(
            url = pageUrl,
            onStreamResolved = vm::streamResolved,
            onBack = vm::closeWebView,
        )
        return
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Partidos") },
                actions = {
                    Button(onClick = vm::refresh, enabled = !state.loading) {
                        Text("Actualizar")
                    }
                },
            )
        },
    ) { padding ->
        when {
            state.loading && state.matches.isEmpty() -> Box(
                Modifier.fillMaxSize().padding(padding),
                contentAlignment = Alignment.Center,
            ) { CircularProgressIndicator() }

            state.error != null -> Column(
                Modifier.fillMaxSize().padding(padding).padding(20.dp),
                verticalArrangement = Arrangement.Center,
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text("No se pudieron cargar los partidos")
                Spacer(Modifier.height(8.dp))
                Text(state.error ?: "Error")
                Spacer(Modifier.height(16.dp))
                Button(onClick = vm::refresh) { Text("Reintentar") }
            }

            else -> LazyColumn(Modifier.fillMaxSize().padding(padding)) {
                items(state.matches, key = FootballMatch::id) { match ->
                    MatchRow(match, onOpen = { vm.open(match) })
                }
            }
        }
    }
}

@Composable
private fun MatchRow(match: FootballMatch, onOpen: () -> Unit) {
    Column(
        Modifier
            .fillMaxWidth()
            .clickable(onClick = onOpen)
            .padding(horizontal = 16.dp, vertical = 12.dp),
    ) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text(match.localTime, style = MaterialTheme.typography.labelLarge)
            Text("Abrir", style = MaterialTheme.typography.labelLarge)
        }
        Spacer(Modifier.height(4.dp))
        Text("${match.home} vs ${match.away}", style = MaterialTheme.typography.titleMedium)
        if (match.competition.isNotBlank()) {
            Text(match.competition, style = MaterialTheme.typography.bodyMedium)
        }
        Spacer(Modifier.height(8.dp))
        Button(onClick = onOpen) { Text("Ver partido") }
    }
}

@SuppressLint("SetJavaScriptEnabled")
@Composable
private fun HiddenMatchResolver(
    url: String,
    onStreamResolved: (String, Map<String, String>) -> Unit,
    onBack: () -> Unit,
) {
    val webView = remember(url) { arrayOfNulls<WebView>(1) }
    val resolved = remember(url) { AtomicBoolean(false) }
    val handler = remember(url) { Handler(Looper.getMainLooper()) }

    DisposableEffect(url) {
        onDispose {
            handler.removeCallbacksAndMessages(null)
            webView[0]?.apply {
                stopLoading()
                loadUrl("about:blank")
                clearHistory()
                removeAllViews()
                destroy()
            }
            webView[0] = null
        }
    }

    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            CircularProgressIndicator()
            Spacer(Modifier.height(16.dp))
            Text("Obteniendo vídeo…", style = MaterialTheme.typography.titleMedium)
            Spacer(Modifier.height(8.dp))
            Text("La página se está procesando en segundo plano")
            Spacer(Modifier.height(20.dp))
            Button(onClick = onBack) { Text("Cancelar") }
        }

        AndroidView(
            factory = { context ->
                WebView(context).apply {
                    webView[0] = this
                    alpha = 0.01f
                    settings.javaScriptEnabled = true
                    settings.domStorageEnabled = true
                    settings.mediaPlaybackRequiresUserGesture = false
                    settings.loadsImagesAutomatically = true
                    settings.useWideViewPort = true
                    settings.loadWithOverviewMode = true

                    val cookieManager = CookieManager.getInstance()
                    cookieManager.setAcceptCookie(true)
                    cookieManager.setAcceptThirdPartyCookies(this, true)

                    fun resolve(requestUrl: String, requestHeaders: Map<String, String>) {
                        if (!requestUrl.contains(".m3u8", ignoreCase = true)) return
                        if (!resolved.compareAndSet(false, true)) return
                        val headers = requestHeaders.toMutableMap()
                        val cookies = cookieManager.getCookie(requestUrl)
                            ?: cookieManager.getCookie(url)
                        if (!cookies.isNullOrBlank()) headers["Cookie"] = cookies
                        headers.putIfAbsent("Referer", url)
                        headers.putIfAbsent("User-Agent", settings.userAgentString)
                        post { onStreamResolved(requestUrl, headers) }
                    }

                    fun triggerPlayback(attempt: Int = 0) {
                        if (resolved.get() || attempt >= 30) return
                        val script = """
                            (function() {
                                try {
                                    document.querySelectorAll('video').forEach(function(v) {
                                        v.muted = true;
                                        v.autoplay = true;
                                        var p = v.play();
                                        if (p && p.catch) p.catch(function(){});
                                    });
                                    var selectors = [
                                        'button[aria-label*=play i]',
                                        '[class*=play i]',
                                        '[id*=play i]',
                                        '.vjs-big-play-button',
                                        '.jw-icon-playback',
                                        '.plyr__control--overlaid'
                                    ];
                                    selectors.forEach(function(selector) {
                                        document.querySelectorAll(selector).forEach(function(el) {
                                            try { el.click(); } catch (e) {}
                                        });
                                    });
                                } catch (e) {}
                            })();
                        """.trimIndent()
                        evaluateJavascript(script, null)
                        handler.postDelayed({ triggerPlayback(attempt + 1) }, 1000L)
                    }

                    webViewClient = object : WebViewClient() {
                        override fun shouldOverrideUrlLoading(
                            view: WebView,
                            request: WebResourceRequest,
                        ): Boolean {
                            val target = request.url.toString()
                            return if (target.startsWith("http://") || target.startsWith("https://")) {
                                view.loadUrl(target)
                                true
                            } else {
                                false
                            }
                        }

                        override fun shouldInterceptRequest(
                            view: WebView,
                            request: WebResourceRequest,
                        ): WebResourceResponse? {
                            resolve(request.url.toString(), request.requestHeaders)
                            return null
                        }

                        override fun onLoadResource(view: WebView, resourceUrl: String) {
                            resolve(resourceUrl, emptyMap())
                        }

                        override fun onPageFinished(view: WebView, finishedUrl: String) {
                            triggerPlayback()
                        }
                    }
                    webChromeClient = WebChromeClient()
                    loadUrl(url)
                }
            },
            update = { view ->
                if (view.url != url && !resolved.get()) view.loadUrl(url)
            },
            modifier = Modifier.size(1.dp),
        )
    }
}

@Composable
private fun PlayerScreen(
    url: String,
    headers: Map<String, String>,
    onBack: () -> Unit,
) {
    val context = LocalContext.current
    val player = remember(url) { ExoPlayer.Builder(context).build() }

    DisposableEffect(url, player) {
        val dataSource = DefaultHttpDataSource.Factory()
            .setUserAgent(headers["User-Agent"] ?: "FootballPlayer")
            .setDefaultRequestProperties(headers)
        val source = HlsMediaSource.Factory(dataSource)
            .createMediaSource(MediaItem.fromUri(url))
        player.setMediaSource(source)
        player.prepare()
        player.playWhenReady = true
        onDispose { player.release() }
    }

    Column(Modifier.fillMaxSize()) {
        Button(onClick = onBack, modifier = Modifier.padding(12.dp)) { Text("Volver") }
        AndroidView(
            factory = { PlayerView(it).apply { this.player = player } },
            modifier = Modifier.fillMaxSize(),
        )
    }
}
