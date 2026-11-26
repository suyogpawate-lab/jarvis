package dev.jarvis.screencast

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.AudioTrack
import android.media.MediaRecorder
import android.media.audiofx.AcousticEchoCanceler
import android.os.Build
import android.os.IBinder
import org.json.JSONObject
import java.io.BufferedInputStream
import java.net.InetSocketAddress
import java.net.Socket
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread

/**
 * Full-duplex PCM transport between Android Telecom audio and the local Termux
 * JARVIS process. The Android Phone app owns the call UI; this service owns
 * microphone capture and downlink playback only while a Telecom call is active.
 */
class OwnerCallAudioService : Service() {
    companion object {
        const val ACTION_START = "dev.jarvis.screencast.owner.AUDIO_START"
        const val ACTION_STOP = "dev.jarvis.screencast.owner.AUDIO_STOP"
        private const val CHANNEL = "jarvis_call_audio"
        private const val NOTIFICATION_ID = 21344
        private const val RATE = 16000
        private const val FRAME_BYTES = 640

        fun start(context: Context, initialMessage: String) {
            val intent = Intent(context, OwnerCallAudioService::class.java).apply {
                action = ACTION_START
                putExtra("initial_message", initialMessage.take(1200))
            }
            if (Build.VERSION.SDK_INT >= 26) context.startForegroundService(intent) else context.startService(intent)
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, OwnerCallAudioService::class.java))
        }
    }

    private val running = AtomicBoolean(false)
    @Volatile private var socket: Socket? = null
    @Volatile private var initialMessage: String = ""
    @Volatile private var recorder: AudioRecord? = null
    @Volatile private var player: AudioTrack? = null
    @Volatile private var echoCanceler: AcousticEchoCanceler? = null

    override fun onCreate() {
        super.onCreate()
        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= 26) {
            manager.createNotificationChannel(NotificationChannel(
                CHANNEL, "JARVIS call audio", NotificationManager.IMPORTANCE_LOW
            ))
        }
        val notification = if (Build.VERSION.SDK_INT >= 26) Notification.Builder(this, CHANNEL)
            else Notification.Builder(this)
        startForeground(NOTIFICATION_ID, notification
            .setSmallIcon(android.R.drawable.sym_call_incoming)
            .setContentTitle("J.A.R.V.I.S. call active")
            .setContentText("Local two-way voice connection")
            .setOngoing(true).build())
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            stopSelf()
            return START_NOT_STICKY
        }
        initialMessage = intent?.getStringExtra("initial_message").orEmpty()
        if (running.compareAndSet(false, true)) {
            val greeting = initialMessage
            thread(name = "JarvisCallAudio", isDaemon = true) { runAudioSession(greeting) }
        }
        return START_NOT_STICKY
    }

    private fun readLine(input: BufferedInputStream, maxBytes: Int = 2048): String {
        val bytes = ArrayList<Byte>()
        while (bytes.size < maxBytes) {
            val value = input.read()
            if (value < 0 || value == 10) break
            if (value != 13) bytes.add(value.toByte())
        }
        return bytes.toByteArray().toString(Charsets.UTF_8)
    }

    private fun readExactly(input: BufferedInputStream, buffer: ByteArray): Boolean {
        var offset = 0
        while (offset < buffer.size && running.get()) {
            val count = input.read(buffer, offset, buffer.size - offset)
            if (count < 0) return false
            offset += count
        }
        return offset == buffer.size
    }

    private fun runAudioSession(greeting: String) {
        try {
            val token = JarvisConnectionService.audioToken(this)
            val connection = Socket()
            socket = connection
            connection.tcpNoDelay = true
            connection.connect(InetSocketAddress("127.0.0.1", 21344), 7000)
            val socketInput = BufferedInputStream(connection.getInputStream())
            val socketOutput = connection.getOutputStream()
            val hello = JSONObject().put("token", token).put("protocol", 1).put("initial_message", greeting).toString() + "\n"
            socketOutput.write(hello.toByteArray(Charsets.UTF_8))
            socketOutput.flush()
            val response = JSONObject(readLine(socketInput))
            if (!response.optBoolean("ok")) throw IllegalStateException(response.optString("error", "call bridge rejected connection"))

            val minIn = AudioRecord.getMinBufferSize(
                RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT
            )
            if (minIn <= 0) throw IllegalStateException("AudioRecord is unavailable: $minIn")
            val record = AudioRecord(
                MediaRecorder.AudioSource.VOICE_COMMUNICATION,
                RATE,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
                maxOf(minIn, FRAME_BYTES * 8)
            )
            recorder = record
            if (record.state != AudioRecord.STATE_INITIALIZED) throw IllegalStateException("Microphone could not be initialized")
            if (AcousticEchoCanceler.isAvailable()) {
                echoCanceler = AcousticEchoCanceler.create(record.audioSessionId)?.apply { enabled = true }
            }

            val minOut = AudioTrack.getMinBufferSize(
                RATE, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT
            )
            if (minOut <= 0) throw IllegalStateException("AudioTrack is unavailable: $minOut")
            val track = AudioTrack.Builder()
                .setAudioAttributes(AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_VOICE_COMMUNICATION)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                    .build())
                .setAudioFormat(AudioFormat.Builder()
                    .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                    .setSampleRate(RATE)
                    .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                    .build())
                .setBufferSizeInBytes(maxOf(minOut, FRAME_BYTES * 8))
                .setTransferMode(AudioTrack.MODE_STREAM)
                .build()
            player = track
            if (track.state != AudioTrack.STATE_INITIALIZED) throw IllegalStateException("Call audio output could not be initialized")

            record.startRecording()
            track.play()
            JarvisConnectionService.onAudioReady()
            android.util.Log.i("JARVIS-CALL", "Local full-duplex audio connected")

            val microphoneThread = thread(name = "JarvisCallMic", isDaemon = true) {
                val frame = ByteArray(FRAME_BYTES)
                while (running.get()) {
                    val count = try { record.read(frame, 0, frame.size, AudioRecord.READ_BLOCKING) }
                    catch (_: Exception) { -1 }
                    if (count <= 0) {
                        if (running.get()) JarvisConnectionService.onAudioFailed()
                        break
                    }
                    if (count < frame.size) java.util.Arrays.fill(frame, count, frame.size, 0.toByte())
                    try {
                        socketOutput.write(frame)
                        socketOutput.flush()
                    } catch (_: Exception) {
                        if (running.get()) JarvisConnectionService.onAudioFailed()
                        break
                    }
                }
                running.set(false)
                try { connection.shutdownOutput() } catch (_: Exception) {}
            }

            val downlink = ByteArray(FRAME_BYTES)
            while (running.get() && readExactly(socketInput, downlink)) {
                var offset = 0
                while (offset < downlink.size && running.get()) {
                    val written = track.write(downlink, offset, downlink.size - offset, AudioTrack.WRITE_BLOCKING)
                    if (written <= 0) break
                    offset += written
                }
            }
            if (running.get()) JarvisConnectionService.onAudioFailed()
            running.set(false)
            try { microphoneThread.join(500) } catch (_: InterruptedException) {}
        } catch (error: Exception) {
            if (running.get()) {
                android.util.Log.e("JARVIS-CALL", "Call audio transport failed", error)
                JarvisConnectionService.onAudioFailed()
            }
        } finally {
            running.set(false)
            try { recorder?.stop() } catch (_: Exception) {}
            try { recorder?.release() } catch (_: Exception) {}
            recorder = null
            try { player?.pause() } catch (_: Exception) {}
            try { player?.flush() } catch (_: Exception) {}
            try { player?.release() } catch (_: Exception) {}
            player = null
            try { echoCanceler?.release() } catch (_: Exception) {}
            echoCanceler = null
            try { socket?.close() } catch (_: Exception) {}
            socket = null
            stopSelf()
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        running.set(false)
        try { socket?.close() } catch (_: Exception) {}
        try { recorder?.stop() } catch (_: Exception) {}
        try { player?.pause() } catch (_: Exception) {}
        stopForeground(true)
        super.onDestroy()
    }
}
