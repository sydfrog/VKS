# Capturing the real council API (≈2 minutes)

The app ships with a best-effort reconstruction of The Hills' bin-day API. This
guide shows how to capture the **real** requests so you can make the app exact.
Everything you learn here goes into one file:
[`app/src/main/java/com/binnight/app/data/SeamlessConfig.kt`](app/src/main/java/com/binnight/app/data/SeamlessConfig.kt).

## Steps

1. Open the council page in a **desktop** browser:
   *The Hills Shire → Waste & Recycling → When is my bin day? → Check which bin
   to put out and when.*
2. Press **F12** → **Network** tab → tick **Preserve log** → filter box: type
   `seamless` (or select the **Fetch/XHR** filter).
3. Type your address into the page's search box and pick your property so the
   bin dates appear.
4. You'll see a few requests. Grab **two** of them.

### Request A — the address search

Fires as you type / when you select the address. The name usually contains
`search`, `address`, `properties`, or `geo`.

Note down:

- **Full URL** including the query string → update `ADDRESS_SEARCH_URL`
  (use `{query}` where your typed text appears).
- In the **Response** (Response/Preview tab), find the field that holds the
  **property id** and the field that holds the **display address** → make sure
  their names are in `PROPERTY_KEY_FIELDS` and `ADDRESS_LABEL_FIELDS`.

### Request B — the collection days

Fires after you pick the address; the name likely contains `CollectionDays` or
`services`.

Note down:

- **Full URL** → update `COLLECTION_DAYS_URL` (use `{propertyKey}` where the id
  goes).
- In the **Response**, find each bin/stream's **name** and its **next date** →
  make sure those key names are in `SERVICE_NAME_FIELDS` and
  `SERVICE_DATE_FIELDS`, and check the app's date parser handles the date format
  (ISO `2026-09-02`, `dd/MM/yyyy`, or a display string like `Wed 2 Sep` are all
  already supported).

## Extra: a GPS shortcut

While the Network tab is open, watch for any request carrying **coordinates**
(`geo`, `lat`, `lng`, `coordinates`). If the widget can turn a lat/long directly
into a property, we can skip reverse-geocoding for a more accurate GPS result —
paste that request and it can be wired in.

## Fastest way to hand it over

For each of the two requests: right-click → **Copy → Copy as cURL**, and copy
the **Response** JSON. Paste both here (street number can be redacted — only the
structure matters) and the config can be finalised for you.

## Headers

If a request only works with a special header (an auth token, a specific
`Referer`, a cookie), add it to `HEADERS` in `SeamlessConfig.kt`.
