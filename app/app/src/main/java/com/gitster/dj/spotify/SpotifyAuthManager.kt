package com.gitster.dj.spotify

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.util.Log
import androidx.browser.customtabs.CustomTabsIntent
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.longPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.FormBody
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject

private const val TAG = "SpotifyAuth"
private const val AUTH_STORE_NAME = "spotify_auth"
private const val EXPIRES_BUFFER_MS = 30_000L
private const val AUTH_REOPEN_GUARD_MS = 60_000L

private val Context.spotifyAuthDataStore by preferencesDataStore(name = AUTH_STORE_NAME)

/**
 * Spotify PKCE auth: Custom Tabs login, code exchange, refresh, and
 * token persistence in DataStore.
 *
 * Call [initialize] early (Application/Activity onCreate) and route the
 * gitster://callback deep link through [handleRedirectIntent].
 */
object SpotifyAuthManager {
    private val accessTokenKey = stringPreferencesKey("access_token")
    private val refreshTokenKey = stringPreferencesKey("refresh_token")
    private val expiresAtMsKey = longPreferencesKey("expires_at_ms")
    private val lastStateKey = stringPreferencesKey("last_state")
    private val lastVerifierKey = stringPreferencesKey("last_verifier")

    private val httpClient = OkHttpClient()
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    /** Bumped whenever a new token is stored; UI observes it to retry autoplay after login. */
    private val _tokenVersion = MutableStateFlow(0L)
    val tokenVersion: StateFlow<Long> = _tokenVersion.asStateFlow()

    @Volatile
    private var appContext: Context? = null

    @Volatile
    private var authInFlight: Boolean = false

    @Volatile
    private var authStartedAtMs: Long = 0L

    fun initialize(context: Context) {
        appContext = context.applicationContext
    }

    /**
     * Returns a valid access token, refreshing if possible.
     * Returns null after launching the interactive login (Custom Tab).
     */
    suspend fun ensureValidToken(activity: Activity): String? {
        initialize(activity.applicationContext)
        val context = appContext ?: return null
        val now = System.currentTimeMillis()
        val snapshot = readSnapshot(context)

        if (!snapshot.accessToken.isNullOrBlank() && snapshot.expiresAtMs > now) {
            return snapshot.accessToken
        }

        if (refreshIfNeeded()) {
            val refreshed = readSnapshot(context).accessToken
            if (!refreshed.isNullOrBlank()) {
                return refreshed
            }
        }

        startAuthorization(activity, context)
        return null
    }

    /** Handles the gitster://callback redirect; ignores unrelated intents. */
    fun handleRedirectIntent(intent: Intent) {
        val data = intent.data ?: return
        if (!isSpotifyCallback(data)) return

        Log.d(TAG, "Auth redirect received")
        val context = appContext
        if (context == null) {
            Log.w(TAG, "Auth redirect dropped: manager not initialized")
            authInFlight = false
            return
        }

        val error = data.getQueryParameter("error")
        if (!error.isNullOrBlank()) {
            Log.w(TAG, "Auth redirect returned error=$error")
            authInFlight = false
            return
        }

        val code = data.getQueryParameter("code")
        val state = data.getQueryParameter("state")
        if (code.isNullOrBlank() || state.isNullOrBlank()) {
            Log.w(TAG, "Auth redirect missing code or state")
            authInFlight = false
            return
        }

        scope.launch {
            exchangeAuthorizationCode(context, code, state)
        }
    }

    /** Returns true if a valid (possibly just refreshed) token is available. */
    suspend fun refreshIfNeeded(): Boolean {
        val context = appContext ?: return false

        val snapshot = readSnapshot(context)
        val now = System.currentTimeMillis()
        if (!snapshot.accessToken.isNullOrBlank() && snapshot.expiresAtMs > now) {
            return true
        }

        val refreshToken = snapshot.refreshToken
        if (refreshToken.isNullOrBlank()) {
            return false
        }

        return refreshAccessToken(context, refreshToken)
    }

    suspend fun getAccessTokenOrNull(): String? {
        val context = appContext ?: return null
        return readSnapshot(context).accessToken
    }

    private fun isSpotifyCallback(uri: Uri): Boolean {
        return uri.scheme.equals("gitster", ignoreCase = true) &&
            uri.host.equals("callback", ignoreCase = true)
    }

    private suspend fun startAuthorization(activity: Activity, context: Context) {
        val now = System.currentTimeMillis()
        if (authInFlight) {
            val elapsed = now - authStartedAtMs
            if (elapsed < AUTH_REOPEN_GUARD_MS) {
                Log.d(TAG, "Authorization already in flight (${elapsed}ms ago), skipping")
                return
            }
            authInFlight = false
        }

        val verifier = SpotifyPkce.generateCodeVerifier()
        val challenge = SpotifyPkce.codeChallengeS256(verifier)
        val state = SpotifyPkce.randomState()

        context.spotifyAuthDataStore.edit { prefs ->
            prefs[lastStateKey] = state
            prefs[lastVerifierKey] = verifier
        }

        val authorizeUri = Uri.parse("https://accounts.spotify.com/authorize")
            .buildUpon()
            .appendQueryParameter("client_id", SpotifyConfig.clientId)
            .appendQueryParameter("response_type", "code")
            .appendQueryParameter("redirect_uri", SpotifyConfig.redirectUri)
            .appendQueryParameter("code_challenge_method", "S256")
            .appendQueryParameter("code_challenge", challenge)
            .appendQueryParameter("state", state)
            .appendQueryParameter(
                "scope",
                "user-modify-playback-state user-read-playback-state"
            )
            .appendQueryParameter("show_dialog", "false")
            .build()

        authInFlight = true
        authStartedAtMs = now

        Log.d(TAG, "Launching authorization Custom Tab")
        withContext(Dispatchers.Main) {
            runCatching {
                CustomTabsIntent.Builder().build().launchUrl(activity, authorizeUri)
            }.onFailure { error ->
                Log.e(TAG, "Failed to launch authorization Custom Tab", error)
                authInFlight = false
            }
        }
    }

