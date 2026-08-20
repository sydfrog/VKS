package com.homelab.unifitoggle

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.View
import android.widget.RemoteViews
import android.widget.Toast
import java.util.concurrent.Executors

/**
 * A switch styled widget for Kids Internet Access.
 *
 * It shows one pill with a knob: green with the knob on the left for Allowed,
 * red with the knob on the right for Blocked. Tapping it flips to the other
 * state. A home screen widget cannot receive a drag gesture, only a tap, so the
 * slide is expressed as a tap that moves the knob and changes colour.
 *
 * The three pills in widget_switch.xml are stacked and exactly one is shown at a
 * time with setViewVisibility, which avoids any runtime repositioning that
 * RemoteViews cannot do.
 */
class SwitchWidgetProvider : AppWidgetProvider() {

    private enum class Render { ALLOWED, BLOCKED, UNKNOWN }

    override fun onUpdate(
        context: Context,
        appWidgetManager: AppWidgetManager,
        appWidgetIds: IntArray,
    ) {
        for (id in appWidgetIds) {
            appWidgetManager.updateAppWidget(
                id, buildViews(context, Render.UNKNOWN, context.getString(R.string.state_checking))
            )
        }
        // Read the real state so a freshly placed switch shows the right side.
        context.sendBroadcast(intentFor(context, ACTION_REFRESH))
    }

    override fun onReceive(context: Context, intent: Intent) {
        val action = intent.action
        if (action != ACTION_TOGGLE && action != ACTION_REFRESH) {
            super.onReceive(context, intent)
            return
        }

        val pendingResult = goAsync()
        val appContext = context.applicationContext
        executor.execute {
            try {
                render(appContext, Render.UNKNOWN, appContext.getString(R.string.state_checking))
                val result = if (action == ACTION_TOGGLE) {
                    ToggleClient.toggle()
                } else {
                    ToggleClient.status()
                }
                if (result.ok) {
                    val render = if (result.enabled == true) Render.BLOCKED else Render.ALLOWED
                    render(appContext, render, null)
                    if (action == ACTION_TOGGLE) {
                        toast(appContext, result.message)
                    }
                } else {
                    render(appContext, Render.UNKNOWN, result.statusLine())
                    toast(appContext, result.message)
                }
            } catch (t: Throwable) {
                Log.e(TAG, "Unexpected failure handling $action", t)
                render(appContext, Render.UNKNOWN, "Error")
                toast(appContext, "Unexpected error: ${t.javaClass.simpleName}")
            } finally {
                pendingResult.finish()
            }
        }
    }

    private companion object {
        const val TAG = "UniFiToggle"
        const val ACTION_TOGGLE = "com.homelab.unifitoggle.SWITCH_TOGGLE"
        const val ACTION_REFRESH = "com.homelab.unifitoggle.SWITCH_REFRESH"

        val executor = Executors.newSingleThreadExecutor()
        val mainHandler = Handler(Looper.getMainLooper())

        fun intentFor(context: Context, action: String): Intent =
            Intent(context, SwitchWidgetProvider::class.java).setAction(action)

        fun pendingIntent(context: Context, action: String, requestCode: Int): PendingIntent =
            PendingIntent.getBroadcast(
                context,
                requestCode,
                intentFor(context, action),
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
            )

        fun buildViews(context: Context, render: Render, unknownText: String?): RemoteViews =
            RemoteViews(context.packageName, R.layout.widget_switch).apply {
                setViewVisibility(
                    R.id.state_allowed, if (render == Render.ALLOWED) View.VISIBLE else View.GONE
                )
                setViewVisibility(
                    R.id.state_blocked, if (render == Render.BLOCKED) View.VISIBLE else View.GONE
                )
                setViewVisibility(
                    R.id.state_unknown, if (render == Render.UNKNOWN) View.VISIBLE else View.GONE
                )
                if (render == Render.UNKNOWN && unknownText != null) {
                    setTextViewText(R.id.state_unknown_text, unknownText)
                }
                // The whole pill is the tap target. A tap flips to the other state.
                setOnClickPendingIntent(
                    R.id.switch_track, pendingIntent(context, ACTION_TOGGLE, 1)
                )
                setOnClickPendingIntent(
                    R.id.switch_title, pendingIntent(context, ACTION_REFRESH, 2)
                )
            }

        fun render(context: Context, r: Render, unknownText: String?) {
            val manager = AppWidgetManager.getInstance(context)
            val component = ComponentName(context, SwitchWidgetProvider::class.java)
            val ids = manager.getAppWidgetIds(component)
            if (ids.isEmpty()) return
            manager.updateAppWidget(ids, buildViews(context, r, unknownText))
        }

        fun toast(context: Context, message: String) {
            mainHandler.post {
                Toast.makeText(context, message, Toast.LENGTH_SHORT).show()
            }
        }
    }
}
