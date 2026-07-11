package com.gitster.dj.scan

import android.annotation.SuppressLint
import android.util.Log
import android.util.Size
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.google.mlkit.vision.barcode.BarcodeScanner
import com.google.mlkit.vision.barcode.BarcodeScannerOptions
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.common.InputImage
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import kotlin.math.max
import kotlin.math.min

private const val TAG = "QrCameraPreview"

/** Width of the square viewfinder as a fraction of the preview width. */
internal const val QR_FRAME_WIDTH_FRACTION = 0.78f

/** Extra inset (fraction of the frame side) so QRs scraping the edge don't fire. */
private const val ROI_MARGIN_FRACTION = 0.03f

/** Minimum QR side (normalized over the image) — rejects codes that are too far away. */
private const val MIN_QR_NORMALIZED_SIZE = 0.09f

/** Normalized rect (0..1) over the upright analysis image. */
data class NormalizedRect(
    val left: Float,
    val top: Float,
    val right: Float,
    val bottom: Float
) {
    fun contains(x: Float, y: Float): Boolean = (x in left..right) && (y in top..bottom)
}

/**
 * CameraX preview + ML Kit QR analysis restricted to the centered square
 * viewfinder. [onQrInFrame] is invoked on the main thread with the raw
 * payload every time a QR is detected inside the frame (no debounce here;
 * the caller decides when to accept it).
 */
@Composable
fun QrCameraPreview(
    modifier: Modifier = Modifier,
    onCameraError: () -> Unit,
    onQrInFrame: (String) -> Unit
) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current

    val cameraProviderState = remember { mutableStateOf<ProcessCameraProvider?>(null) }
    val executor: ExecutorService = remember { Executors.newSingleThreadExecutor() }

    DisposableEffect(Unit) {
        onDispose {
            runCatching { cameraProviderState.value?.unbindAll() }
            executor.shutdown()
        }
    }

    AndroidView(
        modifier = modifier,
        factory = { ctx ->
            val previewView = PreviewView(ctx).apply {
                scaleType = PreviewView.ScaleType.FILL_CENTER
            }

            val cameraProviderFuture = ProcessCameraProvider.getInstance(ctx)
            cameraProviderFuture.addListener({
                val cameraProvider = cameraProviderFuture.get()
                cameraProviderState.value = cameraProvider

                val preview = Preview.Builder()
                    .build()
                    .also { it.setSurfaceProvider(previewView.surfaceProvider) }

                val options = BarcodeScannerOptions.Builder()
                    .setBarcodeFormats(Barcode.FORMAT_QR_CODE)
                    .build()
                val scanner = BarcodeScanning.getClient(options)

                val analysis = ImageAnalysis.Builder()
                    .setTargetResolution(Size(1280, 720))
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                    .build()

                analysis.setAnalyzer(executor) { imageProxy ->
                    analyzeFrame(
                        scanner = scanner,
                        imageProxy = imageProxy,
                        viewWidth = previewView.width,
                        viewHeight = previewView.height
                    ) { raw ->
                        // Jump to the main thread: onQrInFrame mutates Compose state.
                        ContextCompat.getMainExecutor(ctx).execute {
                            runCatching { onQrInFrame(raw) }
                        }
                    }
                }

                try {
                    cameraProvider.unbindAll()
                    cameraProvider.bindToLifecycle(
                        lifecycleOwner,
                        CameraSelector.DEFAULT_BACK_CAMERA,
                        preview,
                        analysis
                    )
                } catch (error: Throwable) {
                    Log.w(TAG, "Camera bind failed: ${error.message}")
                    ContextCompat.getMainExecutor(ctx).execute { onCameraError() }
                }
            }, ContextCompat.getMainExecutor(ctx))

            previewView
        }
    )
}

@SuppressLint("UnsafeOptInUsageError")
private fun analyzeFrame(
    scanner: BarcodeScanner,
    imageProxy: ImageProxy,
    viewWidth: Int,
    viewHeight: Int,
    onQr: (String) -> Unit
) {
    val mediaImage = imageProxy.image
    if (mediaImage == null) {
        imageProxy.close()
        return
    }

    val rotation = imageProxy.imageInfo.rotationDegrees
    val inputImage = InputImage.fromMediaImage(mediaImage, rotation)

    // ML Kit reports bounding boxes on the upright (rotated) image.
    val imageWidth = if (rotation == 90 || rotation == 270) imageProxy.height else imageProxy.width
    val imageHeight = if (rotation == 90 || rotation == 270) imageProxy.width else imageProxy.height

    val roi = viewfinderRoiOnImage(
        viewWidth = viewWidth,
        viewHeight = viewHeight,
        imageWidth = imageWidth,
        imageHeight = imageHeight
    )
    if (roi == null) {
        // Preview not laid out yet; skip the frame instead of guessing.
        imageProxy.close()
        return
    }

    scanner.process(inputImage)
        .addOnSuccessListener { barcodes ->
            val best = barcodes
                .filter { barcode ->
                    val raw = barcode.rawValue?.trim()
                    val box = barcode.boundingBox
                    if (raw.isNullOrBlank() || box == null) return@filter false

                    val cx = box.exactCenterX() / imageWidth.toFloat()
                    val cy = box.exactCenterY() / imageHeight.toFloat()
                    if (!roi.contains(cx, cy)) return@filter false

                    val normalizedSide = min(
                        box.width() / imageWidth.toFloat(),
                        box.height() / imageHeight.toFloat()
                    )
                    normalizedSide > MIN_QR_NORMALIZED_SIZE
                }
                .maxByOrNull { it.boundingBox!!.width() * it.boundingBox!!.height() }

            val raw = best?.rawValue?.trim()
            if (!raw.isNullOrBlank()) onQr(raw)
        }
        .addOnFailureListener { error ->
            Log.d(TAG, "ML Kit frame failed: ${error.message}")
        }
        .addOnCompleteListener {
            imageProxy.close()
        }
}

/**
 * Maps the on-screen square viewfinder to a normalized ROI over the upright
 * analysis image, accounting for PreviewView FILL_CENTER (scale + center crop).
 * Returns null while the view or image sizes are unknown.
 */
internal fun viewfinderRoiOnImage(
    viewWidth: Int,
    viewHeight: Int,
    imageWidth: Int,
    imageHeight: Int
): NormalizedRect? {
    if (viewWidth <= 0 || viewHeight <= 0 || imageWidth <= 0 || imageHeight <= 0) return null

    // Viewfinder rect in view coordinates: centered square.
    val frameSide = viewWidth * QR_FRAME_WIDTH_FRACTION
    val frameLeft = (viewWidth - frameSide) / 2f
    val frameTop = (viewHeight - frameSide) / 2f

    // FILL_CENTER: the image is scaled uniformly to cover the view and centered.
    val scale = max(viewWidth / imageWidth.toFloat(), viewHeight / imageHeight.toFloat())
    val offsetX = (imageWidth * scale - viewWidth) / 2f
    val offsetY = (imageHeight * scale - viewHeight) / 2f

    fun viewXToImage(x: Float): Float = (x + offsetX) / scale / imageWidth
    fun viewYToImage(y: Float): Float = (y + offsetY) / scale / imageHeight

    val margin = frameSide * ROI_MARGIN_FRACTION
    return NormalizedRect(
        left = viewXToImage(frameLeft + margin).coerceIn(0f, 1f),
        top = viewYToImage(frameTop + margin).coerceIn(0f, 1f),
        right = viewXToImage(frameLeft + frameSide - margin).coerceIn(0f, 1f),
        bottom = viewYToImage(frameTop + frameSide - margin).coerceIn(0f, 1f)
    )
}
