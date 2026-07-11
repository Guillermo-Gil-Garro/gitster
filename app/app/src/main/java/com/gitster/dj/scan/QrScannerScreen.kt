package com.gitster.dj.scan

import android.Manifest
import android.os.SystemClock
import android.util.Log
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.BlendMode
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.CompositingStrategy
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.gitster.dj.R
import com.gitster.dj.ui.AnimatedNeonBorder

private const val TAG = "QrScannerScreen"

/** The same QR must stay inside the frame this long before it fires. */
private const val HOLD_MS = 420L

/** Minimum interval between two accepted scans. */
private const val FIRE_COOLDOWN_MS = 900L

/** If the candidate is not re-seen within this window, treat the next sighting as new. */
private const val CANDIDATE_STALE_MS = 800L

/**
 * Full-screen QR scanner: camera permission flow, CameraX + ML Kit preview
 * limited to the viewfinder ROI, and a hold debounce so the QR must be
 * deliberately aimed before [onScanned] fires.
 */
@Composable
fun QrScannerScreen(
    onScanned: (String) -> Unit,
    onClose: () -> Unit
) {
    var hasCameraPermission by remember { mutableStateOf(false) }
    val permissionLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission()
    ) { granted ->
        hasCameraPermission = granted
        if (!granted) onClose()
    }

    LaunchedEffect(Unit) {
        permissionLauncher.launch(Manifest.permission.CAMERA)
    }

    if (!hasCameraPermission) {
        Box(Modifier.fillMaxSize().background(Color.Black)) {
            Text(
                stringResource(R.string.scan_camera_permission),
                color = Color.White,
                modifier = Modifier.align(Alignment.Center)
            )
        }
        return
    }

    // Hold debounce: fire only after the same QR stays in the frame for a
    // while, without ever blocking the camera (a failed resolution must not
    // leave the scanner dead).
    var candidateValue by remember { mutableStateOf<String?>(null) }
    var candidateSinceMs by remember { mutableLongStateOf(0L) }
    var candidateLastSeenMs by remember { mutableLongStateOf(0L) }
    var lastFireMs by remember { mutableLongStateOf(0L) }

    fun onQrInFrame(raw: String) {
        val now = SystemClock.elapsedRealtime()
        val stale = (now - candidateLastSeenMs) > CANDIDATE_STALE_MS
        if (raw != candidateValue || stale) {
            candidateValue = raw
            candidateSinceMs = now
            candidateLastSeenMs = now
            return
        }

        candidateLastSeenMs = now
        val heldFor = now - candidateSinceMs
        if (heldFor >= HOLD_MS && (now - lastFireMs) >= FIRE_COOLDOWN_MS) {
            lastFireMs = now
            Log.d(TAG, "QR accepted after ${heldFor}ms hold")
            onScanned(raw)
        }
    }

    Box(
        Modifier
            .fillMaxSize()
            .safeDrawingPadding()
    ) {
        QrCameraPreview(
            modifier = Modifier.fillMaxSize(),
            onCameraError = onClose,
            onQrInFrame = ::onQrInFrame
        )

        ViewfinderOverlay(
            modifier = Modifier.fillMaxSize(),
            onClose = onClose
        )
    }
}

@Composable
private fun ViewfinderOverlay(
    modifier: Modifier = Modifier,
    onClose: () -> Unit
) {
    val dim = Color(0xAA000000)
    val cornerRadiusDp = 26.dp

    BoxWithConstraints(modifier) {
        val w = maxWidth
        val h = maxHeight

        // Keep in sync with QR_FRAME_WIDTH_FRACTION (square frame).
        val frameW = w * QR_FRAME_WIDTH_FRACTION
        val frameH = frameW

        val left = (w - frameW) / 2
        val top = (h - frameH) / 2

        Canvas(
            modifier = Modifier
                .fillMaxSize()
                .graphicsLayer {
                    compositingStrategy = CompositingStrategy.Offscreen
                }
        ) {
            val radiusPx = cornerRadiusDp.toPx()

            // Full-screen dim with a transparent rounded hole for the frame.
            drawRect(color = dim)
            drawRoundRect(
                color = Color.Transparent,
                topLeft = Offset(left.toPx(), top.toPx()),
                size = Size(frameW.toPx(), frameH.toPx()),
                cornerRadius = CornerRadius(radiusPx, radiusPx),
                blendMode = BlendMode.Clear
            )
        }

        AnimatedNeonBorder(
            modifier = Modifier
                .offset(x = left, y = top)
                .size(width = frameW, height = frameH),
            shape = RoundedCornerShape(cornerRadiusDp),
            strokeDp = 3.dp,
            isAnimated = true
        )

        Row(
            Modifier
                .fillMaxWidth()
                .padding(14.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                stringResource(R.string.brand_name),
                color = Color.White,
                fontWeight = FontWeight.Black
            )
            TextButton(onClick = onClose) {
                Text(
                    stringResource(R.string.scan_exit),
                    color = Color.White,
                    fontWeight = FontWeight.SemiBold
                )
            }
        }

        Text(
            stringResource(R.string.scan_instruction),
            color = Color.White,
            modifier = Modifier
                .align(Alignment.Center)
                .offset(y = (-frameH / 2) - 30.dp)
        )
    }
}
