package com.homelab.unifitoggle

import android.util.Log
import org.json.JSONException
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.SocketTimeoutException
import java.net.URL
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import javax.net.ssl.SSLException

/** Outcome of one call, ready to be shown in the widget and in a toast. */
data class ToggleResult(
    val ok: Boolean,
    val enabled: Boolean?,
    val policyName: String?,
    val message: String,
) {
    /** Short line for the widget. Keeps the last known state visible.
     *
     * On failure the reason goes here, not only in the toast. Android suppresses
     * background toasts on some versions, and the widget updates from a broadcast
     * receiver, so the toast is exactly the case Android may drop. The status
     * line is the one place the reason is guaranteed to be seen.
     */
    fun statusLine(): String {
        val stamp = SimpleDateFormat("HH:mm", Locale.getDefault()).format(Date())
        if (!ok) return "$stamp  $message"
        // The policy blocks the kids' internet, so enabled means Blocked.
        return when (enabled) {
            true -> "Blocked as of $stamp"
            false -> "Allowed as of $stamp"
            else -> "Unknown at $stamp"
        }
    }
}

/**
 * Talks to the middleware. One request per call, no session, no retry.
 *
 * TLS trust comes from res/xml/network_security_config.xml, which pins the CA
 * you generated on the VM. There is deliberately no custom TrustManager here,
 * because a hand rolled one is the usual way apps end up trusting everything.
 */
object ToggleClient {

    private const val TAG = "UniFiToggle"

    fun status(): ToggleResult = call("GET", "/status", "Status")

    fun enable(): ToggleResult = call("POST", "/enable", "Enable")

    fun disable(): ToggleResult = call("POST", "/disable", "Disable")

    /**
     * Flip the policy to the opposite of its current state.
     *
     * Reads the current state first, then calls the opposite. A home screen
     * widget cannot capture a drag, so the switch widget turns a tap into this.
     * Two requests rather than one, which is fine on a LAN for a single user.
     */
    fun toggle(): ToggleResult {
        val current = status()
        if (!current.ok || current.enabled == null) return current
        return if (current.enabled) disable() else enable()
    }

    private fun call(method: String, path: String, label: String): ToggleResult {
        val target = Config.BASE_URL.trimEnd('/') + path
        var conn: HttpURLConnection? = null
        return try {
            conn = (URL(target).openConnection() as HttpURLConnection).apply {
                requestMethod = method
                connectTimeout = Config.CONNECT_TIMEOUT_MS
                readTimeout = Config.READ_TIMEOUT_MS
                useCaches = false
                instanceFollowRedirects = false
                setRequestProperty("Authorization", "Bearer ${Config.API_TOKEN}")
                setRequestProperty("Accept", "application/json")
                if (method == "POST") {
                    doOutput = true
                    setRequestProperty("Content-Type", "application/json")
                    setFixedLengthStreamingMode(EMPTY_BODY.size)
                }
            }
            if (method == "POST") {
                conn.outputStream.use { it.write(EMPTY_BODY) }
            }

            val code = conn.responseCode
            val stream = if (code in 200..299) conn.inputStream else conn.errorStream
            val body = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
            interpret(code, body, label)
        } catch (e: SSLException) {
            Log.w(TAG, "TLS failure talking to $target", e)
            failure(
                "TLS failed. Put the VM's ca.crt in res/raw/unifi_toggle_ca.pem " +
                    "and check BASE_URL matches the certificate."
            )
        } catch (e: SocketTimeoutException) {
            Log.w(TAG, "Timeout talking to $target", e)
            failure("Timed out. Is the VM awake and on the same network?")
        } catch (e: IOException) {
            Log.w(TAG, "Cannot reach $target", e)
            failure("Cannot reach ${Config.BASE_URL}")
        } catch (e: IllegalArgumentException) {
            Log.w(TAG, "Bad BASE_URL $target", e)
            failure("BASE_URL in Config.kt is not a valid URL")
        } finally {
            conn?.disconnect()
        }
    }

    private fun interpret(code: Int, body: String, label: String): ToggleResult {
        val json = parse(body)
        return when (code) {
            in 200..299 -> {
                val name = json?.optString("name").orNullIfBlank()
                val enabled = json?.optBoolean("enabled")
                val changed = json?.optBoolean("changed") ?: false
                // enabled means the block policy is on, so the kids are Blocked.
                val state = if (enabled == true) "Blocked" else "Allowed"
                val message = when {
                    label == "Status" -> "Kids internet is $state"
                    changed -> "Kids internet is now $state"
                    else -> "Kids internet was already $state"
                }
                ToggleResult(ok = true, enabled = enabled, policyName = name, message = message)
            }
            401 -> failure("Rejected: no bearer token was sent")
            403 -> failure("Rejected: API_TOKEN in Config.kt does not match the VM")
            404 -> failure(json.errorText() ?: "Policy not found on the console")
            409 -> failure(json.errorText() ?: "That policy cannot be edited")
            502 -> failure(json.errorText() ?: "The VM could not reach the UniFi console")
            else -> failure(json.errorText() ?: "$label failed with HTTP $code")
        }
    }

    private fun parse(body: String): JSONObject? = try {
        if (body.isBlank()) null else JSONObject(body)
    } catch (e: JSONException) {
        Log.w(TAG, "Response was not JSON: ${body.take(200)}", e)
        null
    }

    /** The middleware returns {"error": "...", "hint": "..."} on failure. */
    private fun JSONObject?.errorText(): String? {
        val error = this?.optString("error").orNullIfBlank() ?: return null
        val hint = this?.optString("hint").orNullIfBlank()
        return if (hint == null) error else "$error ($hint)"
    }

    private fun String?.orNullIfBlank(): String? =
        if (this.isNullOrBlank() || this == "null") null else this

    private fun failure(message: String) =
        ToggleResult(ok = false, enabled = null, policyName = null, message = message)

    private val EMPTY_BODY = "{}".toByteArray()
}
