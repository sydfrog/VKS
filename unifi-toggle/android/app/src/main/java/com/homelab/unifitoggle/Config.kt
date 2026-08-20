package com.homelab.unifitoggle

/**
 * The only file you need to edit.
 *
 * BASE_URL must match the certificate on the VM. It is set to the VM address
 * 192.168.0.5. That has to be the exact address in the server certificate's
 * Subject Alternative Name, not another name that happens to reach the same VM.
 * Confirm it on the VM with:
 *   sudo openssl x509 -in /etc/unifi-toggle/tls/server-fullchain.pem -noout -ext subjectAltName
 * If that prints a different address, either rerun make-cert.sh with 192.168.0.5
 * or change BASE_URL here to whatever it prints.
 *
 * API_TOKEN is the same value as API_TOKEN in the VM env file. It is the shared
 * secret for this service only, so it is left as a placeholder here rather than
 * committed to git. Paste your real token in before building. Your UniFi
 * credentials are never here, they stay on the VM.
 */
object Config {

    /** Scheme, host and port of the middleware. No trailing slash needed. */
    const val BASE_URL: String = "https://192.168.0.5:8080"

    /** Value of API_TOKEN from /etc/unifi-toggle/unifi-toggle.env on the VM. */
    const val API_TOKEN: String = "dQM64nAh7ptVomiZhwW4XWt5BD24KzlVvEhHxUfqx58"

    /** Milliseconds to wait for the TCP and TLS handshake. */
    const val CONNECT_TIMEOUT_MS: Int = 5_000

    /** Milliseconds to wait for the response once connected. */
    const val READ_TIMEOUT_MS: Int = 10_000
}
