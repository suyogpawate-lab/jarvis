package dev.jarvis.screencast

import android.app.AlarmManager
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import org.json.JSONObject
import java.net.ServerSocket
import java.net.Socket
import java.util.concurrent.Executors

class OwnerCallBridgeService : Service() {
    companion object {
        const val ACTION_START = "dev.jarvis.screencast.owner.START"
        const val ACTION_ALARM_CALL = "dev.jarvis.screencast.owner.ALARM_CALL"
        private const val CHANNEL = "jarvis_owner_bridge"
        private const val FOREGROUND_ID = 21343
        private const val PORT = 21342
    }
    @Volatile private var running = false
    private var server: ServerSocket? = null
    private val workers = Executors.newSingleThreadExecutor()

    override fun onCreate() {
        super.onCreate()
        JarvisConnectionService.registerAccount(this)
        if (Build.VERSION.SDK_INT >= 26) {
            val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            nm.createNotificationChannel(NotificationChannel(
                CHANNEL, "JARVIS calling service", NotificationManager.IMPORTANCE_LOW
            ))
        }
        val builder = if (Build.VERSION.SDK_INT >= 26) Notification.Builder(this, CHANNEL)
            else Notification.Builder(this)
        startForeground(FOREGROUND_ID, builder
            .setSmallIcon(android.R.drawable.sym_call_incoming)
            .setContentTitle("JARVIS calling ready")
            .setContentText("Local owner-call bridge is active")
            .setOngoing(true).build())
        running = true
        workers.execute { listen() }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_ALARM_CALL) {
            val message = intent.getStringExtra(JarvisConnectionService.EXTRA_MESSAGE)
                ?: "JARVIS wake-up call."
            JarvisConnectionService.incomingCall(this, message, "scheduled_wakeup")
        }
        return START_STICKY
    }

    private fun listen() {
        try {
            server = ServerSocket(PORT, 8, java.net.InetAddress.getByName("127.0.0.1"))
            while (running) {
                val socket = server?.accept() ?: break
                handle(socket)
            }
        } catch (error: Exception) {
            if (running) android.util.Log.e("JARVIS-CALL", "Local call socket stopped", error)
        }
    }

    private fun handle(socket: Socket) {
        socket.use { client ->
            client.soTimeout = 3000
            val line = client.getInputStream().bufferedReader(Charsets.UTF_8).readLine()
            val request = JSONObject(line ?: "{}")
            val response = when (request.optString("action")) {
                "call" -> {
                    val ok = JarvisConnectionService.incomingCall(
                        this,
                        request.optString("message", "JARVIS has an update."),
                        request.optString("reason", "assistant_update")
                    )
                    JSONObject().put("ok", ok).put("accepted", ok)
                }
                "schedule_wakeup" -> scheduleWakeup(request)
                "cancel_wakeup" -> cancelWakeup(request.optString("event_id"))
                "audio_token" -> JSONObject().put("ok", true).put("audio_token", JarvisConnectionService.audioToken(this))
                "status" -> JSONObject().put("ok", true).put("available", true)
                else -> JSONObject().put("ok", false).put("error", "unknown_action")
            }
            client.getOutputStream().bufferedWriter(Charsets.UTF_8).use {
                it.write(response.toString())
                it.write("\n")
                it.flush()
            }
        }
    }

    private fun wakeIntent(eventId: String, message: String): PendingIntent {
        val intent = Intent(this, OwnerCallAlarmReceiver::class.java).apply {
            action = "dev.jarvis.screencast.owner.WAKE"
            putExtra("event_id", eventId)
            putExtra(JarvisConnectionService.EXTRA_MESSAGE, message)
        }
        val flags = PendingIntent.FLAG_UPDATE_CURRENT or
            (if (Build.VERSION.SDK_INT >= 23) PendingIntent.FLAG_IMMUTABLE else 0)
        return PendingIntent.getBroadcast(this, eventId.hashCode(), intent, flags)
    }

    private fun scheduleWakeup(request: JSONObject): JSONObject {
        val at = (request.optDouble("at_epoch", 0.0) * 1000.0).toLong()
        if (at <= System.currentTimeMillis()) return JSONObject().put("ok", false).put("error", "time_must_be_future")
        val id = request.optString("event_id", "jarvis-wakeup")
        val message = request.optString("message", "JARVIS wake-up call.")
        val alarm = getSystemService(Context.ALARM_SERVICE) as AlarmManager
        return try {
            alarm.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, wakeIntent(id, message))
            JSONObject().put("ok", true).put("scheduled", true).put("at_epoch", at / 1000)
        } catch (error: Exception) {
            JSONObject().put("ok", false).put("error", error.javaClass.simpleName)
        }
    }

    private fun cancelWakeup(id: String): JSONObject {
        val alarm = getSystemService(Context.ALARM_SERVICE) as AlarmManager
        alarm.cancel(wakeIntent(id, ""))
        return JSONObject().put("ok", true).put("cancelled", true)
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        running = false
        try { server?.close() } catch (_: Exception) {}
        workers.shutdownNow()
        stopForeground(true)
        super.onDestroy()
    }
}
