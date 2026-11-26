package dev.jarvis.screencast

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build

class OwnerCallAlarmReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val service = Intent(context, OwnerCallBridgeService::class.java).apply {
            action = OwnerCallBridgeService.ACTION_ALARM_CALL
            putExtra(JarvisConnectionService.EXTRA_MESSAGE,
                intent.getStringExtra(JarvisConnectionService.EXTRA_MESSAGE) ?: "JARVIS wake-up call.")
        }
        if (Build.VERSION.SDK_INT >= 26) context.startForegroundService(service)
        else context.startService(service)
    }
}
