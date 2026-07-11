package com.gitster.dj

import java.util.Locale

/** External links used by the app, kept in one place. */
object AppLinks {
    // Rules pages are served from the repo's docs/ folder once GitHub Pages is enabled.
    private const val RULES_BASE_URL = "https://guillermo-gil-garro.github.io/gitster/rules/"

    /** Language-aware rules URL: Spanish devices get /es/, everyone else /en/. */
    val RULES_URL: String
        get() {
            val isSpanish = Locale.getDefault().language.equals("es", ignoreCase = true)
            return if (isSpanish) "${RULES_BASE_URL}es/" else "${RULES_BASE_URL}en/"
        }
}
