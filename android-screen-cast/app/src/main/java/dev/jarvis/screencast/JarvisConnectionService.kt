package dev.jarvis.screencast

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.telecom.Connection
import android.telecom.ConnectionRequest
import android.telecom.ConnectionService
import android.telecom.DisconnectCause
import android.telecom.PhoneAccount
import android.telecom.PhoneAccountHandle
import android.telecom.TelecomManager
import java.util.UUID

/**
 * System-managed JARVIS VoIP provider.
 *
 * The stock Phone app handles calls. ContactsContract's preferred-account
 * fields route the JARVIS contact to this provider without changing the
 * user's default SIM account or showing an account chooser on each call.
 */
class JarvisConnectionService : ConnectionService() {
    companion object {
        const val EXTRA_MESSAGE = "dev.jarvis.screencast.owner.MESSAGE"
        const val EXTRA_REASON = "dev.jarvis.screencast.owner.REASON"
        private const val ACCOUNT_ID = "jarvis-local-owner"
        private const val PREFS = "jarvis_owner_calls"
        private const val TOKEN_KEY = "audio_token"

        @Volatile var activeConnection: OwnerConnection? = null

        fun accountHandle(context: Context): PhoneAccountHandle =
            PhoneAccountHandle(ComponentName(context, JarvisConnectionService::class.java), ACCOUNT_ID)

        fun registerAccount(context: Context) {
            val telecom = context.getSystemService(Context.TELECOM_SERVICE) as TelecomManager
            val account = PhoneAccount.builder(accountHandle(context), "J.A.R.V.I.S.")
                .setCapabilities(PhoneAccount.CAPABILITY_CALL_PROVIDER)
                .setSupportedUriSchemes(listOf(PhoneAccount.SCHEME_TEL))
                .setShortDescription("Local JARVIS voice assistant")
                .build()
            telecom.registerPhoneAccount(account)
        }

        fun isAccountEnabled(context: Context): Boolean {
            val telecom = context.getSystemService(Context.TELECOM_SERVICE) as TelecomManager
            return telecom.callCapablePhoneAccounts.contains(accountHandle(context))
        }

        fun incomingCall(context: Context, message: String, reason: String): Boolean {
            return try {
                registerAccount(context)
                val extras = Bundle().apply {
                    putString(EXTRA_MESSAGE, message.take(1200))
                    putString(EXTRA_REASON, reason.take(100))
                }
                val telecom = context.getSystemService(Context.TELECOM_SERVICE) as TelecomManager
                telecom.addNewIncomingCall(accountHandle(context), extras)
                true
            } catch (error: Exception) {
                android.util.Log.e("JARVIS-CALL", "Could not report incoming call to Telecom", error)
                false
            }
        }

        fun audioToken(context: Context): String {
            val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            val existing = prefs.getString(TOKEN_KEY, null)
            if (!existing.isNullOrBlank()) return existing
            val created = UUID.randomUUID().toString().replace("-", "") + UUID.randomUUID().toString().replace("-", "")
            prefs.edit().putString(TOKEN_KEY, created).apply()
            return created
        }

        fun startAudio(context: Context, initialMessage: String) {
            OwnerCallAudioService.start(context, initialMessage)
        }

        fun stopAudio(context: Context) {
            OwnerCallAudioService.stop(context)
        }

        fun onAudioReady() {
            activeConnection?.let { connection ->
                if (connection.state == Connection.STATE_DIALING ||
                    connection.state == Connection.STATE_RINGING) {
                    connection.setActive()
                }
            }
        }

        fun onAudioFailed() {
            activeConnection?.let { connection ->
                connection.setDisconnected(DisconnectCause(DisconnectCause.ERROR))
                connection.destroy()
                activeConnection = null
            }
        }
    }

    override fun onCreateIncomingConnection(
        connectionManagerPhoneAccount: PhoneAccountHandle?,
        request: ConnectionRequest
    ): Connection {
        val message = request.extras?.getString(EXTRA_MESSAGE)
            .orEmpty().ifBlank { "JARVIS has an update." }
        return OwnerConnection(this, message, incoming = true).also {
            activeConnection = it
        }
    }

    override fun onCreateOutgoingConnection(
        connectionManagerPhoneAccount: PhoneAccountHandle?,
        request: ConnectionRequest
    ): Connection {
        val address = request.address
        val dialString = address?.schemeSpecificPart.orEmpty()
        val normalizedNumber = dialString.filter { it.isDigit() }
        val isJarvisDestination = normalizedNumber == "12025550147" || normalizedNumber == "2025550147"
        val connection = OwnerConnection(this, "Hello. J.A.R.V.I.S. is ready. How can I help?", incoming = false)
        activeConnection = connection
        if (address?.scheme != PhoneAccount.SCHEME_TEL || !isJarvisDestination) {
            connection.setDisconnected(DisconnectCause(DisconnectCause.ERROR))
            connection.destroy()
            activeConnection = null
            return connection
        }
        connection.setAddress(Uri.fromParts(PhoneAccount.SCHEME_TEL, "+12025550147", null),
            TelecomManager.PRESENTATION_ALLOWED)
        Handler(Looper.getMainLooper()).postDelayed({
            if (activeConnection === connection && connection.state == Connection.STATE_DIALING) {
                startAudio(this, connection.message)
            }
        }, 300L)
        return connection
    }

    override fun onCreateOutgoingConnectionFailed(
        connectionManagerPhoneAccount: PhoneAccountHandle?,
        request: ConnectionRequest
    ) {
        super.onCreateOutgoingConnectionFailed(connectionManagerPhoneAccount, request)
        android.util.Log.w("JARVIS-CALL", "The Phone app could not create a JARVIS call.")
    }

    override fun onCreateIncomingConnectionFailed(
        connectionManagerPhoneAccount: PhoneAccountHandle?,
        request: ConnectionRequest
    ) {
        super.onCreateIncomingConnectionFailed(connectionManagerPhoneAccount, request)
        android.util.Log.w("JARVIS-CALL", "Telecom could not deliver the incoming JARVIS call.")
    }

    class OwnerConnection(
        private val appContext: Context,
        val message: String,
        val incoming: Boolean
    ) : Connection() {
        init {
            setCallerDisplayName("J.A.R.V.I.S.", TelecomManager.PRESENTATION_ALLOWED)
            setAddress(Uri.fromParts(PhoneAccount.SCHEME_TEL, "+12025550147", null),
                TelecomManager.PRESENTATION_ALLOWED)
            setAudioModeIsVoip(true)
            setConnectionProperties(0)
            if (incoming) setRinging() else setDialing()
        }

        override fun onAnswer() {
            startAudio(appContext, message)
        }

        override fun onAnswer(videoState: Int) {
            startAudio(appContext, message)
        }

        override fun onReject() {
            finish(DisconnectCause.REJECTED)
        }

        override fun onDisconnect() {
            finish(DisconnectCause.LOCAL)
        }

        override fun onAbort() {
            finish(DisconnectCause.CANCELED)
        }

        private fun finish(code: Int) {
            stopAudio(appContext)
            if (state != STATE_DISCONNECTED) {
                setDisconnected(DisconnectCause(code))
                destroy()
            }
            if (activeConnection === this) activeConnection = null
        }
    }
}
