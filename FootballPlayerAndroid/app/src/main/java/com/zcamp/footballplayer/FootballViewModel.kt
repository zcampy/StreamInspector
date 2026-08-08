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
    val selectedPageUrl: String? = null,
    val selectedStreamUrl: String? = null,
    val selectedStreamHeaders: Map<String, String> = emptyMap(),
)

class FootballViewModel : ViewModel() {
    private val backend = FootballBackend()
    private val _state = MutableStateFlow(FootballUiState())
    val state: StateFlow<FootballUiState> = _state.asStateFlow()

    init {
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            _state.update {
                it.copy(
                    loading = true,
                    error = null,
                    selectedPageUrl = null,
                    selectedStreamUrl = null,
                    selectedStreamHeaders = emptyMap(),
                )
            }
            runCatching { withContext(Dispatchers.IO) { backend.loadMatches() } }
                .onSuccess { matches ->
                    _state.value = FootballUiState(matches = matches)
                }
                .onFailure { error ->
                    _state.update {
                        it.copy(loading = false, error = error.message ?: "Error desconocido")
                    }
                }
        }
    }

    fun open(match: FootballMatch) {
        _state.update {
            it.copy(
                selectedPageUrl = match.pageUrl,
                selectedStreamUrl = null,
                selectedStreamHeaders = emptyMap(),
            )
        }
    }

    fun streamResolved(url: String, headers: Map<String, String>) {
        _state.update {
            it.copy(
                selectedPageUrl = null,
                selectedStreamUrl = url,
                selectedStreamHeaders = headers,
            )
        }
    }

    fun closePlayer() {
        _state.update {
            it.copy(
                selectedPageUrl = null,
                selectedStreamUrl = null,
                selectedStreamHeaders = emptyMap(),
            )
        }
    }

    fun closeWebView() {
        _state.update { it.copy(selectedPageUrl = null) }
    }
}
