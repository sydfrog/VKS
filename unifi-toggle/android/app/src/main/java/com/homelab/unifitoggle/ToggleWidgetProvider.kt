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
import android.widget.RemoteViews
import android.widget.Toast
import java.util.concurrent.Executors

/**
 * The whole app. Two buttons and a status line on the home screen.
 *
 * Network work cannot run on the broadcast thread, so every tap calls
 * goAsync() to hold the broadcast open, does the request on a background
 * executor, then finishes. That keeps the process alive for the roughly ten
 * seconds a broadcast is allowed, which is well past the request timeout.
 */
class ToggleWidgetProvider : AppWidgetProvider() {

    private enum class Action { ENABLE, DISABLE, STATUS }

    override fun onUpdate(
        context: Context,
        appWidgetManager: AppWidgetManager,
        appWidgetIds: IntArray,
    ) {
        for (id in appWidgetIds) {
            appWidgetManager.updateAppWidget(id, buildViews(context, "Tap to refresh"))
        }
        // Pull the real state so a freshly placed widget is not blank.
        context.sendBroadcast(intentFor(context, ACTION_REFRESH))
    }

    override fun onReceive(context: Context, intent: Intent) {
        val action = when (intent.action) {
            ACTION_ENABLE -> Action.ENABLE
            ACTION_DISABLE -> Action.DISABLE
            ACTION_REFRESH -> Action.STATUS
            else -> null
        }
        if (action == null) {
            super.onReceive(context, intent)
            return
        }

        val pendingResult = goAsync()
        val appContext = context.applicationContext
        executor.execute {
            try {
                setStatus(appContext, "Working...")
                val result = when (action) {
                    Action.ENABLE -> ToggleClient.enable()
                    Action.DISABLE -> ToggleClient.disable()
                    Action.STATUS -> ToggleClient.status()
                }
                setStatus(appContext, result.statusLine())
                // A silent refresh should not pop a toast, a deliberate tap should.
                if (action != Action.STATUS || !result.ok) {
                    toast(appContext, result.message)
                }
            } catch (t: Throwable) {
                Log.e(TAG, "Unexpected failure handling $action", t)
                setStatus(appContext, "Error")
                toast(appContext, "Unexpected error: ${t.javaClass.simpleName}")
            } finally {
                pendingResult.finish()
            }
        }
    }

    private companion object {
        const val TAG = "UniFiToggle"
        const val ACTION_ENABLE = "com.homelab.unifitoggle.ENABLE"
        const val ACTION_DISABLE = "com.homelab.unifitoggle.DISABLE"
        const val ACTION_REFRESH = "com.homelab.unifitoggle.REFRESH"

        // Provider instances are recreated for every broadcast, so the executor
        // and the main thread handler have to outlive them.
        val executor = Executors.newSingleThreadExecutor()
        val mainHandler = Handler(Looper.getMainLooper())

        fun intentFor(context: Context, action: String): Intent =
            Intent(context, ToggleWidgetProvider::class.java).setAction(action)

        fun pendingIntent(context: Context, action: String, requestCode: Int): PendingIntent =
            PendingIntent.getBroadcast(
                context,
                requestCode,
                intentFor(context, action),
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
            )

        fun buildViews(context: Context, status: String): RemoteViews =
            RemoteViews(context.packageName, R.layout.widget_toggle).apply {
                setTextViewText(R.id.status_text, status)
                setOnClickPendingIntent(
                    R.id.button_enable, pendingIntent(context, ACTION_ENABLE, 1)
                )
                setOnClickPendingIntent(
                    R.id.button_disable, pendingIntent(context, ACTION_DISABLE, 2)
                )
                setOnClickPendingIntent(
                    R.id.status_text, pendingIntent(context, ACTION_REFRESH, 3)
                )
            }

        /** Repaint every placed instance of the widget. */
        fun setStatus(context: Context, status: String) {
            val manager = AppWidgetManager.getInstance(context)
            val component = ComponentName(context, ToggleWidgetProvider::class.java)
            val ids = manager.getAppWidgetIds(component)
            if (ids.isEmpty()) return
            manager.updateAppWidget(ids, buildViews(context, status))
        }

        fun toast(context: Context, message: String) {
            mainHandler.post {
                Toast.makeText(context, message, Toast.LENGTH_SHORT).show()
            }
        }
    }
}
