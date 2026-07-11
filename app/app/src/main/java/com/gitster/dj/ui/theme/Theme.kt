package com.gitster.dj.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val DarkColorScheme = darkColorScheme(
    primary = GitsterCyan,
    onPrimary = Color.Black,
    secondary = GitsterMagenta,
    onSecondary = Color.Black,
    tertiary = GitsterViolet,
    onTertiary = Color.Black,

    background = GitsterBg0,
    onBackground = GitsterInk,
    surface = GitsterPanel,
    onSurface = GitsterInk,
    surfaceVariant = GitsterPanel2,
    onSurfaceVariant = GitsterInk,
    outline = Color(0x22FFFFFF)
)

private val LightColorScheme = lightColorScheme(
    primary = GitsterCyan,
    onPrimary = Color.Black,
    secondary = GitsterMagenta,
    onSecondary = Color.Black,
    tertiary = GitsterViolet,
    onTertiary = Color.Black,

    background = GitsterBg1,
    onBackground = GitsterInk,
    surface = GitsterPanel,
    onSurface = GitsterInk,
    surfaceVariant = GitsterPanel2,
    onSurfaceVariant = GitsterInk,
    outline = Color(0x22FFFFFF)
)

/** Dynamic color is intentionally off to keep the neon look consistent. */
@Composable
fun GitsterTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit
) {
    MaterialTheme(
        colorScheme = if (darkTheme) DarkColorScheme else LightColorScheme,
        typography = Typography,
        content = content
    )
}
