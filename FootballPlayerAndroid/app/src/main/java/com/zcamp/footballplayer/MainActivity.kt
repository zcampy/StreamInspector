package com.zcamp.footballplayer

import android.annotation.SuppressLint
import android.os.Bundle
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
        MatchWebView(
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
private fun MatchWebView(
    url: String,
    onStreamResolved: (String, Map<String, String>) -> Unit,
    onBack: () -> Unit,
) {
    val webView = remember(url) { arrayOfNulls<WebView>(1) }
    val resolved = remember(url) { AtomicBoolean(false) }

    DisposableEffect(url) {
        onDispose {
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

    Column(Modifier.fillMaxSize()) {
        Row(
            Modifier.fillMaxWidth().padding(8.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Button(onClick = onBack) { Text("Volver") }
            Text("Buscando vídeo…", style = MaterialTheme.typography.titleMedium)
        }
        AndroidView(
            factory = { context ->
                WebView(context).apply {
                    webView[0] = this
                    settings.javaScriptEnabled = true
                    settings.domStorageEnabled = true
                    settings.mediaPlaybackRequiresUserGesture = false
                    settings.loadsImagesAutomatically = true
                    settings.useWideViewPort = true
                    settings.loadWithOverviewMode = true

                    val cookieManager = CookieManager.getInstance()
                    cookieManager.setAcceptCookie(true)
                    cookieManager.setAcceptThirdPartyCookies(this, true)

                    webViewClient = object : WebViewClient() {
                        override fun shouldInterceptRequest(
                            view: WebView,
                            request: WebResourceRequest,
                        ): WebResourceResponse? {
                            val requestUrl = request.url.toString()
                            if (
                                requestUrl.contains(".m3u8", ignoreCase = true) &&
                                resolved.compareAndSet(false, true)
                            ) {
                                val headers = request.requestHeaders.toMutableMap()
                                val cookies = cookieManager.getCookie(requestUrl)
                                    ?: cookieManager.getCookie(url)
                                if (!cookies.isNullOrBlank()) headers["Cookie"] = cookies
                                if (!headers.containsKey("Referer")) headers["Referer"] = url
                                if (!headers.containsKey("User-Agent")) {
                                    headers["User-Agent"] = settings.userAgentString
                                }
                                view.post { onStreamResolved(requestUrl, headers) }
                            }
                            return null
                        }
                    }
                    webChromeClient = WebChromeClient()
                    loadUrl(url)
                }
            },
            update = { view ->
                if (view.url != url && !resolved.get()) view.loadUrl(url)
            },
            modifier = Modifier.fillMaxSize(),
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
