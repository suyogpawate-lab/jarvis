package dev.jarvis.screencast

import android.net.Uri
import android.telecom.CallRedirectionService
import android.telecom.PhoneAccountHandle
import android.telecom.TelecomManager

/**
 * Intercepts outgoing calls only to JARVIS's reserved virtual contact number.
 *
 * All unrelated destinations are passed through unchanged. For the JARVIS
 * destination, Telecom is instructed to use the registered local JARVIS
 * ConnectionService PhoneAccount instead of the initially selected SIM.
 */
class JarvisCallRedirectionService : CallRedirectionService() {
    override fun onPlaceCall(
        handle: Uri,
        initialPhoneAccount: PhoneAccountHandle,
        allowInteractiveResponse: Boolean
    ) {
        val digits = handle.schemeSpecificPart.orEmpty().filter { it.isDigit() }
        val isJarvisNumber = digits == "12025550147" || digits == "2025550147"

        if (!isJarvisNumber) {
            placeCallUnmodified()
            return
        }

        val jarvisAccount = JarvisConnectionService.accountHandle(this)
        val telecom = getSystemService(TELECOM_SERVICE) as TelecomManager
        if (!telecom.callCapablePhoneAccounts.contains(jarvisAccount)) {
            // Fail closed: never let this virtual number fall through to the SIM.
            android.util.Log.e("JARVIS-CALL", "JARVIS account is disabled; canceling virtual-number call.")
            cancelCall()
            return
        }

        android.util.Log.i("JARVIS-CALL", "Routing JARVIS virtual-number call to the local PhoneAccount.")
        redirectCall(handle, jarvisAccount, false)
    }
}