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
                "JARVIS calls use Android's Phone app interface as a local call provider.\n" +
                "Carrier SIM calls remain directly managed by Android and are never routed through JARVIS.\n\n" +
                "One-time setup:\n" +
                "1. Enable JARVIS Phone calls and allow microphone access.\n" +
                "2. Enable J.A.R.V.I.S. in Android calling-account settings.\n" +
                "3. Keep your SIM selected as the default outgoing account. Do NOT select J.A.R.V.I.S. as SIM call manager.\n" +
                "4. Create the JARVIS Phone contact and allow contacts access.\n\n" +
                "Local audio bridge: 127.0.0.1:21344"
            textSize = 16f
            setPadding(0, 0, 0, 24)
        }
        layout.addView(status)
        layout.addView(button("Enable JARVIS Phone calls") { enableCalling() })
        layout.addView(button("Create JARVIS Phone contact") { setupJarvisContact() })
        layout.addView(button("Open calling-account settings") { openCallingAccountSettings() })
        layout.addView(button("Open Phone app with JARVIS number") { openPhoneDialerForJarvis() })
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
        // Never initialize Telecom during Activity startup.
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
            Toast.makeText(
                this,
                "Enable the JARVIS local call account if available. Keep your SIM as the default outgoing account. Do not select JARVIS as SIM call manager.",
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
        try {
            JarvisConnectionService.registerAccount(this)
        } catch (error: UnsupportedOperationException) {
            showCallingUnavailable("This Android build does not provide Telecom calling support.")
            android.util.Log.w("JARVIS-CALL", "Telecom is unavailable on this device.", error)
            return
        } catch (error: SecurityException) {
            showCallingUnavailable("Android denied registration of the JARVIS calling account.")
            android.util.Log.e("JARVIS-CALL", "PhoneAccount registration was denied.", error)
            return
        } catch (error: IllegalArgumentException) {
            showCallingUnavailable("Android rejected the JARVIS calling account configuration.")
            android.util.Log.e("JARVIS-CALL", "PhoneAccount configuration was rejected.", error)
            return
        } catch (error: RuntimeException) {
            showCallingUnavailable("Android could not initialize phone calling on this device.")
            android.util.Log.e("JARVIS-CALL", "PhoneAccount registration failed.", error)
            return
        }

        try {
            val service = Intent(this, OwnerCallBridgeService::class.java).apply {
                action = OwnerCallBridgeService.ACTION_START
            }
            if (Build.VERSION.SDK_INT >= 26) startForegroundService(service) else startService(service)
            status.text = "JARVIS local calling is enabled. Keep your SIM as the default outgoing account. JARVIS does not manage or proxy carrier calls."
            Toast.makeText(this, "JARVIS local calling enabled. Carrier calls remain on your SIM.", Toast.LENGTH_LONG).show()
        } catch (error: Exception) {
            showCallingUnavailable("Android could not start the JARVIS calling service.")
            android.util.Log.e("JARVIS-CALL", "Could not start the calling service.", error)
        }
    }

    private fun showCallingUnavailable(message: String) {
        status.text = message + "\n\nThe companion app remains available for screen casting and screen control."
        Toast.makeText(this, message, Toast.LENGTH_LONG).show()
    }

    private fun setupJarvisContact() {
        val permissions = arrayOf(
            android.Manifest.permission.READ_CONTACTS,
            android.Manifest.permission.WRITE_CONTACTS
        )
        if (permissions.any { checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }) {
            requestPermissions(permissions, contactsPermissionRequest)
            return
        }
        createJarvisContact()
    }

    private fun createJarvisContact() {
        try {
            val created = JarvisContact.ensure(this)
            val detail = if (created) "Created the JARVIS contact with its local virtual number."
                else "Updated the existing JARVIS contact."
            status.text = detail + "\n\nUse the JARVIS local call account only for the JARVIS contact. Keep your SIM as the default outgoing account. JARVIS never intercepts carrier calls."
            Toast.makeText(this, detail, Toast.LENGTH_LONG).show()
        } catch (error: Exception) {
            android.util.Log.e("JARVIS-CONTACT", "Could not create JARVIS contact", error)
            Toast.makeText(this, "Could not set up the JARVIS contact: " + error.javaClass.simpleName, Toast.LENGTH_LONG).show()
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        when (requestCode) {
            callPermissionRequest -> {
                if (grantResults.isNotEmpty() && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
                    startCallingService()
                } else {
                    Toast.makeText(this, "Microphone permission is required for two-way calls.", Toast.LENGTH_LONG).show()
                }
            }
            contactsPermissionRequest -> {
                if (grantResults.size == 2 && grantResults.all { it == PackageManager.PERMISSION_GRANTED }) {
                    createJarvisContact()
                } else {
                    Toast.makeText(this, "Contacts permission is required to add JARVIS as a local calling contact.", Toast.LENGTH_LONG).show()
                }
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