    private suspend fun exchangeAuthorizationCode(
        context: Context,
        code: String,
        redirectState: String
    ) {
        val snapshot = readSnapshot(context)

        if (snapshot.lastState != redirectState) {
            Log.w(TAG, "Auth code exchange aborted: state mismatch")
            authInFlight = false
            return
        }

        val verifier = snapshot.lastVerifier
        if (verifier.isNullOrBlank()) {
            Log.w(TAG, "Auth code exchange aborted: missing PKCE verifier")
            authInFlight = false
            return
        }

        val body = FormBody.Builder()
            .add("grant_type", "authorization_code")
            .add("client_id", SpotifyConfig.clientId)
            .add("code", code)
            .add("redirect_uri", SpotifyConfig.redirectUri)
            .add("code_verifier", verifier)
            .build()

        val request = Request.Builder()
            .url("https://accounts.spotify.com/api/token")
            .post(body)
            .header("Content-Type", "application/x-www-form-urlencoded")
            .build()

        val result = executeTokenRequest(request)
        if (result == null) {
            Log.w(TAG, "Auth code exchange failed: network error")
            authInFlight = false
            return
        }

        if (result.code !in 200..299) {
            Log.w(TAG, "Auth code exchange failed: HTTP ${result.code}")
            authInFlight = false
            return
        }

        runCatching {
            val json = JSONObject(result.rawBody)
            val accessToken = json.optString("access_token", "")
            val refreshToken = json.optString("refresh_token", "")
            val expiresInSec = json.optLong("expires_in", 0L)

            if (accessToken.isBlank() || expiresInSec <= 0L) {
                Log.w(TAG, "Auth code exchange failed: invalid token payload")
                return@runCatching false
            }

            val expiresAtMs = System.currentTimeMillis() + (expiresInSec * 1_000L) - EXPIRES_BUFFER_MS
            context.spotifyAuthDataStore.edit { prefs ->
                prefs[accessTokenKey] = accessToken
                prefs[expiresAtMsKey] = expiresAtMs
                if (refreshToken.isNotBlank()) {
                    prefs[refreshTokenKey] = refreshToken
                }
                prefs.remove(lastStateKey)
                prefs.remove(lastVerifierKey)
            }

            bumpTokenVersion()
            Log.d(TAG, "Auth code exchange ok")
            true
        }.onFailure { error ->
            Log.w(TAG, "Auth code exchange failed: bad response body", error)
        }

        authInFlight = false
    }

    private suspend fun refreshAccessToken(context: Context, refreshToken: String): Boolean {
        val body = FormBody.Builder()
            .add("grant_type", "refresh_token")
            .add("client_id", SpotifyConfig.clientId)
            .add("refresh_token", refreshToken)
            .build()

        val request = Request.Builder()
            .url("https://accounts.spotify.com/api/token")
            .post(body)
            .header("Content-Type", "application/x-www-form-urlencoded")
            .build()

        val result = executeTokenRequest(request)
        if (result == null) {
            Log.w(TAG, "Token refresh failed: network error")
            return false
        }
        if (result.code !in 200..299) {
            Log.w(TAG, "Token refresh failed: HTTP ${result.code}")
            return false
        }

        return runCatching {
            val json = JSONObject(result.rawBody)
            val accessToken = json.optString("access_token", "")
            val newRefreshToken = json.optString("refresh_token", "")
            val expiresInSec = json.optLong("expires_in", 0L)
            if (accessToken.isBlank() || expiresInSec <= 0L) {
                Log.w(TAG, "Token refresh failed: invalid token payload")
                return@runCatching false
            }

            val expiresAtMs = System.currentTimeMillis() + (expiresInSec * 1_000L) - EXPIRES_BUFFER_MS
            context.spotifyAuthDataStore.edit { prefs ->
                prefs[accessTokenKey] = accessToken
                prefs[expiresAtMsKey] = expiresAtMs
                val refreshTokenToStore = newRefreshToken.takeIf { it.isNotBlank() } ?: refreshToken
                prefs[refreshTokenKey] = refreshTokenToStore
            }
            bumpTokenVersion()
            Log.d(TAG, "Token refresh ok")
            true
        }.getOrElse { error ->
            Log.w(TAG, "Token refresh failed: bad response body", error)
            false
        }
    }

    private suspend fun executeTokenRequest(request: Request): TokenResponse? {
        return withContext(Dispatchers.IO) {
            runCatching {
                httpClient.newCall(request).execute().use { response ->
                    val body = response.body?.string().orEmpty()
                    TokenResponse(
                        code = response.code,
                        rawBody = body
                    )
                }
            }.getOrNull()
        }
    }

    private fun bumpTokenVersion() {
        _tokenVersion.value = _tokenVersion.value + 1L
    }

    private suspend fun readSnapshot(context: Context): TokenSnapshot {
        val prefs = context.spotifyAuthDataStore.data.first()
        return TokenSnapshot(
            accessToken = prefs[accessTokenKey],
            refreshToken = prefs[refreshTokenKey],
            expiresAtMs = prefs[expiresAtMsKey] ?: 0L,
            lastState = prefs[lastStateKey],
            lastVerifier = prefs[lastVerifierKey]
        )
    }

    private data class TokenSnapshot(
        val accessToken: String?,
        val refreshToken: String?,
        val expiresAtMs: Long,
        val lastState: String?,
        val lastVerifier: String?
    )

    private data class TokenResponse(
        val code: Int,
        val rawBody: String
    )
}
