# Bin Night? 🗑️♻️🌿

A tiny Android app that tells you **which bins to put out this week** for a
property in **The Hills Shire (NSW)** — by address, or by tapping **Use my
location**.

<p>
  <img alt="Kotlin" src="https://img.shields.io/badge/Kotlin-1.9.24-7F52FF">
  <img alt="Jetpack Compose" src="https://img.shields.io/badge/UI-Jetpack%20Compose-4285F4">
  <img alt="minSdk 26" src="https://img.shields.io/badge/minSdk-26-3DDC84">
</p>

## What it does

- Enter your address **or** tap **📍 Use my location** (GPS → reverse-geocoded
  to a street address).
- Resolves the address to the council's property record and fetches its
  collection days.
- Shows a big card: the **next collection date** and **which bins** go out —
  General waste, Recycling, and Garden/FOGO — plus what's coming up after that.
- Remembers your property, so it opens straight to your bins next time.

## ⚠️ Important: the council API needs one verification step

The Hills "When is my bin day?" page is backed by an internal JSON API on the
"Seamless" waste platform:

```
https://apps.thehills.nsw.gov.au/seamlessproxy/api/...
```

It is **undocumented** (the widget's private backend, not a public API). The
exact request paths and JSON field names in this app are a **best-effort
reconstruction that has not been verified against a live capture** — the council
domain was unreachable from the build environment.

The app parses responses **defensively** (it matches fields by a list of likely
names and handles many date formats), so it may well work as-is. To make it
exact, spend ~2 minutes capturing the real calls — see
[`CAPTURE-THE-API.md`](CAPTURE-THE-API.md). Everything you'd change lives in a
**single file**: [`SeamlessConfig.kt`](app/src/main/java/com/binnight/app/data/SeamlessConfig.kt).

## Build & run

You need Android Studio (Koala/2024.1+) or the Android SDK + this repo's Gradle
wrapper.

```bash
cd bin-night-android
./gradlew assembleDebug        # build the APK
# or open the folder in Android Studio and press Run
```

The debug APK lands in `app/build/outputs/apk/debug/`.

> The Gradle wrapper is committed, but you must supply an Android SDK. In
> Android Studio this is automatic; on CI set `sdk.dir` in `local.properties`
> or the `ANDROID_HOME` env var.

## How it works

```
Address text ─┐
              ├─► BinRepository.searchAddress()  ─► propertyKey
GPS ─► Geocoder ┘                                     │
                                                      ▼
                       BinRepository.collectionDays(propertyKey)
                                                      │
                                     defensive JSON/date parsing
                                                      ▼
                              BinSchedule ─► Compose UI (next bins)
```

| Layer | File |
|-------|------|
| API config (edit me!) | `data/SeamlessConfig.kt` |
| Networking + parsing | `data/BinRepository.kt` |
| Models | `data/Models.kt` |
| GPS + reverse geocode | `location/LocationHelper.kt` |
| State | `ui/MainViewModel.kt` |
| Screen | `ui/MainScreen.kt` |

## Accuracy note

Bin days in The Hills vary property-by-property, so GPS resolves to a specific
house. If reverse-geocoding lands on a neighbour, the result screen has a
**"Not right? Edit address"** button to correct it in one tap.

## Scope

Deliberately minimal: **show this week's bins.** Reminders, a home-screen
widget, and a full calendar view are natural next steps but are not built yet.

*Not affiliated with The Hills Shire Council. Uses the council's public website
data on your behalf; check the site's terms before redistributing.*
