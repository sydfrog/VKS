# Part 2: build and sideload the widget

Do not start this until `scripts/smoke-test.sh` passes on the VM and you have
watched the switch move in the UniFi UI.

Screen labels below match Android Studio Ladybug and Meerkat. If your version
words something slightly differently, the menu path is in the same place.

## What the app is

Three Kotlin files and some layout. There is no launcher activity and no
settings screen, on purpose. The app is a widget and nothing else, so it will
not appear in your app drawer. You will find it in the widget picker.

## 1. Install Android Studio

Download it from `https://developer.android.com/studio` and install it. On first
launch the **Android Studio Setup Wizard** appears. Accept the standard setup and
let it download the SDK. That is the only SDK work you need to do by hand.

## 2. Copy the CA certificate to your workstation

From your workstation, not the VM:

```bash
scp <you>@<vm-ip>:/etc/unifi-toggle/tls/ca.crt ./ca.crt
```

If scp is awkward, print it on the VM and copy the text:

```bash
sudo cat /etc/unifi-toggle/tls/ca.crt
```

It starts with `-----BEGIN CERTIFICATE-----` and ends with
`-----END CERTIFICATE-----`. Copy all of it including both of those lines.

## 3. Open the project

1. Start Android Studio. On the **Welcome to Android Studio** screen click **Open**.
   If a previous project opens instead, use **File**, then **Open**.
2. Navigate to the `unifi-toggle/android` folder inside this repository. Select
   the `android` folder itself, not `app` and not the repository root. Click **OK**.
3. A dialog titled **Trust and Open Project?** appears. Click **Trust Project**.
4. Android Studio starts a Gradle sync. The status bar at the bottom reads
   **Gradle: Build Running** and then **Gradle sync finished**. The first sync
   downloads Gradle 8.9 and the Android Gradle Plugin, so it takes a few minutes.
5. If a banner appears at the top of the editor saying an SDK is missing, click
   the **Install missing SDK package(s)** link in that banner, accept the licence,
   and click **Next** and then **Finish**. The sync re-runs by itself.

## 4. Put in your two values

In the **Project** panel on the left, make sure the dropdown at its top says
**Android**, then expand **app**, then **kotlin+java**, then
**com.homelab.unifitoggle**. Double click **Config.kt**.

Change exactly two lines:

```kotlin
const val BASE_URL: String = "https://192.168.0.50:8080"
const val API_TOKEN: String = "paste-the-API_TOKEN-value-here"
```

* `BASE_URL` must use the same address you passed to `make-cert.sh`. If you ran
  `make-cert.sh 192.168.0.50` then it has to be `https://192.168.0.50:8080`.
  A different name that reaches the same VM will fail the certificate check.
* `API_TOKEN` is the value of `API_TOKEN` from
  `/etc/unifi-toggle/unifi-toggle.env`, character for character.

This is the only file to edit. The base URL and the token live nowhere else.

## 5. Put in your CA certificate

In the **Project** panel, expand **app**, then **res**, then **raw**. Double click
**unifi_toggle_ca.pem**.

The file that ships here is a placeholder whose subject reads
`REPLACE THIS FILE with ca.crt from your VM`. Select all of its contents and
replace them with the contents of the `ca.crt` you copied in step 2.

Save with **Ctrl+S**, or **Cmd+S** on a Mac.

If you skip this, the widget builds and installs fine and then reports
`TLS failed` on every tap, because it does not trust your VM's certificate.

## 6. Build the APK

Use the menu **Build**, then **Build App Bundle(s) / APK(s)**, then **Build APK(s)**.

Do not use the green Run arrow. This app has no launcher activity, so a run
configuration set to launch the default activity fails with
`Default Activity not found`. Building the APK is the right path for sideloading.

When the build finishes a notification appears in the bottom right:
**APK(s) generated successfully for 1 module**. Click the **locate** link in that
notification to open the folder containing the file. It is at:

```
android/app/build/outputs/apk/debug/app-debug.apk
```

The debug build is signed with Android Studio's debug key, which is all a
sideloaded app needs.

### Building from a terminal instead

```bash
cd unifi-toggle/android
./gradlew assembleDebug
```

The APK lands in the same place. This needs `ANDROID_HOME` pointing at your SDK,
or a `local.properties` file with `sdk.dir=/path/to/Android/Sdk`. Android Studio
writes that file for you the first time it opens the project.

