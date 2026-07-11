package com.gitster.dj

import android.app.Activity
import android.content.Context
import android.content.ContextWrapper

/** Unwraps the Activity behind a (possibly wrapped) Compose LocalContext. */
fun Context.findActivity(): Activity? = when (this) {
    is Activity -> this
    is ContextWrapper -> baseContext.findActivity()
    else -> null
}
