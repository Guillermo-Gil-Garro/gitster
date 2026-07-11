package com.gitster.dj.ui

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Outline
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.drawscope.drawIntoCanvas
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.gitster.dj.ui.theme.GitsterAmber
import com.gitster.dj.ui.theme.GitsterCyan
import com.gitster.dj.ui.theme.GitsterMagenta

@Composable
fun AnimatedNeonBorder(
    modifier: Modifier = Modifier,
    shape: Shape = RoundedCornerShape(22.dp),
    strokeDp: Dp = 2.dp,
    isAnimated: Boolean
) {
    val angleDeg = if (isAnimated) {
        val transition = rememberInfiniteTransition(label = "animated_neon_border")
        val animatedAngle by transition.animateFloat(
            initialValue = 0f,
            targetValue = 360f,
            animationSpec = infiniteRepeatable(
                animation = tween(durationMillis = 8_000, easing = LinearEasing),
                repeatMode = RepeatMode.Restart
            ),
            label = "animated_neon_border_angle"
        )
        animatedAngle
    } else {
        0f
    }

    val neonColors = remember {
        intArrayOf(
            GitsterMagenta.toArgb(),
            GitsterCyan.toArgb(),
            GitsterAmber.toArgb(),
            Color(0xFFFF9E2C).toArgb(),
            GitsterMagenta.toArgb()
        )
    }
    val shaderMatrix = remember { android.graphics.Matrix() }

    Canvas(modifier = modifier) {
        val strokePx = strokeDp.toPx().coerceAtLeast(1f)
        val halfStroke = strokePx / 2f
        val drawWidth = (size.width - strokePx).coerceAtLeast(0f)
        val drawHeight = (size.height - strokePx).coerceAtLeast(0f)
        if (drawWidth <= 0f || drawHeight <= 0f) return@Canvas

        val centerX = size.width / 2f
        val centerY = size.height / 2f

        val shader = android.graphics.SweepGradient(centerX, centerY, neonColors, null)
        shaderMatrix.reset()
        shaderMatrix.setRotate(angleDeg, centerX, centerY)
        shader.setLocalMatrix(shaderMatrix)

        val frameworkPaint = android.graphics.Paint(android.graphics.Paint.ANTI_ALIAS_FLAG).apply {
            style = android.graphics.Paint.Style.STROKE
            strokeWidth = strokePx
            this.shader = shader
        }

        val outline = shape.createOutline(size = size, layoutDirection = layoutDirection, density = this)

        drawIntoCanvas { canvas ->
            val nativeCanvas = canvas.nativeCanvas
            when (outline) {
                is Outline.Rounded -> {
                    val rr = outline.roundRect
                    val radii = floatArrayOf(
                        rr.topLeftCornerRadius.x, rr.topLeftCornerRadius.y,
                        rr.topRightCornerRadius.x, rr.topRightCornerRadius.y,
                        rr.bottomRightCornerRadius.x, rr.bottomRightCornerRadius.y,
                        rr.bottomLeftCornerRadius.x, rr.bottomLeftCornerRadius.y
                    )
                    val path = android.graphics.Path().apply {
                        addRoundRect(
                            android.graphics.RectF(
                                halfStroke,
                                halfStroke,
                                halfStroke + drawWidth,
                                halfStroke + drawHeight
                            ),
                            radii,
                            android.graphics.Path.Direction.CW
                        )
                    }
                    nativeCanvas.drawPath(path, frameworkPaint)
                }

                else -> {
                    nativeCanvas.drawRect(
                        halfStroke,
                        halfStroke,
                        halfStroke + drawWidth,
                        halfStroke + drawHeight,
                        frameworkPaint
                    )
                }
            }
        }
    }
}
