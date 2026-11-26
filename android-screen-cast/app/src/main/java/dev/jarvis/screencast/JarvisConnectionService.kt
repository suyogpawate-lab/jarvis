package dev.jarvis.screencast

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.media.AudioAttributes
import android.media.RingtoneManager
import android.os.Bundle
import android.telecom.Connection
import android.telecom.ConnectionRequest
import android.telecom.ConnectionService
import android.telecom.DisconnectCause
import android.telecom.PhoneAccount
import android.telecom.PhoneAccountHandle
import android.telecom.TelecomManager

class JarvisConnectionService : ConnectionService() {
    companion object {
        const val EXTRA_MESSAGE = "dev.jarvis.screencast.owner.MESSAGE"
        const val EXTRA_REASON = "dev.jarvis.screencast.owner.REASON"
        private const val ACCOUNT_ID = "jarvis-local-owner"
        private const val CHANNEL_ID = "jarvis_owner_calls"
        private const val NOTIFICATION_ID = 21342
        @Volatile var activeConnection: OwnerConnection? = null
        @Volatile var activeMessage: String = "JARVIS has an update."

        fun accountHandle(context: Context): PhoneAccountHandle =
            PhoneAccountHandle(ComponentName(context, JarvisConnectionService::class.java), ACCOUNT_ID)

        fun registerAccount(context: Context) {
            val telecom = context.getSystemService(Context.TELECOM_SERVICE) as TelecomManager
            val handle = accountHandle(context)
            val account = PhoneAccount.builder(handle, "J.A.R.V.I.S. Local")
                .setCapabilities(PhoneAccount.CAPABILITY_SELF_MANAGED)
                .setShortDescription("Local JARVIS assistant calls")
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
                android.util.Log.e("JARVIS-CALL", "Could not register local incoming call", error)
                false
            }
        }

        fun showIncomingUi(context: Context, message: String) {
            activeMessage = message.ifBlank { "JARVIS has an update." }
            val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            if (android.os.Build.VERSION.SDK_INT >= 26) {
                manager.createNotificationChannel(NotificationChannel(
                    CHANNEL_ID, "JARVIS owner calls", NotificationManager.IMPORTANCE_HIGH
                ).apply {
                    description = "Local calls from JARVIS"
                    setSound(
                        RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE),
                        AudioAttributes.Builder()
                            .setUsage(AudioAttributes.USAGE_NOTIFICATION_RINGTONE)
                            .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                            .build()
                    )
                })
            }
            val open = Intent(context, IncomingCallActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            }
            val pending = PendingIntent.getActivity(
                context, 21342, open,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
            val builder = if (android.os.Build.VERSION.SDK_INT >= 26)
                Notification.Builder(context, CHANNEL_ID) else Notification.Builder(context)
            val notification = builder
                .setSmallIcon(android.R.drawable.sym_call_incoming)
                .setContentTitle("J.A.R.V.I.S.")
                .setContentText(activeMessage.take(120))
                .setCategory(Notification.CATEGORY_CALL)
                .setPriority(Notification.PRIORITY_MAX)
                .setFullScreenIntent(pending, true)
                .setContentIntent(pending)
                .setOngoing(true)
                .build().apply { flags = flags or Notification.FLAG_INSISTENT }
            manager.notify(NOTIFICATION_ID, notification)
        }

        fun clearIncomingUi(context: Context) {
            (context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager)
                .cancel(NOTIFICATION_ID)
        }
    }

    override fun onCreateIncomingConnection(
        connectionManagerPhoneAccount: PhoneAccountHandle?,
        request: ConnectionRequest
    ): Connection {
        val extras = request.extras
        val message = extras?.getString(EXTRA_MESSAGE).orEmpty().ifBlank { "JARVIS has an update." }
        activeMessage = message
        return OwnerConnection(this, message).also { activeConnection = it }
    }

    override fun onCreateIncomingConnectionFailed(
        connectionManagerPhoneAccount: PhoneAccountHandle?,
        request: ConnectionRequest
    ) {
        super.onCreateIncomingConnectionFailed(connectionManagerPhoneAccount, request)
        android.util.Log.w("JARVIS-CALL", "Telecom rejected an incoming local call")
    }

    class OwnerConnection(private val appContext: Context, val message: String) : Connection() {
        init {
            setCallerDisplayName("J.A.R.V.I.S.", TelecomManager.PRESENTATION_ALLOWED)
            setAddress(Uri.EMPTY, TelecomManager.PRESENTATION_ALLOWED)
            setAudioModeIsVoip(true)
            setConnectionProperties(PROPERTY_SELF_MANAGED)
            setRinging()
        }

        override fun onShowIncomingCallUi() {
            showIncomingUi(appContext, message)
        }

        override fun onAnswer() {
            setActive()
            clearIncomingUi(appContext)
            val intent = Intent(appContext, IncomingCallActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            }
            appContext.startActivity(intent)
        }

        override fun onAnswer(videoState: Int) = onAnswer()

        override fun onReject() {
            setDisconnected(DisconnectCause(DisconnectCause.REJECTED))
            destroy()
            clearIncomingUi(appContext)
            activeConnection = null
        }

        override fun onDisconnect() {
            setDisconnected(DisconnectCause(DisconnectCause.LOCAL))
            destroy()
            clearIncomingUi(appContext)
            activeConnection = null
        }
    }
}
