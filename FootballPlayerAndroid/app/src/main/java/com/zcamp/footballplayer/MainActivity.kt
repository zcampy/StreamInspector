package com.zcamp.footballplayer

import android.annotation.SuppressLint
import android.os.Bundle
import android.webkit.CookieManager
import android.webkit.JavascriptInterface
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

private class HlsBridge(
    private val webView: WebView,
    private val pageUrl: String,
    private val resolved: AtomicBoolean,
    private val onResolved: (String, Map<String, String>) -> Unit,
) {
    @JavascriptInterface
    fun report(candidate: String?) {
        val streamUrl = candidate?.trim().orEmpty()
        if (!streamUrl.startsWith("http", ignoreCase = true)) return
        if (!looksLikeHls(streamUrl)) return
        resolve(streamUrl, emptyMap())
    }

    fun resolve(streamUrl: String, requestHeaders: Map<String, String>) {
        if (!resolved.compareAndSet(false, true)) return
        val headers = requestHeaders.toMutableMap()
        val cookieManager = CookieManager.getInstance()
        val cookies = cookieManager.getCookie(streamUrl) ?: cookieManager.getCookie(pageUrl)
        if (!cookies.isNullOrBlank()) headers["Cookie"] = cookies
        headers.putIfAbsent("Referer", pageUrl)
        headers.putIfAbsent("User-Agent", webView.settings.userAgentString)
        webView.post { onResolved(streamUrl, headers) }
    }

    private fun looksLikeHls(value: String): Boolean {
        val lowered = value.lowercase()
        return ".m3u8" in lowered || "application/vnd.apple.mpegurl" in lowered ||
            "application/x-mpegurl" in lowered
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

private const val HLS_HOOK = """
(function () {
  if (window.__footballHlsHookInstalled) return;
  window.__footballHlsHookInstalled = true;

  const report = (value) => {
    try {
      const url = typeof value === 'string' ? value : (value && value.url) || '';
      if (/^https?:/i.test(url) && (/\.m3u8(?:$|[?#])/i.test(url) || /mpegurl/i.test(url))) {
        AndroidHls.report(url);
      }
    } catch (_) {}
  };

  const originalFetch = window.fetch;
  if (originalFetch) {
    window.fetch = function(input, init) {
      report(input);
      return originalFetch.apply(this, arguments).then((response) => {
        report(response && response.url);
        try {
          const type = response && response.headers && response.headers.get('content-type');
          if (type && /mpegurl/i.test(type)) report(response.url);
        } catch (_) {}
        return response;
      });
    };
  }

  const originalOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function(method, requestUrl) {
    report(requestUrl);
    this.addEventListener('load', function() {
      report(this.responseURL);
      try {
        const type = this.getResponseHeader('content-type');
        if (type && /mpegurl/i.test(type)) report(this.responseURL);
      } catch (_) {}
    });
    return originalOpen.apply(this, arguments);
  };

  const scan = () => {
    try {
      performance.getEntriesByType('resource').forEach((entry) => report(entry.name));
      document.querySelectorAll('video, source').forEach((element) => {
        report(element.currentSrc);
        report(element.src);
      });
    } catch (_) {}
  };

  new MutationObserver(scan).observe(document.documentElement || document, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ['src']
  });
  setInterval(scan, 750);
  scan();
})();
"""

@SuppressLint("SetJavaScriptEnabled", "JavascriptInterface")
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
                removeJavascriptInterface("AndroidHls")
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
                    settings.javaScriptCanOpenWindowsAutomatically = false
                    settings.setSupportMultipleWindows(false)

                    val cookieManager = CookieManager.getInstance()
                    cookieManager.setAcceptCookie(true)
                    cookieManager.setAcceptThirdPartyCookies(this, true)
                    val bridge = HlsBridge(this, url, resolved, onStreamResolved)
                    addJavascriptInterface(bridge, "AndroidHls")

                    webViewClient = object : WebViewClient() {
                        override fun shouldOverrideUrlLoading(
                            view: WebView,
                            request: WebResourceRequest,
                        ): Boolean {
                            val target = request.url.toString()
                            if (target.startsWith("http", ignoreCase = true)) {
                                view.loadUrl(target)
                                return true
                            }
                            return false
                        }

                        override fun onPageFinished(view: WebView, pageUrl: String) {
                            super.onPageFinished(view, pageUrl)
                            if (!resolved.get()) view.evaluateJavascript(HLS_HOOK, null)
                        }

                        override fun onLoadResource(view: WebView, resourceUrl: String) {
                            super.onLoadResource(view, resourceUrl)
                            if (resourceUrl.contains(".m3u8", ignoreCase = true)) {
                                bridge.resolve(resourceUrl, emptyMap())
                            }
                        }

                        override fun shouldInterceptRequest(
                            view: WebView,
                            request: WebResourceRequest,
                        ): WebResourceResponse? {
                            val requestUrl = request.url.toString()
                            if (requestUrl.contains(".m3u8", ignoreCase = true)) {
                                bridge.resolve(requestUrl, request.requestHeaders)
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
