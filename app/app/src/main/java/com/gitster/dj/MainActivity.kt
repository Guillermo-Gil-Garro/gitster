package com.gitster.dj

import android.content.Intent
import android.os.Bundle
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import com.gitster.dj.deck.DeckRepository
import com.gitster.dj.spotify.SpotifyAuthManager
import com.gitster.dj.ui.theme.GitsterTheme

private const val TAG = "MainActivity"

class MainActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        SpotifyAuthManager.initialize(applicationContext)
        // The auth manager ignores intents that are not the gitster://callback redirect.
        SpotifyAuthManager.handleRedirectIntent(intent)
        Log.d(TAG, "onCreate intentData=${intent.dataString}")

        val repo = DeckRepository(context = applicationContext)

        setContent {
            GitsterTheme {
                GitsterApp(
                    repo = repo,
                    rulesUrl = AppLinks.RULES_URL
                )
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        Log.d(TAG, "onNewIntent intentData=${intent.dataString}")
        setIntent(intent)
        SpotifyAuthManager.handleRedirectIntent(intent)
    }
}
