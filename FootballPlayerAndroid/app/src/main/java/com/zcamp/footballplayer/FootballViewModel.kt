package com.zcamp.footballplayer

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext


data class FootballUiState(
    val loading: Boolean = false,
    val matches: List<FootballMatch> = emptyList(),
    val error: String? = null,
    val selectedStream: String? = null,
)

class FootballViewModel : ViewModel() {
    private val backend = FootballBackend()
    private val _state = MutableStateFlow(FootballUiState())
    val state: StateFlow<FootballUiState> = _state.asStateFlow()
    private var apiBase: String? = null

    init {
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            _state.update { it.copy(loading = true, error = null, selectedStream = null) }
            runCatching { withContext(Dispatchers.IO) { backend.loadMatches() } }
                .onSuccess { (base, matches) ->
                    apiBase = base
                    _state.value = FootballUiState(matches = matches)
                    discoverAll()
                }
                .onFailure { error ->
                    _state.update { it.copy(loading = false, error = error.message ?: "Error desconocido") }
                }
        }
    }

    fun discoverAll(limit: Int = 20) {
        val base = apiBase ?: return
        viewModelScope.launch {
            val candidates = _state.value.matches.take(limit)
            for (match in candidates) {
                updateMatch(match.id) { it.copy(state = MatchState.Searching) }
                val result = runCatching {
                    withContext(Dispatchers.IO) { backend.discoverDirectStream(base, match.id) }
                }
                result.onSuccess { stream ->
                    updateMatch(match.id) {
                        it.copy(
                            streamUrl = stream,
                            state = if (stream == null) MatchState.NotDirect else MatchState.Available,
                        )
                    }
                }.onFailure {
                    updateMatch(match.id) { current -> current.copy(state = MatchState.Error) }
                }
            }
        }
    }

    fun play(match: FootballMatch) {
        if (match.streamUrl != null) _state.update { it.copy(selectedStream = match.streamUrl) }
    }

    fun closePlayer() {
        _state.update { it.copy(selectedStream = null) }
    }

    fun playbackHeaders(): Map<String, String> = backend.playbackHeaders()

    private fun updateMatch(id: Long, transform: (FootballMatch) -> FootballMatch) {
        _state.update { state ->
            state.copy(matches = state.matches.map { if (it.id == id) transform(it) else it })
        }
    }
}
