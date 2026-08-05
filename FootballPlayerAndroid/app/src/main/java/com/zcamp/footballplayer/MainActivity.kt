package com.zcamp.footballplayer

import android.annotation.SuppressLint
import android.os.Bundle
import android.webkit.CookieManager
import android.webkit.WebChromeClient
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
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel

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
    val pageUrl = state.selectedPageUrl
    if (pageUrl != null) {
        MatchWebView(pageUrl, vm::closeWebView)
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
private fun MatchWebView(url: String, onBack: () -> Unit) {
    val webView = remember(url) { arrayOfNulls<WebView>(1) }
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
            Text("Reproductor web", style = MaterialTheme.typography.titleMedium)
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
                    CookieManager.getInstance().setAcceptCookie(true)
                    CookieManager.getInstance().setAcceptThirdPartyCookies(this, true)
                    webViewClient = WebViewClient()
                    webChromeClient = WebChromeClient()
                    loadUrl(url)
                }
            },
            update = { view ->
                if (view.url != url) view.loadUrl(url)
            },
            modifier = Modifier.fillMaxSize(),
        )
    }
}
