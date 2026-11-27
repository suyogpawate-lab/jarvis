package dev.jarvis.screencast

import android.content.ComponentName
import android.content.Context
import android.net.Uri
import android.os.Bundle
import android.telecom.Connection
import android.telecom.ConnectionRequest
import android.telecom.ConnectionService
import android.telecom.DisconnectCause
import android.telecom.PhoneAccount
import android.telecom.PhoneAccountHandle
import android.telecom.TelecomManager
import java.util.UUID

/**
 * JARVIS is a local Phone-app call provider only.
 *
 * It deliberately does NOT register as CAPABILITY_CONNECTION_MANAGER and
 * never intercepts/proxies carrier SIM calls. The previous SIM-call-manager
 * proxy path could destabilize Telecom on some Android 10 vendor builds.
 * Ordinary calls must remain owned by Android's selected SIM account.
 */
class JarvisConnectionService : ConnectionService() {
    companion object {
        const val EXTRA_MESSAGE = "dev.jarvis.screencast.owner.MESSAGE"
        const val EXTRA_REASON = "dev.jarvis.screencast.owner.REASON"
        private const val ACCOUNT_ID = "jarvis-local-owner"
        private const val PREFS = "jarvis_owner_calls"
        private const val TOKEN_KEY = "audio_token"
        private const val JARVIS_NANP = "12025550147"
        private const val JARVIS_LOCAL = "2025550147"

        @Volatile var activeConnection: OwnerConnection? = null

        fun accountHandle(context: Context): PhoneAccountHandle =
            PhoneAccountHandle(ComponentName(context, JarvisConnectionService::class.java), ACCOUNT_ID)

        fun registerAccount(context: Context) {
            val telecom = context.getSystemService(Context.TELECOM_SERVICE) as TelecomManager
            // IMPORTANT: CALL_PROVIDER only. Never claim CONNECTION_MANAGER:
            // this app must not sit in the carrier SIM call path.
            val account = PhoneAccount.builder(accountHandle(context), "J.A.R.V.I.S.")
                .setCapabilities(PhoneAccount.CAPABILITY_CALL_PROVIDER)
                .setSupportedUriSchemes(listOf(PhoneAccount.SCHEME_TEL))
                .setShortDescription("Local JARVIS voice assistant")
                .build()
            telecom.registerPhoneAccount(account)
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
                android.util.Log.e("JARVIS-CALL", "Could not report local incoming call to Telecom", error)
                false
            }
        }

        fun audioToken(context: Context): String {
            val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            val existing = prefs.getString(TOKEN_KEY, null)
            if (!existing.isNullOrBlank()) return existing
            val created = UUID.randomUUID().toString().replace("-", "") +
                UUID.randomUUID().toString().replace("-", "")
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
        // A non-null manager handle means Android is trying to route a carrier
        // call through this app. Refuse safely rather than proxying SIM calls.
        if (connectionManagerPhoneAccount != null) {
            android.util.Log.e("JARVIS-CALL", "Refusing SIM call-manager routing; JARVIS is local-call-only.")
            return Connection.createFailedConnection(DisconnectCause(DisconnectCause.ERROR))
        }

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
        if (connectionManagerPhoneAccount != null) {
            android.util.Log.e("JARVIS-CALL", "Refusing SIM call-manager routing; JARVIS is local-call-only.")
            return Connection.createFailedConnection(DisconnectCause(DisconnectCause.ERROR))
        }

        val address = request.address
        val dialString = address?.schemeSpecificPart.orEmpty()
        val normalizedNumber = dialString.filter { it.isDigit() }
        val isJarvisDestination =
            normalizedNumber == JARVIS_NANP || normalizedNumber == JARVIS_LOCAL

        if (!isJarvisDestination || address?.scheme != PhoneAccount.SCHEME_TEL) {
            android.util.Log.w("JARVIS-CALL", "Refusing non-JARVIS destination on the local-only call account.")
            return Connection.createFailedConnection(DisconnectCause(DisconnectCause.ERROR))
        }

        val connection = OwnerConnection(
            this,
            "Hello. J.A.R.V.I.S. is ready. How can I help?",
            incoming = false
        )
        activeConnection = connection
        connection.setAddress(
            Uri.fromParts(PhoneAccount.SCHEME_TEL, "+12025550147", null),
            TelecomManager.PRESENTATION_ALLOWED
        )
        android.os.Handler(android.os.Looper.getMainLooper()).postDelayed({
            if (activeConnection === connection && connection.state == Connection.STATE_DIALING) {
                startAudio(this, connection.message)
            }
        }, 300L)
        android.util.Log.i("JARVIS-CALL", "Handling JARVIS destination locally; carrier SIM is not used.")
        return connection
    }

    override fun onCreateOutgoingConnectionFailed(
        connectionManagerPhoneAccount: PhoneAccountHandle?,
        request: ConnectionRequest
    ) {
        super.onCreateOutgoingConnectionFailed(connectionManagerPhoneAccount, request)
        android.util.Log.w("JARVIS-CALL", "Telecom could not create the local JARVIS outgoing connection.")
    }

    override fun onCreateIncomingConnectionFailed(
        connectionManagerPhoneAccount: PhoneAccountHandle?,
        request: ConnectionRequest
    ) {
        super.onCreateIncomingConnectionFailed(connectionManagerPhoneAccount, request)
        android.util.Log.w("JARVIS-CALL", "Telecom could not create the local JARVIS incoming connection.")
    }

    class OwnerConnection(
        private val appContext: Context,
        val message: String,
        val incoming: Boolean
    ) : Connection() {
        init {
            setCallerDisplayName("J.A.R.V.I.S.", TelecomManager.PRESENTATION_ALLOWED)
            setAddress(
                Uri.fromParts(PhoneAccount.SCHEME_TEL, "+$JARVIS_NANP", null),
                TelecomManager.PRESENTATION_ALLOWED
            )
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
