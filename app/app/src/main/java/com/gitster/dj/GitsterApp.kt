package com.gitster.dj

import android.content.Intent
import android.net.Uri
import android.util.Log
import android.widget.Toast
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.Saver
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.gitster.dj.deck.DeckRepository
import com.gitster.dj.scan.QrScannerScreen
import com.gitster.dj.ui.HomeScreen
import com.gitster.dj.ui.PlaybackScreen
import kotlinx.coroutines.launch

private const val TAG = "GitsterApp"

private sealed interface Screen {
    data object Home : Screen
    data object Scan : Screen
    data class Playback(val playable: PlayableCard) : Screen
}

data class PlayableCard(
    val rawUrl: String,
    val cardId: String?,
    val trackId: String?,
    val spotifyUri: String,
    val title: String? = null,
    val artists: String? = null,
    val year: Int? = null
)

private val ScreenSaver: Saver<Screen, Any> = Saver(
    save = { s ->
        when (s) {
            Screen.Home -> arrayListOf("home")
            Screen.Scan -> arrayListOf("scan")
            is Screen.Playback -> arrayListOf(
                "playback",
                s.playable.rawUrl,
                s.playable.cardId.orEmpty(),
                s.playable.trackId.orEmpty(),
                s.playable.spotifyUri,
                s.playable.title.orEmpty(),
                s.playable.artists.orEmpty(),
                s.playable.year?.toString().orEmpty()
            )
        }
    },
    restore = { restored ->
        val list = restored as? List<*> ?: return@Saver Screen.Home
        when (list.getOrNull(0) as? String ?: "home") {
            "scan" -> Screen.Scan
            "playback" -> {
                val rawUrl = list.getOrNull(1) as? String ?: ""
                val cardId = (list.getOrNull(2) as? String).orEmpty().ifBlank { null }
                val trackId = (list.getOrNull(3) as? String).orEmpty().ifBlank { null }
                val spotifyUri = list.getOrNull(4) as? String ?: ""
                val title = (list.getOrNull(5) as? String).orEmpty().ifBlank { null }
                val artists = (list.getOrNull(6) as? String).orEmpty().ifBlank { null }
                val year = (list.getOrNull(7) as? String).orEmpty().ifBlank { null }?.toIntOrNull()

                Screen.Playback(
                    playable = PlayableCard(
                        rawUrl = rawUrl,
                        cardId = cardId,
                        trackId = trackId,
                        spotifyUri = spotifyUri,
                        title = title,
                        artists = artists,
                        year = year
                    )
                )
            }

            else -> Screen.Home
        }
    }
)

@Composable
fun GitsterApp(
    repo: DeckRepository,
    rulesUrl: String
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    var screen by rememberSaveable(stateSaver = ScreenSaver) { mutableStateOf<Screen>(Screen.Home) }
    var deckLoaded by remember { mutableStateOf(false) }
    var loading by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) {
        runCatching { repo.loadDeckIfNeeded() }
            .onFailure { Log.w(TAG, "Deck preload failed: ${it.message}") }
        deckLoaded = true
    }

    Surface(modifier = Modifier.fillMaxSize()) {
        Box(Modifier.fillMaxSize()) {
            when (val s = screen) {
                Screen.Home -> HomeScreen(
                    onPlayNow = {
                        screen = Screen.Scan
                    },
                    onRules = {
                        runCatching {
                            context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(rulesUrl)))
                        }.onFailure {
                            Toast.makeText(
                                context,
                                context.getString(R.string.error_open_link),
                                Toast.LENGTH_SHORT
                            ).show()
                        }
                    }
                )

                Screen.Scan -> QrScannerScreen(
                    onClose = { screen = Screen.Home },
                    onScanned = { raw ->
                        // Debounced navigation: ignore further scans while one resolves.
                        if (loading) return@QrScannerScreen
                        loading = true
                        scope.launch {
                            try {
                                if (!deckLoaded) {
                                    runCatching { repo.loadDeckIfNeeded() }
                                        .onFailure { Log.w(TAG, "Deck load failed: ${it.message}") }
                                    deckLoaded = true
                                }

                                val res = repo.resolveFromRaw(rawInput = raw)
                                val trackId = res.trackId
                                if (trackId == null) {
                                    Toast.makeText(
                                        context,
                                        context.getString(R.string.scan_card_not_found),
                                        Toast.LENGTH_SHORT
                                    ).show()
                                } else {
                                    val card = res.card
                                    screen = Screen.Playback(
                                        PlayableCard(
                                            rawUrl = res.raw,
                                            cardId = card?.cardId,
                                            trackId = trackId,
                                            spotifyUri = "spotify:track:$trackId",
                                            title = card?.title,
                                            artists = card?.artists,
                                            year = card?.year
                                        )
                                    )
                                }
                            } catch (t: Throwable) {
                                Toast.makeText(
                                    context,
                                    t.message ?: context.getString(R.string.scan_resolve_error),
                                    Toast.LENGTH_SHORT
                                ).show()
                            } finally {
                                loading = false
                            }
                        }
                    }
                )

                is Screen.Playback -> PlaybackScreen(
                    playable = s.playable,
                    onNextCard = { screen = Screen.Scan },
                    onBackHome = { screen = Screen.Home }
                )
            }

            if (loading) {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        CircularProgressIndicator()
                        Spacer(Modifier.height(10.dp))
                        Text(stringResource(R.string.loading_resolving))
                    }
                }
            }
        }
    }
}
