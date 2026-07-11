package com.gitster.dj.spotify

import android.net.Uri
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException

private const val TAG = "SpotifyWebApi"

/**
 * Thin Spotify Web API client (player endpoints only).
 *
 * Every call retries once on 401 after refreshing the token through
 * [SpotifyAuthManager]. Non-2xx responses are thrown as typed
 * [WebApiException]s so callers can map them to playback states.
 */
object SpotifyWebApiClient {
    private val client = OkHttpClient()
    private val jsonMediaType = "application/json".toMediaType()

    data class Device(
        val id: String,
        val name: String,
        val isActive: Boolean
    )

    data class PlayerState(
        val progressMs: Long,
        val durationMs: Long?
    )

    open class WebApiException(
        message: String,
        val statusCode: Int,
        val bodyPreview: String
    ) : IOException(message)

    class UnauthorizedException(
        statusCode: Int,
        bodyPreview: String
    ) : WebApiException("Unauthorized from Spotify Web API", statusCode, bodyPreview)

    class NoActiveDeviceException(
        statusCode: Int,
        bodyPreview: String
    ) : WebApiException("No active Spotify device", statusCode, bodyPreview)

    class UnexpectedStatusException(
        statusCode: Int,
        bodyPreview: String,
        endpoint: String
    ) : WebApiException("Unexpected status from $endpoint", statusCode, bodyPreview)

    suspend fun getDevices(token: String): List<Device> {
        val endpoint = "GET /v1/me/player/devices"
        val result = executeWithRefreshRetry(
            initialToken = token,
            method = "GET",
            url = "https://api.spotify.com/v1/me/player/devices",
            bodyJson = null
        )

        if (result.statusCode in 200..299) {
            val json = JSONObject(result.body)
            val devices = json.optJSONArray("devices") ?: JSONArray()
            val parsedDevices = buildList {
                for (i in 0 until devices.length()) {
                    val item = devices.optJSONObject(i) ?: continue
                    val id = item.optString("id", "")
                    if (id.isBlank()) continue
                    add(
                        Device(
                            id = id,
                            name = item.optString("name", "Spotify device"),
                            isActive = item.optBoolean("is_active", false)
                        )
                    )
                }
            }
            Log.d(TAG, "Devices count=${parsedDevices.size}")
            return parsedDevices
        }

        throwStatus(endpoint = endpoint, result = result)
    }

    suspend fun transferPlayback(token: String, deviceId: String, play: Boolean) {
        val endpoint = "PUT /v1/me/player"
        val body = JSONObject()
            .put("device_ids", JSONArray().put(deviceId))
            .put("play", play)
            .toString()

        val result = executeWithRefreshRetry(
            initialToken = token,
            method = "PUT",
            url = "https://api.spotify.com/v1/me/player",
            bodyJson = body
        )

        if (result.statusCode in 200..299) {
            Log.d(TAG, "Transfer ok")
            return
        }
        Log.w(TAG, "Transfer failed code=${result.statusCode}")
        throwStatus(endpoint = endpoint, result = result)
    }

    suspend fun playTrack(
        token: String,
        deviceId: String?,
        spotifyTrackUri: String,
        positionMs: Long? = null
    ) {
        val endpoint = "PUT /v1/me/player/play"
        val playUrl = Uri.parse("https://api.spotify.com/v1/me/player/play")
            .buildUpon()
            .apply {
                if (!deviceId.isNullOrBlank()) appendQueryParameter("device_id", deviceId)
            }
            .build()
            .toString()

        val body = JSONObject()
            .put("uris", JSONArray().put(spotifyTrackUri))
            .apply {
                if (positionMs != null && positionMs >= 0L) {
                    put("position_ms", positionMs)
                }
            }
            .toString()

        val result = executeWithRefreshRetry(
            initialToken = token,
            method = "PUT",
            url = playUrl,
            bodyJson = body
        )

        if (result.statusCode in 200..299) {
            Log.d(TAG, "Play ok")
            return
        }
        Log.w(TAG, "Play failed code=${result.statusCode}")
        throwStatus(endpoint = endpoint, result = result)
    }

    suspend fun resumePlayback(token: String) {
        val endpoint = "PUT /v1/me/player/play"
        val result = executeWithRefreshRetry(
            initialToken = token,
            method = "PUT",
            url = "https://api.spotify.com/v1/me/player/play",
            bodyJson = null
        )

        if (result.statusCode in 200..299) {
            return
        }

        throwStatus(endpoint = endpoint, result = result)
    }

    suspend fun pausePlayback(token: String) {
        val endpoint = "PUT /v1/me/player/pause"
        val result = executeWithRefreshRetry(
            initialToken = token,
            method = "PUT",
            url = "https://api.spotify.com/v1/me/player/pause",
            bodyJson = null
        )

        if (result.statusCode in 200..299) {
            Log.d(TAG, "Pause ok")
            return
        }

        Log.w(TAG, "Pause failed code=${result.statusCode}")
        throwStatus(endpoint = endpoint, result = result)
    }