## 7. Install it on the phone

The simplest route, with the phone plugged in over USB:

1. On the phone, open **Settings**, then **About phone**, and tap **Build number**
   seven times. You will see **You are now a developer!**
2. Go back to **Settings**, then **System**, then **Developer options**, and turn on
   **USB debugging**.
3. Plug the phone in. A dialog appears on the phone reading
   **Allow USB debugging?**. Tick **Always allow from this computer** and tap **Allow**.
4. On your workstation:

```bash
adb install -r android/app/build/outputs/apk/debug/app-debug.apk
```

`adb` ships with the SDK, at `~/Android/Sdk/platform-tools/adb` on Linux and
`~/Library/Android/sdk/platform-tools/adb` on a Mac.

Success prints:

```
Performing Streamed Install
Success
```

Without a cable, copy `app-debug.apk` to the phone by any means you like, open it
with the phone's file manager, and tap through the
**For your security, your phone is not allowed to install unknown apps from this
source** prompt to allow the file manager to install it.

## 8. Put the widget on the home screen

1. Long press an empty part of the home screen.
2. Tap **Widgets**.
3. Scroll to **UniFi Toggle**. Tap it to expand.
4. Long press the widget preview labelled **UniFi policy** and drag it onto the
   home screen.

The widget shows a title line, a status line, and the two buttons. It reads the
current state as soon as it is placed, so within a second or two the status line
should change from `Tap to refresh` to `ON as of 14:32` or `OFF as of 14:32`.

## Using it

* **Enable** turns the policy on. **Disable** turns it off.
* A toast confirms each tap, for example `Block Kids from Internet is now enabled`.
  If you have toasts turned off for this app, Android suppresses them, so the
  same message also appears on the widget status line, which is never suppressed.
* Tap the status line to re-read the state without changing anything.
* Tapping Enable when it is already on says `Block Kids from Internet was already
  enabled` and changes nothing.
* The status line refreshes on its own every 30 minutes.

## If a tap fails

The toast tells you which layer failed.

| Toast | Cause | Fix |
| --- | --- | --- |
| `TLS failed...` with `Trust anchor for certification path not found` in logcat | The CA in the app does not match the CA that signed the server cert, usually because make-cert.sh was rerun and minted a new CA | Copy the current `/etc/unifi-toggle/tls/ca.crt` from the VM into `res/raw/unifi_toggle_ca.pem`, rebuild, reinstall. Current make-cert.sh reuses the CA to avoid this. |
| `TLS failed...` with a hostname or SAN error in logcat | `BASE_URL` does not match the certificate SAN | Make them match, rebuild, reinstall |
| `Cannot reach https://...` | Phone is not on the network, VM is down, or the port is blocked | Check wifi or VPN, `systemctl status unifi-toggle`, and the VM firewall |
| `Timed out. Is the VM awake and on the same network?` | The address answers slowly or not at all | Same checks as above |
| `Rejected: no bearer token was sent` | `API_TOKEN` in `Config.kt` is empty | Fill it in, rebuild |
| `Rejected: API_TOKEN in Config.kt does not match the VM` | Token mismatch | Copy it again from the env file, rebuild |
| `Policy not found ...` | Wrong `UNIFI_POLICY_ID` or `UNIFI_POLICY_NAME` on the VM, or the policy was renamed | Re-run `probe-unifi.sh`, fix the env file, restart the service |
| `The VM could not reach the UniFi console ...` | The VM to UCG Ultra leg is broken | Check `journalctl -u unifi-toggle -f` |

The last two are the VM's problem, not the phone's. The widget is showing you
the middleware's own error and hint.

## Changing the address or token later

Edit `Config.kt`, build the APK again, and install it again with
`adb install -r`. The `-r` flag replaces the existing app and keeps your placed
widget where it is.

If you regenerate the TLS certificate on the VM you also have to replace
`res/raw/unifi_toggle_ca.pem` and rebuild, otherwise the phone stops trusting
the VM.

## Where the security boundary sits

The APK contains the bearer token, so treat the phone as trusted. If it is lost:

1. On the VM, run `/opt/unifi-toggle/scripts/gen-token.sh` for a new token.
2. Put it in `/etc/unifi-toggle/unifi-toggle.env` and run
   `sudo systemctl restart unifi-toggle`.

The old APK is dead at that point. Your UniFi API key is untouched, because it
was never on the phone. That is the whole reason the middleware exists.
