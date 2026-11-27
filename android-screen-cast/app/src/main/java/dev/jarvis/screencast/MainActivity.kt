package dev.jarvis.screencast

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.view.Gravity
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast

class MainActivity : Activity() {
    private val projectionRequest = 7021
    private val callPermissionRequest = 7022
    private lateinit var status: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val layout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setPadding(32, 32, 32, 32)
        }
        status = TextView(this).apply {
            text = "JARVIS Android companion\n\n" +
                "Calls are handled by your existing Phone app.\n\n" +
                "One-time setup:\n" +
                "1. Tap Enable JARVIS Phone calls below.\n" +
                "2. Allow microphone access.\n" +
                "3. Tap Open calling-account settings below. Set calls to Ask every time.\n\n" +
                "To call JARVIS: open Phone, dial 0, tap Call, then choose J.A.R.V.I.S. in the account chooser.\n" +
                "Do not choose the SIM for 0; the SIM dialer treats it as an MMI code.\n" +
                "Incoming JARVIS calls will appear in the Phone app.\n\n" +
                "Local audio bridge: 127.0.0.1:21344"
            textSize = 16f
            setPadding(0, 0, 0, 24)
        }
        layout.addView(status)
        layout.addView(button("Enable JARVIS Phone calls") { enableCalling() })
        layout.addView(button("Open calling-account settings") { openCallingAccountSettings() })
        layout.addView(button("Enable screen control") {
            startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
        })
        layout.addView(button("Start live cast") {
            val manager = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
            startActivityForResult(manager.createScreenCaptureIntent(), projectionRequest)
        })
        layout.addView(button("Stop live cast") {
            stopService(Intent(this, ScreenCastService::class.java))
            status.text = "Screen cast stopped."
        })
        setContentView(layout)
        JarvisConnectionService.registerAccount(this)
    }

    private fun openCallingAccountSettings() {
        val intent = Intent("android.telecom.action.CHANGE_PHONE_ACCOUNTS")
        try {
            startActivity(intent)
        } catch (_: Exception) {
            startActivity(Intent(Settings.ACTION_SETTINGS))
            Toast.makeText(
                this,
                "Open Calling accounts, then set outgoing calls to Ask every time.",
                Toast.LENGTH_LONG
            ).show()
        }
    }

    private fun enableCalling() {
        if (checkSelfPermission(android.Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(android.Manifest.permission.RECORD_AUDIO), callPermissionRequest)
            return
        }
        startCallingService()
    }

    private fun startCallingService() {
        JarvisConnectionService.registerAccount(this)
        val service = Intent(this, OwnerCallBridgeService::class.java).apply {
            action = OwnerCallBridgeService.ACTION_START
        }
        if (Build.VERSION.SDK_INT >= 26) startForegroundService(service) else startService(service)
        Toast.makeText(
            this,
            "JARVIS calling service enabled. Open calling-account settings and choose Ask every time.",
            Toast.LENGTH_LONG
        ).show()
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == callPermissionRequest) {
            if (grantResults.isNotEmpty() && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
                startCallingService()
            } else {
                Toast.makeText(this, "Microphone permission is required for two-way calls.", Toast.LENGTH_LONG).show()
            }
        }
    }

    private fun button(label: String, action: () -> Unit): Button =
        Button(this).apply { text = label; setOnClickListener { action() } }

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
