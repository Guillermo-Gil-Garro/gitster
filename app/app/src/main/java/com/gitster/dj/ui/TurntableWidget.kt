package com.gitster.dj.ui

import android.util.Log
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Image
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.ColorFilter
import androidx.compose.ui.graphics.ColorMatrix
import androidx.compose.ui.graphics.TransformOrigin
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.painter.Painter
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.gitster.dj.R
import kotlin.math.max

private const val TAG = "TurntableWidget"
private val TURN_TABLE_SIZE_DP = 260.dp
private const val VINYL_ROTATION_DURATION_MS = 4_000
private const val DEFAULT_INTRINSIC_FALLBACK_PX = 1_024f
private const val VINYL_CENTERING_MODE = "STATIC_SQUARE_CONTAINER + CENTER_ROTATION"
private const val VINYL_CONTRAST_LAYER_ENABLED = false
private const val VINYL_COLOR_MATRIX_ENABLED = true
private const val VINYL_BRIGHTNESS_BIAS = 0.06f
private const val VINYL_CONTRAST_GAIN = 1.08f
private const val VINYL_SATURATION_GAIN = 1.05f
private val VINYL_IMAGE_OFFSET_X_DP = 0.dp
private val VINYL_IMAGE_OFFSET_Y_DP = 3.7.dp
private val VINYL_GROUP_OFFSET_Y_DP = (-6).dp

// Layer scales are multiplied by globalScale (intrinsic based).
private const val RING_MAIN_SCALE = 1.0f
private const val RING_CUT_SCALE = 1.0f
private const val VINYL_SCALE = 1.04f
private const val NEEDLE_SCALE = 1.0f

private val RING_MAIN_OFFSET_X_DP = 0.dp
private val RING_MAIN_OFFSET_Y_DP = 0.dp
private val RING_CUT_OFFSET_X_DP = 0.dp
private val RING_CUT_OFFSET_Y_DP = 0.dp
private val VINYL_OFFSET_X_DP = 0.dp
private val VINYL_OFFSET_Y_DP = 0.dp

private const val NEEDLE_PIVOT_X = 0.80f
private const val NEEDLE_PIVOT_Y = 0.47f
private const val NEEDLE_PLAY_ANGLE_DEG = 0f
private const val NEEDLE_PAUSE_ANGLE_DEG = 90f
private val NEEDLE_PLAY_OFFSET_X_DP = 0.dp
private val NEEDLE_PLAY_OFFSET_Y_DP = 6.dp
private val NEEDLE_PAUSE_OFFSET_X_DP = 43.dp
private val NEEDLE_PAUSE_OFFSET_Y_DP = -29.dp

private const val RING_CUT_ALPHA_PLAY = 1f
private const val RING_CUT_ALPHA_PAUSE = 0f

private data class IntrinsicSizeInfo(
    val sizePx: Size,
    val usedFallback: Boolean
)

private fun resolveIntrinsicSize(painter: Painter): IntrinsicSizeInfo {
    val intrinsic = painter.intrinsicSize
    val valid =
        intrinsic != Size.Unspecified &&
            intrinsic.width.isFinite() &&
            intrinsic.height.isFinite() &&
            intrinsic.width > 0f &&
            intrinsic.height > 0f
    return if (valid) {
        IntrinsicSizeInfo(sizePx = intrinsic, usedFallback = false)
    } else {
        IntrinsicSizeInfo(
            sizePx = Size(DEFAULT_INTRINSIC_FALLBACK_PX, DEFAULT_INTRINSIC_FALLBACK_PX),
            usedFallback = true
        )
    }
}

private fun Float.pxToDp(density: Float): Dp = (this / density).dp

