package dev.jarvis.screencast

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.media.projection.MediaProjectionManager
import android.net.Uri
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
    private val contactsPermissionRequest = 7023
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
                "Calls use Android Telecom and the normal Phone app interface.\n\n" +
                "One-time setup:\n" +
                "1. Enable JARVIS Phone calls and allow microphone access.\n" +
                "2. Enable J.A.R.V.I.S. in Android calling-account settings.\n" +
                "3. Set outgoing calls to Ask every time, if your Phone app offers that option.\n" +
                "4. Create the JARVIS Phone contact and allow contacts access.\n\n" +
                "From the Phone app, choose the J.A.R.V.I.S. calling account for the JARVIS contact. Choose your SIM for ordinary calls. The JARVIS number must never be sent through the SIM.\n\n" +
                "Local audio bridge: 127.0.0.1:21344"
            textSize = 16f
            setPadding(0, 0, 0, 24)
        }
        layout.addView(status)
        layout.addView(button("Enable JARVIS Phone calls") { enableCalling() })
        layout.addView(button("Create JARVIS Phone contact") { setupJarvisContact() })
        layout.addView(button("Open calling-account settings") { openCallingAccountSettings() })
        layout.addView(button("Open Phone app with JARVIS number") { openPhoneDialerForJarvis() })
        layout.addView(button("Enable screen control") { startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)) })
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

    private fun openPhoneDialerForJarvis() {
        val dialIntent = Intent(Intent.ACTION_DIAL, Uri.fromParts("tel", "+12025550147", null))
        try {
            startActivity(dialIntent)
        } catch (error: Exception) {
            Toast.makeText(this, "No Phone app is available to open the JARVIS number.", Toast.LENGTH_LONG).show()
            android.util.Log.e("JARVIS-CALL", "Could not open the Phone app", error)
        }
    }

    private fun openCallingAccountSettings() {
        val intent = Intent("android.telecom.action.CHANGE_PHONE_ACCOUNTS")
        try {
            startActivity(intent)
        } catch (_: Exception) {
            startActivity(Intent(Settings.ACTION_SETTINGS))
            Toast.makeText(this, "Open Calling accounts, enable J.A.R.V.I.S., and keep your SIM available for normal calls.", Toast.LENGTH_LONG).show()
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
        val service = Intent(this, OwnerCallBridgeService::class.java).apply { action = OwnerCallBridgeService.ACTION_START }
        if (Build.VERSION.SDK_INT >= 26) startForegroundService(service) else startService(service)
        Toast.makeText(this, "JARVIS calling service enabled. Enable its calling account in Android settings.", Toast.LENGTH_LONG).show()
    }

    private fun setupJarvisContact() {
        val permissions = arrayOf(android.Manifest.permission.READ_CONTACTS, android.Manifest.permission.WRITE_CONTACTS)
        if (permissions.any { checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }) {
            requestPermissions(permissions, contactsPermissionRequest)
            return
        }
        createJarvisContact()
    }

    private fun createJarvisContact() {
        try {
            val created = JarvisContact.ensure(this)
            val detail = if (created) "Created the JARVIS contact with its local virtual number." else "Updated the existing JARVIS contact."
            status.text = "$detail\n\nEnable J.A.R.V.I.S. in calling-account settings. For Phone-app calls, choose J.A.R.V.I.S. as the outgoing account for this contact and your SIM for ordinary calls."
            Toast.makeText(this, detail, Toast.LENGTH_LONG).show()
        } catch (error: Exception) {
            android.util.Log.e("JARVIS-CONTACT", "Could not create JARVIS contact", error)
            Toast.makeText(this, "Could not set up the JARVIS contact: \${error.javaClass.simpleName}", Toast.LENGTH_LONG).show()
        }
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        when (requestCode) {
            callPermissionRequest -> {
                if (grantResults.isNotEmpty() && grantResults[0] == PackageManager.PERMISSION_GRANTED) startCallingService()
                else Toast.makeText(this, "Microphone permission is required for two-way calls.", Toast.LENGTH_LONG).show()
            }
            contactsPermissionRequest -> {
                if (grantResults.size == 2 && grantResults.all { it == PackageManager.PERMISSION_GRANTED }) createJarvisContact()
                else Toast.makeText(this, "Contacts permission is required to add JARVIS as a local calling contact.", Toast.LENGTH_LONG).show()
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
