package com.binnight.app.location

import android.annotation.SuppressLint
import android.content.Context
import android.location.Address
import android.location.Geocoder
import android.os.Build
import com.google.android.gms.location.CurrentLocationRequest
import com.google.android.gms.location.LocationServices
import com.google.android.gms.location.Priority
import kotlinx.coroutines.suspendCancellableCoroutine
import java.util.Locale
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

/**
 * Wraps GPS + reverse geocoding: get the device's current location, then turn
 * it into a street-address string the council search understands.
 *
 * Caller MUST have been granted a location permission before calling
 * [currentAddress] — the ViewModel handles the runtime request.
 */
class LocationHelper(private val context: Context) {

    /** Get current location and reverse-geocode it to an address string. */
    @SuppressLint("MissingPermission") // permission is checked by the caller
    suspend fun currentAddress(): String {
        val location = awaitCurrentLocation()
            ?: throw LocationException("Couldn't get a GPS fix. Try again outdoors or enter your address manually.")
        val address = reverseGeocode(location.latitude, location.longitude)
            ?: throw LocationException("Found your location but couldn't turn it into an address. Enter it manually instead.")
        return address
    }

    @SuppressLint("MissingPermission")
    private suspend fun awaitCurrentLocation() =
        suspendCancellableCoroutine<android.location.Location?> { cont ->
            val client = LocationServices.getFusedLocationProviderClient(context)
            val request = CurrentLocationRequest.Builder()
                .setPriority(Priority.PRIORITY_HIGH_ACCURACY)
                .setMaxUpdateAgeMillis(60_000) // a recent cached fix is fine
                .build()
            client.getCurrentLocation(request, null)
                .addOnSuccessListener { cont.resume(it) }
                .addOnFailureListener { cont.resumeWithException(it) }
        }

    private suspend fun reverseGeocode(lat: Double, lon: Double): String? {
        val geocoder = Geocoder(context, Locale.ENGLISH)
        val results = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            suspendCancellableCoroutine<List<Address>> { cont ->
                geocoder.getFromLocation(lat, lon, 1, object : Geocoder.GeocodeListener {
                    override fun onGeocode(addresses: MutableList<Address>) {
                        if (cont.isActive) cont.resume(addresses)
                    }
                    override fun onError(errorMessage: String?) {
                        if (cont.isActive) cont.resume(emptyList())
                    }
                })
            }
        } else {
            @Suppress("DEPRECATION")
            runCatching { geocoder.getFromLocation(lat, lon, 1) }.getOrNull().orEmpty()
        }
        return results.firstOrNull()?.let(::formatAddress)
    }

    /** Prefer "12 Smith St, Baulkham Hills NSW 2153" style the search expects. */
    private fun formatAddress(a: Address): String? {
        val street = listOfNotNull(a.subThoroughfare, a.thoroughfare)
            .joinToString(" ").trim()
        val tail = listOfNotNull(
            a.locality ?: a.subAdminArea,
            a.adminArea?.let(::stateAbbrev),
            a.postalCode,
        ).joinToString(" ").trim()

        val joined = listOf(street, tail)
            .filter { it.isNotBlank() }
            .joinToString(", ")

        if (joined.isNotBlank()) return joined

        // Last resort: whatever single-line address the geocoder gave us.
        return (0..a.maxAddressLineIndex)
            .joinToString(", ") { a.getAddressLine(it) }
            .ifBlank { null }
    }

    private fun stateAbbrev(state: String): String = when (state.lowercase()) {
        "new south wales" -> "NSW"
        else -> state
    }
}

class LocationException(message: String) : Exception(message)