@Composable
fun TurntableWidget(
    isPlaying: Boolean,
    onTogglePlayPause: () -> Unit,
    modifier: Modifier = Modifier
) {
    val density = LocalDensity.current
    val densityValue = density.density
    val widgetPx = with(density) { TURN_TABLE_SIZE_DP.toPx() }

    val ringMainPainter = painterResource(id = R.drawable.turntable_ring_main)
    val ringCutPainter = painterResource(id = R.drawable.turntable_ring_cut)
    val vinylPainter = painterResource(id = R.drawable.turntable_vinyl)
    val needlePainter = painterResource(id = R.drawable.turntable_needle)

    val ringMainIntrinsic = resolveIntrinsicSize(ringMainPainter)
    val ringCutIntrinsic = resolveIntrinsicSize(ringCutPainter)
    val vinylIntrinsic = resolveIntrinsicSize(vinylPainter)
    val needleIntrinsic = resolveIntrinsicSize(needlePainter)

    val ringMainMaxDimPx = max(ringMainIntrinsic.sizePx.width, ringMainIntrinsic.sizePx.height)
    val ringCutMaxDimPx = max(ringCutIntrinsic.sizePx.width, ringCutIntrinsic.sizePx.height)
    val vinylMaxDimPx = max(vinylIntrinsic.sizePx.width, vinylIntrinsic.sizePx.height)
    val basePx = max(max(ringMainMaxDimPx, ringCutMaxDimPx), vinylMaxDimPx).coerceAtLeast(1f)
    val globalScale = widgetPx / basePx

    val ringMainFinalScale = globalScale * RING_MAIN_SCALE
    val ringCutFinalScale = globalScale * RING_CUT_SCALE
    val vinylFinalScale = globalScale * VINYL_SCALE
    val needleFinalScale = globalScale * NEEDLE_SCALE

    val ringMainWidthDp = (ringMainIntrinsic.sizePx.width * ringMainFinalScale).pxToDp(densityValue)
    val ringMainHeightDp = (ringMainIntrinsic.sizePx.height * ringMainFinalScale).pxToDp(densityValue)
    val ringCutWidthDp = (ringCutIntrinsic.sizePx.width * ringCutFinalScale).pxToDp(densityValue)
    val ringCutHeightDp = (ringCutIntrinsic.sizePx.height * ringCutFinalScale).pxToDp(densityValue)
    val vinylWidthDp = (vinylIntrinsic.sizePx.width * vinylFinalScale).pxToDp(densityValue)
    val vinylHeightDp = (vinylIntrinsic.sizePx.height * vinylFinalScale).pxToDp(densityValue)
    val vinylContainerSizeDp = if (vinylWidthDp > vinylHeightDp) vinylWidthDp else vinylHeightDp
    val needleWidthDp = (needleIntrinsic.sizePx.width * needleFinalScale).pxToDp(densityValue)
    val needleHeightDp = (needleIntrinsic.sizePx.height * needleFinalScale).pxToDp(densityValue)

    val ringMainOffsetXPx = with(density) { RING_MAIN_OFFSET_X_DP.toPx() }
    val ringMainOffsetYPx = with(density) { RING_MAIN_OFFSET_Y_DP.toPx() }
    val ringCutOffsetXPx = with(density) { RING_CUT_OFFSET_X_DP.toPx() }
    val ringCutOffsetYPx = with(density) { RING_CUT_OFFSET_Y_DP.toPx() }
    val vinylOffsetXPx = with(density) { VINYL_OFFSET_X_DP.toPx() }
    val vinylOffsetYPx = with(density) { VINYL_OFFSET_Y_DP.toPx() }
    val vinylGroupOffsetYPx = with(density) { VINYL_GROUP_OFFSET_Y_DP.toPx() }
    val vinylColorFilter = remember {
        if (!VINYL_COLOR_MATRIX_ENABLED) {
            null
        } else {
            val saturation = VINYL_SATURATION_GAIN
            val invSaturation = 1f - saturation
            val lumR = 0.213f
            val lumG = 0.715f
            val lumB = 0.072f
            val satR = lumR * invSaturation
            val satG = lumG * invSaturation
            val satB = lumB * invSaturation

            val contrast = VINYL_CONTRAST_GAIN
            val brightnessBiasPx = VINYL_BRIGHTNESS_BIAS * 255f
            val contrastCenterCompensation = (1f - contrast) * 128f
            val translation = brightnessBiasPx + contrastCenterCompensation

            val matrix = ColorMatrix(
                floatArrayOf(
                    contrast * (satR + saturation), contrast * satG, contrast * satB, 0f, translation,
                    contrast * satR, contrast * (satG + saturation), contrast * satB, 0f, translation,
                    contrast * satR, contrast * satG, contrast * (satB + saturation), 0f, translation,
                    0f, 0f, 0f, 1f, 0f
                )
            )
            ColorFilter.colorMatrix(matrix)
        }
    }

    val ringCutAlpha by animateFloatAsState(
        targetValue = if (isPlaying) RING_CUT_ALPHA_PLAY else RING_CUT_ALPHA_PAUSE,
        animationSpec = tween(durationMillis = 240),
        label = "ringCutAlpha"
    )

    val report = buildString {
        append("widgetSizeDp=").append(TURN_TABLE_SIZE_DP.value)
        append(" ringMainIntrinsicPx=(").append(ringMainIntrinsic.sizePx.width).append(",").append(ringMainIntrinsic.sizePx.height).append(")")
        append(" ringMainFallback=").append(ringMainIntrinsic.usedFallback)
        append(" ringCutIntrinsicPx=(").append(ringCutIntrinsic.sizePx.width).append(",").append(ringCutIntrinsic.sizePx.height).append(")")
        append(" ringCutFallback=").append(ringCutIntrinsic.usedFallback)
        append(" vinylIntrinsicPx=(").append(vinylIntrinsic.sizePx.width).append(",").append(vinylIntrinsic.sizePx.height).append(")")
        append(" vinylFallback=").append(vinylIntrinsic.usedFallback)
        append(" needleIntrinsicPx=(").append(needleIntrinsic.sizePx.width).append(",").append(needleIntrinsic.sizePx.height).append(")")
        append(" needleFallback=").append(needleIntrinsic.usedFallback)
        append(" basePx=").append(basePx)
        append(" widgetPx=").append(widgetPx)
        append(" globalScale=").append(globalScale)
        append(" finalScales ringMain=").append(ringMainFinalScale)
        append(" ringCut=").append(ringCutFinalScale)
        append(" vinyl=").append(vinylFinalScale)
        append(" needle=").append(needleFinalScale)
        append(" layerSizeDp ringMain=(").append(ringMainWidthDp.value).append(",").append(ringMainHeightDp.value).append(")")
        append(" ringCut=(").append(ringCutWidthDp.value).append(",").append(ringCutHeightDp.value).append(")")
        append(" vinyl=(").append(vinylWidthDp.value).append(",").append(vinylHeightDp.value).append(")")
        append(" vinylContainer=").append(vinylContainerSizeDp.value)
        append(" needle=(").append(needleWidthDp.value).append(",").append(needleHeightDp.value).append(")")
        append(" vinylTransformOrigin=(0.5,0.5)")
        append(" VINYL_CENTERING_MODE=").append(VINYL_CENTERING_MODE)
        append(" VINYL_IMAGE_OFFSET_DP=(").append(VINYL_IMAGE_OFFSET_X_DP.value).append(",").append(VINYL_IMAGE_OFFSET_Y_DP.value).append(")")
        append(" contrastLayerEnabled=").append(VINYL_CONTRAST_LAYER_ENABLED)
        append(" vinylColorMatrixEnabled=").append(VINYL_COLOR_MATRIX_ENABLED)
        append(" vinylColorMatrixParams=(")
            .append("brightnessBias=").append(VINYL_BRIGHTNESS_BIAS).append(",")
            .append("contrast=").append(VINYL_CONTRAST_GAIN).append(",")
            .append("saturation=").append(VINYL_SATURATION_GAIN).append(")")
        append(" VINYL_GROUP_OFFSET_Y_DP=").append(VINYL_GROUP_OFFSET_Y_DP.value)
        append(" offsetsDp ringMain=(").append(RING_MAIN_OFFSET_X_DP.value).append(",").append(RING_MAIN_OFFSET_Y_DP.value).append(")")
        append(" ringCut=(").append(RING_CUT_OFFSET_X_DP.value).append(",").append(RING_CUT_OFFSET_Y_DP.value).append(")")
        append(" vinyl=(").append(VINYL_OFFSET_X_DP.value).append(",").append(VINYL_OFFSET_Y_DP.value).append(")")
        append(" needlePlay=(").append(NEEDLE_PLAY_OFFSET_X_DP.value).append(",").append(NEEDLE_PLAY_OFFSET_Y_DP.value).append(")")
        append(" needlePause=(").append(NEEDLE_PAUSE_OFFSET_X_DP.value).append(",").append(NEEDLE_PAUSE_OFFSET_Y_DP.value).append(")")
        append(" needlePivot=(").append(NEEDLE_PIVOT_X).append(",").append(NEEDLE_PIVOT_Y).append(")")
        append(" needleAngles=(").append(NEEDLE_PLAY_ANGLE_DEG).append(",").append(NEEDLE_PAUSE_ANGLE_DEG).append(")")
        append(" ringCutAlphaRange=(").append(RING_CUT_ALPHA_PLAY).append(",").append(RING_CUT_ALPHA_PAUSE).append(")")
        append(" vinylRotationMs=").append(VINYL_ROTATION_DURATION_MS)
    }
    val vinylAngle = remember { Animatable(0f) }
    LaunchedEffect(isPlaying) {
        if (!isPlaying) return@LaunchedEffect
        val degPerSec = 360f / (VINYL_ROTATION_DURATION_MS / 1_000f)
        var lastFrameNanos = withFrameNanos { it }
        while (true) {
            val frameNanos = withFrameNanos { it }
            val deltaSec = (frameNanos - lastFrameNanos).coerceAtLeast(0L) / 1_000_000_000f
            lastFrameNanos = frameNanos
            val next = (vinylAngle.value + degPerSec * deltaSec) % 360f
            vinylAngle.snapTo(if (next < 0f) next + 360f else next)
        }
    }
    val needleAngle by animateFloatAsState(
        targetValue = if (isPlaying) NEEDLE_PLAY_ANGLE_DEG else NEEDLE_PAUSE_ANGLE_DEG,
        animationSpec = tween(durationMillis = 300),
        label = "needleTilt"
    )
    val needleOffsetXDp by animateDpAsState(
        targetValue = if (isPlaying) NEEDLE_PLAY_OFFSET_X_DP else NEEDLE_PAUSE_OFFSET_X_DP,
        animationSpec = tween(durationMillis = 300),
        label = "needleOffsetX"
    )
    val needleOffsetYDp by animateDpAsState(
        targetValue = if (isPlaying) NEEDLE_PLAY_OFFSET_Y_DP else NEEDLE_PAUSE_OFFSET_Y_DP,
        animationSpec = tween(durationMillis = 300),
        label = "needleOffsetY"
    )

    LaunchedEffect(report, isPlaying) {
        Log.d(
            TAG,
            "$report ringCutAlphaCurrent=$ringCutAlpha vinylAngleCurrent=${vinylAngle.value} " +
                "needleOffsetCurrentDp=(${needleOffsetXDp.value},${needleOffsetYDp.value}) " +
                "needlePauseOffsetDp=(${NEEDLE_PAUSE_OFFSET_X_DP.value},${NEEDLE_PAUSE_OFFSET_Y_DP.value})"
        )
    }

    Box(
        modifier = modifier.size(TURN_TABLE_SIZE_DP)
    ) {
        Image(
            painter = ringMainPainter,
            contentDescription = null,
            contentScale = ContentScale.Fit,
            modifier = Modifier
                .align(Alignment.Center)
                .size(ringMainWidthDp, ringMainHeightDp)
                .graphicsLayer {
                    translationX = ringMainOffsetXPx
                    translationY = ringMainOffsetYPx
                }
        )

        Image(
            painter = ringCutPainter,
            contentDescription = null,
            contentScale = ContentScale.Fit,
            modifier = Modifier
                .align(Alignment.Center)
                .size(ringCutWidthDp, ringCutHeightDp)
                .graphicsLayer {
                    alpha = ringCutAlpha
                    translationX = ringCutOffsetXPx
                    translationY = ringCutOffsetYPx
                }
        )

        Box(
            modifier = Modifier
                .align(Alignment.Center)
                .size(vinylContainerSizeDp)
                .graphicsLayer {
                    translationX = vinylOffsetXPx
                    translationY = vinylOffsetYPx + vinylGroupOffsetYPx
                }
                .clip(CircleShape)
                .clickable(onClick = onTogglePlayPause),
            contentAlignment = Alignment.Center
        ) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .graphicsLayer {
                        transformOrigin = TransformOrigin.Center
                        rotationZ = vinylAngle.value
                    },
                contentAlignment = Alignment.Center
            ) {
                Image(
                    painter = vinylPainter,
                    contentDescription = null,
                    contentScale = ContentScale.Fit,
                    colorFilter = vinylColorFilter,
                    modifier = Modifier
                        .fillMaxSize()
                        .offset(x = VINYL_IMAGE_OFFSET_X_DP, y = VINYL_IMAGE_OFFSET_Y_DP)
                )
            }
        }

        Image(
            painter = needlePainter,
            contentDescription = null,
            contentScale = ContentScale.Fit,
            modifier = Modifier
                .align(Alignment.Center)
                .size(needleWidthDp, needleHeightDp)
                .offset(x = needleOffsetXDp, y = needleOffsetYDp + VINYL_GROUP_OFFSET_Y_DP)
                .graphicsLayer {
                    transformOrigin = TransformOrigin(NEEDLE_PIVOT_X, NEEDLE_PIVOT_Y)
                    rotationZ = needleAngle
                }
        )
    }
}
