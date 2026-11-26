package dev.jarvis.screencast

import android.app.Activity
import android.os.Bundle
import android.view.Gravity
import android.view.WindowManager
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView

class IncomingCallActivity : Activity() {
    private lateinit var detail: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (android.os.Build.VERSION.SDK_INT >= 27) {
            setShowWhenLocked(true)
            setTurnScreenOn(true)
        } else {
            @Suppress("DEPRECATION")
            window.addFlags(WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED or
                WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON)
        }
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
        detail = TextView(this).apply {
            text = JarvisConnectionService.activeMessage
            textSize = 18f
            gravity = Gravity.CENTER
            setPadding(0, 28, 0, 36)
        }
        layout.addView(detail)
        layout.addView(Button(this).apply {
            text = "Answer"
            setOnClickListener {
                JarvisConnectionService.activeConnection?.answerFromUi()
                detail.text = "Call accepted. Voice conversation transport is not connected yet."
                it.isEnabled = false
            }
        })
        layout.addView(Button(this).apply {
            text = "Dismiss"
            setOnClickListener {
                JarvisConnectionService.activeConnection?.rejectFromUi()
                JarvisConnectionService.activeConnection = null
                JarvisConnectionService.clearIncomingUi(this@IncomingCallActivity)
                finish()
            }
        })
        setContentView(layout)
    }
}
