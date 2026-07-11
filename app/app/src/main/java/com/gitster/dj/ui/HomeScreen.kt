package com.gitster.dj.ui

import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.keyframes
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.blur
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Shadow
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.graphics.drawscope.scale
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.gitster.dj.R

@Composable
fun HomeScreen(
    onPlayNow: () -> Unit,
    onRules: () -> Unit
) {
    val shapeLg = RoundedCornerShape(20.dp)

    Box(modifier = Modifier.fillMaxSize()) {
        Image(
            painter = painterResource(id = R.drawable.home_bg),
            contentDescription = null,
            modifier = Modifier.fillMaxSize(),
            contentScale = ContentScale.Crop
        )

        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(
                    Brush.verticalGradient(
                        0f to Color(0x66060814),
                        0.55f to Color(0x77060814),
                        1f to Color(0x99060814)
                    )
                )
        )

        Column(
            modifier = Modifier
                .fillMaxSize()
                .safeDrawingPadding()
                .padding(horizontal = 18.dp, vertical = 16.dp),
            verticalArrangement = Arrangement.Top,
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Column(
                Modifier.fillMaxWidth().weight(1f),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                Spacer(Modifier.height(26.dp))
                NeonFlickerLogo(modifier = Modifier.fillMaxWidth())
                Box(
                    modifier = Modifier.fillMaxWidth().weight(1f),
                    contentAlignment = Alignment.Center
                ) {
                    HomeQrHero()
                }

                Spacer(Modifier.height(8.dp))
                Button(
                    onClick = onPlayNow,
                    modifier = Modifier.fillMaxWidth().height(58.dp),
                    shape = shapeLg,
                    colors = ButtonDefaults.buttonColors(
                        containerColor = MaterialTheme.colorScheme.secondary,
                        contentColor = Color.Black
                    )
                ) {
                    Text(
                        stringResource(R.string.home_play_now),
                        fontWeight = FontWeight.Black,
                        style = MaterialTheme.typography.titleMedium
                    )
                }

                Spacer(Modifier.height(12.dp))

                Button(
                    onClick = onRules,
                    modifier = Modifier.fillMaxWidth().height(58.dp),
                    shape = shapeLg,
                    colors = ButtonDefaults.buttonColors(
                        containerColor = MaterialTheme.colorScheme.primary,
                        contentColor = Color.Black
                    )
                ) {
                    Text(
                        stringResource(R.string.home_rules),
                        fontWeight = FontWeight.Black,
                        style = MaterialTheme.typography.titleMedium
                    )
                }
            }
        }
    }
}

@Composable
private fun HomeQrHero() {
    val frameVisualSize = 248.dp
    val frameCanvasSize = 320.dp
    val qrCardSize = 176.dp

    Column(
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Box(
            modifier = Modifier.size(frameCanvasSize),
            contentAlignment = Alignment.Center
        ) {
            NeonQrFrame(
                modifier = Modifier.fillMaxSize(),
                frameVisualSize = frameVisualSize
            )

            Card(
                modifier = Modifier.size(qrCardSize),
                shape = RoundedCornerShape(14.dp),
                colors = CardDefaults.cardColors(containerColor = Color(0xFFFDFDFD))
            ) {
                Box(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(12.dp),
                    contentAlignment = Alignment.Center
                ) {
                    Image(
                        painter = painterResource(id = R.drawable.qr_home),
                        contentDescription = stringResource(R.string.home_qr_content_description),
                        modifier = Modifier.fillMaxSize(),
                        contentScale = ContentScale.Fit
                    )
                }
            }
        }

        Spacer(Modifier.height(2.dp))
        ScanMeNeonText()
    }
}

