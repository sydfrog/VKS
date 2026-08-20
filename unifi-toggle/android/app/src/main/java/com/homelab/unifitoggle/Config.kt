package com.homelab.unifitoggle

/**
 * The only file you need to edit.
 *
 * BASE_URL must match the certificate you generated on the VM. If you ran
 *   scripts/make-cert.sh 192.168.0.50
 * then the certificate names 192.168.0.50, so BASE_URL has to use exactly
 * that, not a different name or address that happens to reach the same VM.
 *
 * API_TOKEN is the same value as API_TOKEN in the VM env file. It is the
 * shared secret for this service only. Your UniFi credentials are never here,
 * they stay on the VM.
 */
object Config {

    /** Scheme, host and port of the middleware. No trailing slash needed. */
    const val BASE_URL: String = "https://192.168.0.50:8080"

    /** Value of API_TOKEN from /etc/unifi-toggle/unifi-toggle.env on the VM. */
    const val API_TOKEN: String = "paste-the-API_TOKEN-value-here"

    /** Milliseconds to wait for the TCP and TLS handshake. */
    const val CONNECT_TIMEOUT_MS: Int = 5_000

    /** Milliseconds to wait for the response once connected. */
    const val READ_TIMEOUT_MS: Int = 10_000
}
