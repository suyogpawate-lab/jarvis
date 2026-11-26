package dev.jarvis.screencast

import android.app.Activity
import android.os.Bundle
import android.view.Gravity
import android.view.WindowManager
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import android.telecom.DisconnectCause

class OutgoingCallActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        val layout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setPadding(36, 48, 36, 48)
        }
        layout.addView(TextView(this).apply {
            text = "J.A.R.V.I.S."
            textSize = 30f
            gravity = Gravity.CENTER
        })
        layout.addView(TextView(this).apply {
            text = "Outgoing local call\n\nThe JARVIS Telecom session has been started on this device. Two-way speech is not connected in this build yet."
            textSize = 18f
            gravity = Gravity.CENTER
            setPadding(0, 28, 0, 36)
        })
        layout.addView(Button(this).apply {
            text = "End call"
            setOnClickListener {
                JarvisConnectionService.activeConnection?.rejectFromUi()
                JarvisConnectionService.activeConnection = null
                finish()
            }
        })
        setContentView(layout)
    }
}
