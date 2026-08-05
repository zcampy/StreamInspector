package com.zcamp.footballplayer

import android.os.Bundle
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
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
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

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            MaterialTheme {
                FootballApp()
            }
        }
    }
}

@Composable
private fun FootballApp(vm: FootballViewModel = viewModel()) {
    val state by vm.state.collectAsStateWithLifecycle()
    val stream = state.selectedStream
    if (stream != null) {
        PlayerScreen(stream, vm.playbackHeaders(), vm::closePlayer)
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

            else -> LazyColumn(
                Modifier.fillMaxSize().padding(padding),
            ) {
                items(state.matches, key = FootballMatch::id) { match ->
                    MatchRow(match, onPlay = { vm.play(match) })
                }
            }
        }
    }
}

@Composable
private fun MatchRow(match: FootballMatch, onPlay: () -> Unit) {
    val available = match.state == MatchState.Available
    Column(
        Modifier
            .fillMaxWidth()
            .clickable(enabled = available, onClick = onPlay)
            .padding(horizontal = 16.dp, vertical = 12.dp),
    ) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text(match.localTime, style = MaterialTheme.typography.labelLarge)
            Text(
                when (match.state) {
                    MatchState.Pending -> "Pendiente"
                    MatchState.Searching -> "Buscando…"
                    MatchState.Available -> "Disponible"
                    MatchState.NotDirect -> "No directo"
                    MatchState.Error -> "Error"
                },
                style = MaterialTheme.typography.labelLarge,
            )
        }
        Spacer(Modifier.height(4.dp))
        Text("${match.home} vs ${match.away}", style = MaterialTheme.typography.titleMedium)
        if (match.competition.isNotBlank()) {
            Text(match.competition, style = MaterialTheme.typography.bodyMedium)
        }
        if (available) {
            Spacer(Modifier.height(8.dp))
            Button(onClick = onPlay) { Text("Reproducir") }
        }
    }
}

@Composable
private fun PlayerScreen(url: String, headers: Map<String, String>, onBack: () -> Unit) {
    val context = LocalContext.current
    val player = ExoPlayer.Builder(context).build()
    DisposableEffect(url) {
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
