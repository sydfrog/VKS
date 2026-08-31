package com.binnight.app.data

/**
 * ============================================================================
 *  THE ONE FILE TO EDIT ONCE YOU CAPTURE THE REAL COUNCIL API
 * ============================================================================
 *
 * The Hills Shire "When is my bin day?" page is powered by an internal JSON
 * backend on the "Seamless" waste platform, proxied through the council's own
 * apps subdomain:
 *
 *     https://apps.thehills.nsw.gov.au/seamlessproxy/api/...
 *
 * The address search resolves a street address to a `propertyKey`, and a second
 * call returns that property's collection days.
 *
 * The endpoint SHAPES below are our best reconstruction of that API. They have
 * NOT been verified against a live capture (the council domain was unreachable
 * from the build environment). To make the app 100% correct:
 *
 *   1. Open the council page in a desktop browser, F12 -> Network tab.
 *   2. Search your address and watch the requests.
 *   3. Update [ADDRESS_SEARCH_URL], [COLLECTION_DAYS_URL] and, if needed, the
 *      candidate key-name lists below to match what you see.
 *
 * The repository parses responses DEFENSIVELY (it scans for the fields by a
 * list of likely names), so small differences are usually tolerated without any
 * code change — but pasting the real request/response makes it bullet-proof.
 */
object SeamlessConfig {

    /** Scheme + host of the council's Seamless proxy. */
    const val BASE = "https://apps.thehills.nsw.gov.au"

    /**
     * Address search / autocomplete. `{query}` is replaced with the URL-encoded
     * address the user typed (or the address reverse-geocoded from GPS).
     *
     * Expected to return JSON containing one or more property matches, each with
     * a display label and a property identifier (the `propertyKey`).
     *
     * TODO(verify): confirm path + query-param name against a live capture.
     */
    const val ADDRESS_SEARCH_URL = "$BASE/seamlessproxy/api/search?keyword={query}"

    /**
     * Collection days for a resolved property. `{propertyKey}` is replaced with
     * the identifier returned by the address search.
     *
     * TODO(verify): confirm path against a live capture. The reverse-engineered
     * form is `.../seamlessproxy/api/services/{propertyKey}.CollectionDays`.
     */
    const val COLLECTION_DAYS_URL =
        "$BASE/seamlessproxy/api/services/{propertyKey}.CollectionDays"

    /**
     * Headers sent with every request. Many council widgets only answer their
     * own front-end, so we present as a normal browser XHR coming from the page.
     * If your capture shows an extra header (e.g. an auth token), add it here.
     */
    val HEADERS: Map<String, String> = mapOf(
        "Accept" to "application/json, text/plain, */*",
        "X-Requested-With" to "XMLHttpRequest",
        "Referer" to
            "$BASE/",
        "User-Agent" to
            "Mozilla/5.0 (Linux; Android) BinNightApp/1.0",
    )

    // --- Defensive parsing hints -------------------------------------------
    // The repository walks the JSON response and matches keys case-insensitively
    // against these lists. Add the real names from your capture to the FRONT of
    // each list if the defaults don't match.

    /** JSON keys that may hold the property identifier in a search result. */
    val PROPERTY_KEY_FIELDS = listOf(
        "propertyKey", "PropertyKey", "propertyId", "PropertyId",
        "id", "Id", "geolocationid", "key", "value",
    )

    /** JSON keys that may hold the human-readable address of a search result. */
    val ADDRESS_LABEL_FIELDS = listOf(
        "address", "Address", "formattedAddress", "AddressSingleLine",
        "label", "Label", "name", "Name", "text", "displayText", "title",
    )

    /** JSON keys that may hold a bin/service name in a collection-days result. */
    val SERVICE_NAME_FIELDS = listOf(
        "name", "Name", "service", "Service", "serviceName",
        "type", "Type", "title", "Title", "bin", "description",
    )

    /** JSON keys that may hold the next collection date for a service. */
    val SERVICE_DATE_FIELDS = listOf(
        "nextDate", "NextDate", "next", "Next", "nextService", "NextService",
        "date", "Date", "collectionDate", "CollectionDate", "nextCollection",
        "nextServiceDate", "dateNext",
    )
}
