package dev.jarvis.screencast

import android.app.Activity
import android.app.role.RoleManager
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
    private val contactsPermissionRequest = 7023
    private val redirectionRoleRequest = 7024
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
                "Calls use the normal Android Phone app.\n\n" +
                "One-time setup:\n" +
                "1. Enable JARVIS Phone calls and allow microphone access.\n" +
                "2. Enable JARVIS call routing in the system role prompt.\n" +
                "3. Create the JARVIS Phone contact and allow contacts access.\n" +
                "4. Enable J.A.R.V.I.S. in calling-account settings. Keep your SIM as the default account.\n\n" +
                "Search for JARVIS in the Phone app and tap Call. Only the JARVIS virtual number is routed locally; other calls remain unchanged.\n\n" +
                "Local audio bridge: 127.0.0.1:21344"
            textSize = 16f
            setPadding(0, 0, 0, 24)
        }
        layout.addView(status)
        layout.addView(button("Enable JARVIS Phone calls") { enableCalling() })
        layout.addView(button("Enable JARVIS call routing") { requestCallRedirectionRole() })
        layout.addView(button("Create JARVIS Phone contact") { setupJarvisContact() })
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

    private fun requestCallRedirectionRole() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) {
            Toast.makeText(this, "JARVIS call routing requires Android 10 or newer.", Toast.LENGTH_LONG).show()
            return
        }
        val roles = getSystemService(Context.ROLE_SERVICE) as RoleManager
        if (!roles.isRoleAvailable(RoleManager.ROLE_CALL_REDIRECTION)) {
            Toast.makeText(this, "This Android build does not expose the call-redirection role.", Toast.LENGTH_LONG).show()
            return
        }
        if (roles.isRoleHeld(RoleManager.ROLE_CALL_REDIRECTION)) {
            status.text = "JARVIS already has the call-redirection role."
            Toast.makeText(this, "JARVIS call routing is enabled.", Toast.LENGTH_SHORT).show()
            return
        }
        startActivityForResult(
            roles.createRequestRoleIntent(RoleManager.ROLE_CALL_REDIRECTION),
            redirectionRoleRequest
        )
    }

    private fun openCallingAccountSettings() {
        val intent = Intent("android.telecom.action.CHANGE_PHONE_ACCOUNTS")
        try {
            startActivity(intent)
        } catch (_: Exception) {
            startActivity(Intent(Settings.ACTION_SETTINGS))
            Toast.makeText(
                this,
                "Open Calling accounts and enable J.A.R.V.I.S. Leave your SIM as the default outgoing account.",
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
            "JARVIS calling service enabled. Enable its calling account once in Android settings.",
            Toast.LENGTH_LONG
        ).show()
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
            status.text = "$detail\n\nConfirm JARVIS call routing is enabled and enable J.A.R.V.I.S. in calling-account settings. Keep your SIM as the default outgoing account."
            Toast.makeText(this, detail, Toast.LENGTH_LONG).show()
        } catch (error: Exception) {
            android.util.Log.e("JARVIS-CONTACT", "Could not create JARVIS contact", error)
            Toast.makeText(this, "Could not set up the JARVIS contact: ${error.javaClass.simpleName}", Toast.LENGTH_LONG).show()
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
        if (requestCode == redirectionRoleRequest) {
            val roles = getSystemService(Context.ROLE_SERVICE) as RoleManager
            val enabled = roles.isRoleHeld(RoleManager.ROLE_CALL_REDIRECTION)
            status.text = if (enabled) {
                "JARVIS call routing enabled. Calls to the JARVIS contact will be handed to its local calling account."
            } else {
                "Call routing was not enabled. The JARVIS virtual number must not be called until routing is enabled."
            }
            Toast.makeText(this, if (enabled) "JARVIS call routing enabled." else "JARVIS call routing not enabled.", Toast.LENGTH_LONG).show()
            return
        }
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