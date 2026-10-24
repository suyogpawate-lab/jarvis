package dev.jarvis.screencast

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.media.projection.MediaProjectionManager
import android.os.Bundle
import android.provider.Settings
import android.view.Gravity
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast

class MainActivity : Activity() {
    private val projectionRequest = 7021
    private lateinit var status: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val layout = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER; setPadding(32, 32, 32, 32) }
        status = TextView(this).apply {
            text = "JARVIS live screen cast\n\nStream: 127.0.0.1:21340\nControl: 127.0.0.1:21341\n\nCasting requires Android system consent. Control requires enabling the accessibility service."
            textSize = 16f; setPadding(0, 0, 0, 24)
        }
        layout.addView(status)
        layout.addView(button("Enable screen control") { startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)) })
        layout.addView(button("Start live cast") {
            val manager = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
            startActivityForResult(manager.createScreenCaptureIntent(), projectionRequest)
        })
        layout.addView(button("Stop live cast") {
            stopService(Intent(this, ScreenCastService::class.java)); status.text = "Screen cast stopped."
        })
        setContentView(layout)
    }

    private fun button(label: String, action: () -> Unit): Button = Button(this).apply { text = label; setOnClickListener { action() } }

    @Deprecated("Activity result API retained for Android 10 compatibility")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != projectionRequest) return
        if (resultCode != RESULT_OK || data == null) {
            Toast.makeText(this, "Screen-capture permission was not granted.", Toast.LENGTH_SHORT).show()
            return
        }
        val service = Intent(this, ScreenCastService::class.java).apply {
            action = ScreenCastService.ACTION_START
            putExtra(ScreenCastService.EXTRA_RESULT_CODE, resultCode)
            putExtra(ScreenCastService.EXTRA_RESULT_DATA, data)
        }
        startForegroundService(service)
        status.text = "Live cast starting. Keep Android's screen-sharing indicator visible while casting."
    }
}