@Composable
private fun NeonQrFrame(
    modifier: Modifier = Modifier,
    frameVisualSize: Dp
) {
    val infinite = rememberInfiniteTransition(label = "qr_neon_ring")
    val angleDeg by infinite.animateFloat(
        initialValue = 0f,
        targetValue = 360f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 7000),
            repeatMode = RepeatMode.Restart
        ),
        label = "qr_ring_angle"
    )
    val pulse by infinite.animateFloat(
        initialValue = 0.98f,
        targetValue = 1.03f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 3000),
            repeatMode = RepeatMode.Reverse
        ),
        label = "qr_ring_pulse"
    )

    val colorMagenta = Color(0xFFFF2FD0)
    val neonColors = listOf(
        colorMagenta,
        Color(0xFFFF63C9),
        Color(0xFF9D4DFF),
        Color(0xFF4B7BFF),
        Color(0xFF26D7FF),
        Color(0xFF4FFFD2),
        Color(0xFFFFE45E),
        Color(0xFFFF9E2C),
        colorMagenta
    )
    val sweep = Brush.sweepGradient(colors = neonColors)

    Canvas(
        modifier = modifier.graphicsLayer(alpha = 0.95f)
    ) {
        val strokeOuter = size.minDimension * 0.13f
        val strokeMid = size.minDimension * 0.085f
        val strokeInner = size.minDimension * 0.045f
        val maxStroke = maxOf(strokeOuter, strokeMid, strokeInner)
        val side = frameVisualSize.toPx()
        val left = (size.width - side) / 2f
        val top = (size.height - side) / 2f
        val inset = (maxStroke / 2f) + 10.dp.toPx()
        val frameRect = Rect(
            left = left + inset,
            top = top + inset,
            right = left + side - inset,
            bottom = top + side - inset
        )
        val cornerOuter = 26.dp.toPx()
        val cornerMid = 24.dp.toPx()
        val cornerInner = 22.dp.toPx()

        rotate(degrees = angleDeg, pivot = center) {
            scale(scale = pulse, pivot = center) {
                drawRoundRect(
                    brush = sweep,
                    topLeft = frameRect.topLeft,
                    size = frameRect.size,
                    cornerRadius = CornerRadius(cornerOuter, cornerOuter),
                    style = Stroke(width = strokeOuter),
                    alpha = 0.20f
                )
                drawRoundRect(
                    brush = sweep,
                    topLeft = frameRect.topLeft,
                    size = frameRect.size,
                    cornerRadius = CornerRadius(cornerMid, cornerMid),
                    style = Stroke(width = strokeMid),
                    alpha = 0.42f
                )
                drawRoundRect(
                    brush = sweep,
                    topLeft = frameRect.topLeft,
                    size = frameRect.size,
                    cornerRadius = CornerRadius(cornerInner, cornerInner),
                    style = Stroke(width = strokeInner),
                    alpha = 0.98f
                )
            }
        }
    }
}

@Composable
private fun ScanMeNeonText() {
    val scanMeText = stringResource(R.string.home_scan_me)
    val infinite = rememberInfiniteTransition(label = "scan_me_flicker")
    val flickerAlpha by infinite.animateFloat(
        initialValue = 1f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = keyframes {
                durationMillis = 1500
                1f at 0
                0.84f at 190
                1f at 280
                0.72f at 780
                1f at 890
                0.88f at 1220
                1f at 1500
            },
            repeatMode = RepeatMode.Restart
        ),
        label = "scan_me_alpha"
    )

    Box(
        modifier = Modifier
            .offset(y = (-22).dp)
            .padding(top = 0.dp),
        contentAlignment = Alignment.Center
    ) {
        Text(
            text = scanMeText,
            color = Color(0xFFD7FF4A).copy(alpha = 0.42f * flickerAlpha),
            style = MaterialTheme.typography.titleLarge.copy(
                fontWeight = FontWeight.ExtraBold,
                shadow = Shadow(
                    color = Color.Black.copy(alpha = 0.82f),
                    blurRadius = 28f
                )
            ),
            modifier = Modifier
                .graphicsLayer(
                    scaleX = 1.04f,
                    scaleY = 1.04f
                )
                .blur(7.dp)
        )
        Text(
            text = scanMeText,
            color = Color(0xFFD7FF4A).copy(alpha = 0.32f * flickerAlpha),
            style = MaterialTheme.typography.titleLarge.copy(
                fontWeight = FontWeight.ExtraBold,
                shadow = Shadow(
                    color = Color(0xFFD7FF4A).copy(alpha = 0.9f),
                    blurRadius = 24f
                )
            )
        )
        Text(
            text = scanMeText,
            color = Color.White.copy(alpha = 0.96f * flickerAlpha),
            style = MaterialTheme.typography.titleLarge.copy(
                fontWeight = FontWeight.ExtraBold,
                shadow = Shadow(
                    color = Color(0xFFD7FF4A).copy(alpha = 0.68f),
                    blurRadius = 10f
                )
            )
        )
    }
}

@Composable
private fun NeonFlickerLogo(modifier: Modifier = Modifier) {
    val infinite = rememberInfiniteTransition(label = "logo_flicker")
    val alpha by infinite.animateFloat(
        initialValue = 1f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = keyframes {
                durationMillis = 9000
                1f at 0
                0.86f at 1800
                1f at 1940
                0.74f at 5300
                1f at 5420
                0.82f at 5560
                1f at 5700
                1f at 9000
            },
            repeatMode = RepeatMode.Restart
        ),
        label = "logo_alpha"
    )

    Box(modifier = modifier, contentAlignment = Alignment.Center) {
        Image(
            painter = painterResource(id = R.drawable.gitster_logo),
            contentDescription = null,
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 10.dp)
                .graphicsLayer(
                    alpha = 0.26f * alpha,
                    scaleX = 1.03f,
                    scaleY = 1.03f
                )
                .blur(12.dp),
            contentScale = ContentScale.Fit
        )

        Image(
            painter = painterResource(id = R.drawable.gitster_logo),
            contentDescription = stringResource(R.string.brand_name),
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 10.dp)
                .graphicsLayer(
                    alpha = alpha,
                    scaleX = 1f - (1f - alpha) * 0.01f,
                    scaleY = 1f - (1f - alpha) * 0.01f
                ),
            contentScale = ContentScale.Fit
        )
    }
}
