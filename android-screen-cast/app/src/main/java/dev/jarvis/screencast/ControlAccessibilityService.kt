package dev.jarvis.screencast

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.graphics.Path
import android.os.Bundle
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.InetAddress
import java.net.ServerSocket
import java.util.concurrent.Executors

class ControlAccessibilityService : AccessibilityService() {
    @Volatile private var listener: ServerSocket? = null
    private val worker = Executors.newSingleThreadExecutor()

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {}
    override fun onInterrupt() {}

    override fun onServiceConnected() {
        super.onServiceConnected()
        worker.execute {
            while (!Thread.currentThread().isInterrupted) {
                try {
                    ServerSocket(21341, 8, InetAddress.getByName("127.0.0.1")).use { server ->
                        listener = server
                        while (!server.isClosed) {
                            server.accept().use { client ->
                                client.soTimeout = 4000
                                val line = BufferedReader(InputStreamReader(client.getInputStream(), Charsets.UTF_8)).readLine()
                                val result = try {
                                    if (line.isNullOrBlank() || line.length > 8192) JSONObject().put("ok", false).put("error", "invalid request")
                                    else runAction(JSONObject(line))
                                } catch (e: Exception) {
                                    JSONObject().put("ok", false).put("error", e.message ?: "action failed")
                                }
                                client.getOutputStream().write((result.toString() + "\n").toByteArray(Charsets.UTF_8))
                                client.getOutputStream().flush()
                            }
                        }
                    }
                } catch (_: Exception) {
                    try { Thread.sleep(400) } catch (_: InterruptedException) { return@execute }
                } finally { listener = null }
            }
        }
    }

    private fun runAction(req: JSONObject): JSONObject {
        val action = req.optString("action", "")
        val ok = when (action) {
            "tap" -> {
                val x = req.getInt("x").toFloat()
                val y = req.getInt("y").toFloat()
                performSwipe(x, y, x, y, 80)
            }
            "swipe" -> performSwipe(
                req.getInt("x1").toFloat(), req.getInt("y1").toFloat(),
                req.getInt("x2").toFloat(), req.getInt("y2").toFloat(),
                req.optLong("duration_ms", 350).coerceIn(80, 1500)
            )
            "type" -> setFocusedText(req.getString("text"))
            "back" -> performGlobalAction(GLOBAL_ACTION_BACK)
            "home" -> performGlobalAction(GLOBAL_ACTION_HOME)
            "recents" -> performGlobalAction(GLOBAL_ACTION_RECENTS)
            "notifications" -> performGlobalAction(GLOBAL_ACTION_NOTIFICATIONS)
            else -> return JSONObject().put("ok", false).put("error", "unsupported action")
        }
        return JSONObject().put("ok", ok).put("action", action)
    }

    private fun performSwipe(x1: Float, y1: Float, x2: Float, y2: Float, duration: Long): Boolean {
        val path = Path().apply { moveTo(x1, y1); lineTo(x2, y2) }
        val gesture = GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, 0, duration)).build()
        return dispatchGesture(gesture, null, null)
    }

    private fun setFocusedText(text: String): Boolean {
        if (text.isEmpty() || text.length > 2000) return false
        val root = rootInActiveWindow ?: return false
        val node = root.findFocus(AccessibilityNodeInfo.FOCUS_INPUT)
        val args = Bundle().apply {
            putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text)
        }
        val result = node?.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args) ?: false
        node?.recycle()
        root.recycle()
        return result
    }

    override fun onDestroy() {
        try { listener?.close() } catch (_: Exception) {}
        worker.shutdownNow()
        super.onDestroy()
    }
}
