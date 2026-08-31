package com.binnight.app.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.binnight.app.data.BinRepository
import com.binnight.app.data.BinSchedule
import com.binnight.app.data.PropertyMatch
import com.binnight.app.location.LocationHelper
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** Where in the flow the screen currently is. */
enum class Phase { Input, Searching, ChoosingMatch, LoadingSchedule, Result }

data class UiState(
    val query: String = "",
    val phase: Phase = Phase.Input,
    val matches: List<PropertyMatch> = emptyList(),
    val schedule: BinSchedule? = null,
    val error: String? = null,
    val gpsInProgress: Boolean = false,
)

class MainViewModel(app: Application) : AndroidViewModel(app) {

    private val repo = BinRepository()
    private val location = LocationHelper(app)
    private val prefs = app.getSharedPreferences("bin_night", 0)

    private val _state = MutableStateFlow(UiState())
    val state: StateFlow<UiState> = _state.asStateFlow()

    init {
        // Reopen straight to the last property, refreshing its dates.
        loadSavedProperty()?.let { loadSchedule(it) }
    }

    fun onQueryChange(text: String) {
        _state.update { it.copy(query = text, error = null) }
    }

    /** Called after the address search box is submitted. */
    fun search() {
        val q = _state.value.query.trim()
        if (q.length < 3) {
            _state.update { it.copy(error = "Type at least a few characters of your address.") }
            return
        }
        _state.update { it.copy(phase = Phase.Searching, error = null, matches = emptyList()) }
        viewModelScope.launch {
            runCatching { repo.searchAddress(q) }
                .onSuccess { matches ->
                    when {
                        matches.isEmpty() -> _state.update {
                            it.copy(
                                phase = Phase.Input,
                                error = "No properties matched \"$q\". Try including your suburb.",
                            )
                        }
                        matches.size == 1 -> loadSchedule(matches.first())
                        else -> _state.update {
                            it.copy(phase = Phase.ChoosingMatch, matches = matches)
                        }
                    }
                }
                .onFailure { e -> fail(e) }
        }
    }

    /** User picked one of several address matches. */
    fun selectMatch(match: PropertyMatch) = loadSchedule(match)

    /**
     * GPS button. Call ONLY after a location permission has been granted.
     * Resolves the current address, fills the box, and runs the search.
     */
    fun locateViaGps() {
        _state.update { it.copy(gpsInProgress = true, error = null) }
        viewModelScope.launch {
            runCatching { location.currentAddress() }
                .onSuccess { addr ->
                    _state.update { it.copy(query = addr, gpsInProgress = false) }
                    search()
                }
                .onFailure { e ->
                    _state.update {
                        it.copy(gpsInProgress = false, error = e.message ?: "Location failed.")
                    }
                }
        }
    }

    fun onLocationPermissionDenied() {
        _state.update {
            it.copy(
                gpsInProgress = false,
                error = "Location permission is needed to find your address. You can still type it in.",
            )
        }
    }

    /** Back to the search box (e.g. "Not right? Edit address"). */
    fun editAddress() {
        _state.update { it.copy(phase = Phase.Input, matches = emptyList(), error = null) }
    }

    fun refresh() {
        loadSavedProperty()?.let { loadSchedule(it) } ?: editAddress()
    }

    private fun loadSchedule(match: PropertyMatch) {
        _state.update { it.copy(phase = Phase.LoadingSchedule, error = null, matches = emptyList()) }
        viewModelScope.launch {
            runCatching { repo.collectionDays(match) }
                .onSuccess { schedule ->
                    saveProperty(match)
                    _state.update { it.copy(phase = Phase.Result, schedule = schedule) }
                }
                .onFailure { e -> fail(e) }
        }
    }

    private fun fail(e: Throwable) {
        _state.update {
            it.copy(
                phase = if (it.schedule != null) Phase.Result else Phase.Input,
                error = e.message ?: "Something went wrong. Please try again.",
            )
        }
    }

    // --- persistence --------------------------------------------------------

    private fun saveProperty(match: PropertyMatch) {
        prefs.edit()
            .putString(KEY_PROPERTY, match.propertyKey)
            .putString(KEY_ADDRESS, match.address)
            .apply()
    }

    private fun loadSavedProperty(): PropertyMatch? {
        val key = prefs.getString(KEY_PROPERTY, null) ?: return null
        val addr = prefs.getString(KEY_ADDRESS, null) ?: return null
        return PropertyMatch(key, addr)
    }

    private companion object {
        const val KEY_PROPERTY = "property_key"
        const val KEY_ADDRESS = "property_address"
    }
}