    suspend fun getPlayerState(token: String): PlayerState {
        val endpoint = "GET /v1/me/player"
        val result = executeWithRefreshRetry(
            initialToken = token,
            method = "GET",
            url = "https://api.spotify.com/v1/me/player",
            bodyJson = null
        )

        if (result.statusCode in 200..299) {
            val json = JSONObject(result.body)
            val progressMs = when {
                !json.has("progress_ms") || json.isNull("progress_ms") -> 0L
                else -> json.optLong("progress_ms", 0L).coerceAtLeast(0L)
            }
            val itemJson = json.optJSONObject("item")
            val durationMs = when {
                itemJson == null || !itemJson.has("duration_ms") || itemJson.isNull("duration_ms") -> null
                else -> itemJson.optLong("duration_ms", 0L).takeIf { it > 0L }
            }
            return PlayerState(
                progressMs = progressMs,
                durationMs = durationMs
            )
        }

        throwStatus(endpoint = endpoint, result = result)
    }

    suspend fun seekTo(token: String, positionMs: Long) {
        val endpoint = "PUT /v1/me/player/seek"
        val seekUrl = Uri.parse("https://api.spotify.com/v1/me/player/seek")
            .buildUpon()
            .appendQueryParameter("position_ms", positionMs.coerceAtLeast(0L).toString())
            .build()
            .toString()

        val result = executeWithRefreshRetry(
            initialToken = token,
            method = "PUT",
            url = seekUrl,
            bodyJson = null
        )

        if (result.statusCode in 200..299) {
            return
        }

        throwStatus(endpoint = endpoint, result = result)
    }

    private suspend fun executeWithRefreshRetry(
        initialToken: String,
        method: String,
        url: String,
        bodyJson: String?
    ): HttpResult {
        var token = initialToken
        var retried = false
        while (true) {
            val result = withContext(Dispatchers.IO) { executeOnce(token, method, url, bodyJson) }
            if (result.statusCode != 401) {
                return result
            }

            if (retried) {
                return result
            }

            val refreshed = SpotifyAuthManager.refreshIfNeeded()
            val newToken = SpotifyAuthManager.getAccessTokenOrNull()
            if (!refreshed || newToken.isNullOrBlank()) {
                return result
            }
            token = newToken
            retried = true
        }
    }

    private fun executeOnce(
        token: String,
        method: String,
        url: String,
        bodyJson: String?
    ): HttpResult {
        return authorizedRequest(token, method, url, bodyJson).use { response ->
            val body = response.body?.string().orEmpty()
            Log.d(TAG, "HTTP ${response.code} ${endpointFromUrl(method, url)}")
            HttpResult(
                statusCode = response.code,
                body = body,
                bodyPreview = body.take(200)
            )
        }
    }

    private fun authorizedRequest(
        token: String,
        method: String,
        url: String,
        bodyJson: String?
    ): Response {
        val requestBuilder = Request.Builder()
            .url(url)
            .header("Authorization", "Bearer $token")

        val upperMethod = method.uppercase()
        when {
            bodyJson != null -> {
                requestBuilder.method(upperMethod, bodyJson.toRequestBody(jsonMediaType))
            }

            upperMethod == "PUT" || upperMethod == "POST" || upperMethod == "PATCH" -> {
                requestBuilder.method(upperMethod, "".toRequestBody(jsonMediaType))
            }

            else -> {
                requestBuilder.method(upperMethod, null)
            }
        }

        return client.newCall(requestBuilder.build()).execute()
    }

    private fun throwStatus(endpoint: String, result: HttpResult): Nothing {
        if (result.statusCode == 401) {
            throw UnauthorizedException(
                statusCode = result.statusCode,
                bodyPreview = result.bodyPreview
            )
        }
        if (
            (endpoint == "GET /v1/me/player/devices" && result.statusCode == 404) ||
            (endpoint == "GET /v1/me/player" && result.statusCode == 204) ||
            (endpoint == "PUT /v1/me/player/seek" && result.statusCode == 404) ||
            (endpoint == "PUT /v1/me/player/play" && (result.statusCode == 403 || result.statusCode == 404)) ||
            (endpoint == "PUT /v1/me/player/pause" && (result.statusCode == 403 || result.statusCode == 404)) ||
            isNoActiveDevice(result.statusCode, result.bodyPreview)
        ) {
            throw NoActiveDeviceException(
                statusCode = result.statusCode,
                bodyPreview = result.bodyPreview
            )
        }
        throw UnexpectedStatusException(
            statusCode = result.statusCode,
            bodyPreview = result.bodyPreview,
            endpoint = endpoint
        )
    }

    private fun isNoActiveDevice(statusCode: Int, body: String): Boolean {
        if (statusCode != 404) return false
        return body.contains("NO_ACTIVE_DEVICE", ignoreCase = true) ||
            body.contains("No active device", ignoreCase = true)
    }

    private fun endpointFromUrl(method: String, url: String): String {
        val path = Uri.parse(url).encodedPath ?: url
        return "${method.uppercase()} $path"
    }

    private data class HttpResult(
        val statusCode: Int,
        val body: String,
        val bodyPreview: String
    )
}
