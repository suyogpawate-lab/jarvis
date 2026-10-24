package dev.jarvis.screencast

import android.app.*
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.*
import android.util.DisplayMetrics
import android.view.WindowManager
import java.io.BufferedOutputStream
import java.io.DataOutputStream
import java.net.InetSocketAddress
import java.net.Socket

class ScreenCastService : Service() {
    companion object {
        const val ACTION_START = "dev.jarvis.screencast.START"
        const val EXTRA_RESULT_CODE = "result_code"
        const val EXTRA_RESULT_DATA = "result_data"
        private const val CHANNEL = "jarvis_screen_cast"
    }
    private var projection: MediaProjection? = null
    private var display: VirtualDisplay? = null
    private var reader: ImageReader? = null
    private var thread: HandlerThread? = null
    private var socket: Socket? = null
    private var output: DataOutputStream? = null
    @Volatile private var lastSent = 0L

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action != ACTION_START) return START_NOT_STICKY
        @Suppress("DEPRECATION")
        val data = intent.getParcelableExtra<Intent>(EXTRA_RESULT_DATA)
        val code = intent.getIntExtra(EXTRA_RESULT_CODE, 0)
        if (data == null || code == 0) { stopSelf(); return START_NOT_STICKY }
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= 26) nm.createNotificationChannel(NotificationChannel(CHANNEL, "JARVIS screen cast", NotificationManager.IMPORTANCE_LOW))
        val nb = if (Build.VERSION.SDK_INT >= 26) Notification.Builder(this, CHANNEL) else Notification.Builder(this)
        startForeground(21340, nb.setContentTitle("JARVIS screen cast active").setContentText("Live screen is streaming to JARVIS locally").setSmallIcon(android.R.drawable.ic_menu_view).build())
        beginCapture(code, data)
        return START_NOT_STICKY
    }

    private fun beginCapture(code: Int, data: Intent) {
        val metrics = DisplayMetrics()
        @Suppress("DEPRECATION")
        (getSystemService(Context.WINDOW_SERVICE) as WindowManager).defaultDisplay.getRealMetrics(metrics)
        val scale = minOf(1f, 960f / metrics.widthPixels.toFloat())
        val w = (metrics.widthPixels * scale).toInt().coerceAtLeast(1)
        val h = (metrics.heightPixels * scale).toInt().coerceAtLeast(1)
        thread = HandlerThread("jarvis-cast").also { it.start() }
        val handler = Handler(thread!!.looper)
        reader = ImageReader.newInstance(w, h, PixelFormat.RGBA_8888, 2)
        val mgr = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        projection = mgr.getMediaProjection(code, data)
        projection?.registerCallback(object : MediaProjection.Callback() {
            override fun onStop() { stopSelf() }
        }, handler)
        reader?.setOnImageAvailableListener({ source ->
            val now = System.currentTimeMillis()
            if (now - lastSent < 160) { source.acquireLatestImage()?.close(); return@setOnImageAvailableListener }
            val image = source.acquireLatestImage() ?: return@setOnImageAvailableListener
            try {
                val plane = image.planes[0]
                val padded = plane.rowStride / plane.pixelStride
                val bitmap = Bitmap.createBitmap(padded, image.height, Bitmap.Config.ARGB_8888)
                bitmap.copyPixelsFromBuffer(plane.buffer)
                val crop = if (padded == image.width) bitmap else Bitmap.createBitmap(bitmap, 0, 0, image.width, image.height)
                val bytes = java.io.ByteArrayOutputStream()
                crop.compress(Bitmap.CompressFormat.JPEG, 58, bytes)
                if (crop !== bitmap) crop.recycle()
                bitmap.recycle()
                sendFrame(bytes.toByteArray())
                lastSent = now
            } catch (_: Exception) {
            } finally { image.close() }
        }, handler)
        display = projection?.createVirtualDisplay("JARVIS Live Screen", w, h, metrics.densityDpi, DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR, reader?.surface, null, handler)
    }

    @Synchronized private fun sendFrame(frame: ByteArray) {
        try {
            if (socket == null || socket?.isClosed != false) {
                socket = Socket().also { it.connect(InetSocketAddress("127.0.0.1", 21340), 1000); it.tcpNoDelay = true }
                output = DataOutputStream(BufferedOutputStream(socket!!.getOutputStream()))
            }
            output?.writeInt(frame.size)
            output?.write(frame)
            output?.flush()
        } catch (_: Exception) {
            try { socket?.close() } catch (_: Exception) {}
            socket = null
            output = null
        }
    }

    override fun onDestroy() {
        try { display?.release() } catch (_: Exception) {}
        try { reader?.close() } catch (_: Exception) {}
        try { projection?.stop() } catch (_: Exception) {}
        try { socket?.close() } catch (_: Exception) {}
        thread?.quitSafely()
        stopForeground(true)
        super.onDestroy()
    }
}
