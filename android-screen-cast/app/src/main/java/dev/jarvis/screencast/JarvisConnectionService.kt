package dev.jarvis.screencast

import android.content.ComponentName
import android.content.Context
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.telecom.CallAudioState
import android.telecom.Connection
import android.telecom.ConnectionRequest
import android.telecom.ConnectionService
import android.telecom.DisconnectCause
import android.telecom.PhoneAccount
import android.telecom.PhoneAccountHandle
import android.telecom.RemoteConnection
import android.telecom.StatusHints
import android.telecom.TelecomManager
import java.util.UUID

/**
 * JARVIS is both a local call provider and an optional SIM call manager.
 *
 * When selected by the user as the SIM call manager, Telecom sends outgoing
 * SIM calls here first. The reserved JARVIS contact is handled locally;
 * every other call is proxied to the originally selected SIM account through
 * createRemoteOutgoingConnection(). Incoming SIM calls are proxied likewise.
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
            val account = PhoneAccount.builder(accountHandle(context), "J.A.R.V.I.S.")
                .setCapabilities(
                    PhoneAccount.CAPABILITY_CALL_PROVIDER or
                        PhoneAccount.CAPABILITY_CONNECTION_MANAGER
                )
                .setSupportedUriSchemes(listOf(PhoneAccount.SCHEME_TEL))
                .setShortDescription("Local JARVIS voice assistant and SIM call manager")
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
                android.util.Log.e("JARVIS-CALL", "Could not report incoming call to Telecom", error)
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
        val isJarvisAccount = request.accountHandle == accountHandle(this)
        if (connectionManagerPhoneAccount != null && !isJarvisAccount) {
            android.util.Log.i("JARVIS-CALL", "Proxying incoming SIM call through the selected SIM call manager.")
            return proxyRemoteConnection(
                createRemoteIncomingConnection(connectionManagerPhoneAccount, request),
                "Could not proxy incoming SIM call"
            )
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
        val address = request.address
        val dialString = address?.schemeSpecificPart.orEmpty()
        val normalizedNumber = dialString.filter { it.isDigit() }
        val isJarvisDestination =
            normalizedNumber == JARVIS_NANP || normalizedNumber == JARVIS_LOCAL

        if (isJarvisDestination) {
            if (address?.scheme != PhoneAccount.SCHEME_TEL) {
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
            Handler(Looper.getMainLooper()).postDelayed({
                if (activeConnection === connection && connection.state == Connection.STATE_DIALING) {
                    startAudio(this, connection.message)
                }
            }, 300L)
            android.util.Log.i("JARVIS-CALL", "Handling JARVIS destination locally; no SIM call is created.")
            return connection
        }

        if (connectionManagerPhoneAccount != null) {
            android.util.Log.i("JARVIS-CALL", "Proxying ordinary outgoing call to the originally selected SIM account.")
            return proxyRemoteConnection(
                createRemoteOutgoingConnection(connectionManagerPhoneAccount, request),
                "Could not proxy outgoing SIM call"
            )
        }

        android.util.Log.e("JARVIS-CALL", "Ordinary outgoing call reached JARVIS without a SIM call-manager request; refusing to reroute it.")
        return Connection.createFailedConnection(DisconnectCause(DisconnectCause.ERROR))
    }

    private fun proxyRemoteConnection(remote: RemoteConnection?, failureMessage: String): Connection {
        if (remote == null) {
            android.util.Log.e("JARVIS-CALL", failureMessage + ": Telecom returned no RemoteConnection.")
            return Connection.createFailedConnection(DisconnectCause(DisconnectCause.ERROR))
        }
        if (remote.state == Connection.STATE_DISCONNECTED) {
            android.util.Log.e("JARVIS-CALL", failureMessage + ": " + remote.disconnectCause)
            return Connection.createFailedConnection(
                remote.disconnectCause ?: DisconnectCause(DisconnectCause.ERROR)
            )
        }
        return SimCallProxyConnection(remote)
    }

    override fun onCreateOutgoingConnectionFailed(
        connectionManagerPhoneAccount: PhoneAccountHandle?,
        request: ConnectionRequest
    ) {
        super.onCreateOutgoingConnectionFailed(connectionManagerPhoneAccount, request)
        android.util.Log.w("JARVIS-CALL", "Telecom could not create an outgoing connection.")
    }

    override fun onCreateIncomingConnectionFailed(
        connectionManagerPhoneAccount: PhoneAccountHandle?,
        request: ConnectionRequest
    ) {
        super.onCreateIncomingConnectionFailed(connectionManagerPhoneAccount, request)
        android.util.Log.w("JARVIS-CALL", "Telecom could not create an incoming connection.")
    }

    /**
     * Mirrors a RemoteConnection into the local Connection returned to Telecom.
     * User controls and audio-state changes are forwarded to the real SIM call.
     */
    private class SimCallProxyConnection(
        private val remote: RemoteConnection
    ) : Connection() {
        private var finished = false

        private val callback = object : RemoteConnection.Callback() {
            override fun onStateChanged(connection: RemoteConnection, state: Int) {
                syncState(state)
            }

            override fun onDisconnected(
                connection: RemoteConnection,
                disconnectCause: DisconnectCause
            ) {
                finish(disconnectCause)
            }

            override fun onDestroyed(connection: RemoteConnection) {
                finish(connection.disconnectCause ?: DisconnectCause(DisconnectCause.ERROR))
            }

            override fun onAddressChanged(
                connection: RemoteConnection,
                address: Uri,
                presentation: Int
            ) {
                setAddress(address, presentation)
            }

            override fun onCallerDisplayNameChanged(
                connection: RemoteConnection,
                callerDisplayName: String,
                presentation: Int
            ) {
                setCallerDisplayName(callerDisplayName, presentation)
            }

            override fun onConnectionCapabilitiesChanged(
                connection: RemoteConnection,
                connectionCapabilities: Int
            ) {
                setConnectionCapabilities(connectionCapabilities)
            }

            override fun onConnectionPropertiesChanged(
                connection: RemoteConnection,
                connectionProperties: Int
            ) {
                setConnectionProperties(connectionProperties)
            }

            override fun onStatusHintsChanged(connection: RemoteConnection, statusHints: StatusHints) {
                setStatusHints(statusHints)
            }

            override fun onRingbackRequested(connection: RemoteConnection, ringback: Boolean) {
                setRingbackRequested(ringback)
            }

            override fun onVoipAudioChanged(connection: RemoteConnection, isVoip: Boolean) {
                setAudioModeIsVoip(isVoip)
            }

            override fun onExtrasChanged(connection: RemoteConnection, extras: Bundle?) {
                if (extras != null) setExtras(extras)
            }

            override fun onPostDialChar(connection: RemoteConnection, nextChar: Char) {
                setNextPostDialChar(nextChar)
            }

            override fun onPostDialWait(connection: RemoteConnection, remainingPostDialSequence: String) {
                setPostDialWait(remainingPostDialSequence)
            }
        }

        init {
            setAddress(remote.address, remote.addressPresentation)
            setCallerDisplayName(
                remote.callerDisplayName?.toString(),
                remote.callerDisplayNamePresentation
            )
            setConnectionCapabilities(remote.connectionCapabilities)
            setConnectionProperties(remote.connectionProperties)
            setStatusHints(remote.statusHints)
            setAudioModeIsVoip(remote.isVoipAudioMode)
            setRingbackRequested(remote.isRingbackRequested)
            remote.extras?.let { setExtras(it) }
            remote.registerCallback(callback)
            syncState(remote.state)
        }

        private fun syncState(remoteState: Int) {
            if (finished) return
            when (remoteState) {
                STATE_INITIALIZING -> setInitializing()
                STATE_NEW -> setInitialized()
                STATE_RINGING -> setRinging()
                STATE_DIALING -> setDialing()
                STATE_ACTIVE -> setActive()
                STATE_HOLDING -> setOnHold()
                STATE_DISCONNECTED -> finish(
                    remote.disconnectCause ?: DisconnectCause(DisconnectCause.ERROR)
                )
            }
        }

        private fun finish(cause: DisconnectCause) {
            if (finished) return
            finished = true
            if (state != STATE_DISCONNECTED) setDisconnected(cause)
            remote.unregisterCallback(callback)
            destroy()
        }

        override fun onAnswer() {
            remote.answer()
        }

        override fun onReject() {
            remote.reject()
        }

        override fun onDisconnect() {
            remote.disconnect()
        }

        override fun onHold() {
            remote.hold()
        }

        override fun onUnhold() {
            remote.unhold()
        }

        override fun onAbort() {
            remote.abort()
        }

        override fun onPlayDtmfTone(digit: Char) {
            remote.playDtmfTone(digit)
        }

        override fun onStopDtmfTone() {
            remote.stopDtmfTone()
        }

        override fun onPostDialContinue(proceed: Boolean) {
            remote.postDialContinue(proceed)
        }

        override fun onCallAudioStateChanged(state: CallAudioState) {
            remote.setCallAudioState(state)
        }

        override fun onDestroy() {
            if (!finished) {
                finished = true
                remote.unregisterCallback(callback)
            }
            super.onDestroy()
        }
    }

    class OwnerConnection(
        private val appContext: Context,
        val message: String,
        val incoming: Boolean
    ) : Connection() {
        init {
            setCallerDisplayName("J.A.R.V.I.S.", TelecomManager.PRESENTATION_ALLOWED)
            setAddress(
                Uri.fromParts(PhoneAccount.SCHEME_TEL, "+" + JARVIS_NANP, null),
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
