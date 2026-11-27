package dev.jarvis.screencast

import android.content.ContentProviderOperation
import android.content.ContentUris
import android.content.ContentValues
import android.content.Context
import android.provider.ContactsContract
import android.provider.ContactsContract.CommonDataKinds.Phone
import android.provider.ContactsContract.CommonDataKinds.StructuredName

/**
 * Creates/updates a real Phone contact whose preferred Telecom account is
 * JARVIS. The contact uses tel:0 so both a dial-pad "0" and a contact lookup
 * for "JARVIS" resolve to the same local ConnectionService.
 */
object JarvisContact {
    private const val CONTACT_NAME = "JARVIS"
    private const val LOCAL_NUMBER = "0"

    /** @return true when a new contact was inserted, false when an existing one was updated. */
    fun ensure(context: Context): Boolean {
        JarvisConnectionService.registerAccount(context)
        val handle = JarvisConnectionService.accountHandle(context)
        val componentName = handle.componentName.flattenToString()
        val accountId = handle.id
        val resolver = context.contentResolver

        val projection = arrayOf(Phone._ID)
        val selection = "${Phone.DISPLAY_NAME} = ? AND ${Phone.NUMBER} = ?"
        val cursor = resolver.query(
            Phone.CONTENT_URI,
            projection,
            selection,
            arrayOf(CONTACT_NAME, LOCAL_NUMBER),
            null
        )
        cursor?.use {
            if (it.moveToFirst()) {
                val dataId = it.getLong(0)
                val values = ContentValues().apply {
                    put(ContactsContract.Data.PREFERRED_PHONE_ACCOUNT_COMPONENT_NAME, componentName)
                    put(ContactsContract.Data.PREFERRED_PHONE_ACCOUNT_ID, accountId)
                }
                resolver.update(
                    ContentUris.withAppendedId(ContactsContract.Data.CONTENT_URI, dataId),
                    values,
                    null,
                    null
                )
                return false
            }
        }

        val operations = arrayListOf(
            ContentProviderOperation.newInsert(ContactsContract.RawContacts.CONTENT_URI)
                .withValue(ContactsContract.RawContacts.ACCOUNT_NAME, null)
                .withValue(ContactsContract.RawContacts.ACCOUNT_TYPE, null)
                .build(),
            ContentProviderOperation.newInsert(ContactsContract.Data.CONTENT_URI)
                .withValueBackReference(ContactsContract.Data.RAW_CONTACT_ID, 0)
                .withValue(ContactsContract.Data.MIMETYPE, StructuredName.CONTENT_ITEM_TYPE)
                .withValue(StructuredName.DISPLAY_NAME, CONTACT_NAME)
                .build(),
            ContentProviderOperation.newInsert(ContactsContract.Data.CONTENT_URI)
                .withValueBackReference(ContactsContract.Data.RAW_CONTACT_ID, 0)
                .withValue(ContactsContract.Data.MIMETYPE, Phone.CONTENT_ITEM_TYPE)
                .withValue(Phone.NUMBER, LOCAL_NUMBER)
                .withValue(Phone.TYPE, Phone.TYPE_MAIN)
                .withValue(Phone.LABEL, "JARVIS local")
                .withValue(ContactsContract.Data.PREFERRED_PHONE_ACCOUNT_COMPONENT_NAME, componentName)
                .withValue(ContactsContract.Data.PREFERRED_PHONE_ACCOUNT_ID, accountId)
                .build()
        )
        resolver.applyBatch(ContactsContract.AUTHORITY, operations)
        return true
    }
}
