package pl.plagcheck.app

import android.annotation.SuppressLint
import android.content.ActivityNotFoundException
import android.content.ContentValues
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.os.Environment
import android.print.PrintAttributes
import android.print.PrintManager
import android.provider.MediaStore
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.webkit.JavascriptInterface
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import java.io.File
import java.util.concurrent.Executors

/**
 * Cała aplikacja działa w telefonie: Python (Chaquopy) uruchamia serwer PlagCheck na 127.0.0.1,
 * a WebView wyświetla jego interfejs. Internet jest potrzebny tylko do wyszukiwania fraz.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var root: FrameLayout
    private lateinit var web: WebView
    private lateinit var loading: View
    private lateinit var loadingText: TextView
    private var baseUrl: String = ""
    private var fileCallback: ValueCallback<Array<Uri>>? = null
    private val worker = Executors.newSingleThreadExecutor()

    private val pickOne = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        fileCallback?.onReceiveValue(uri?.let { arrayOf(it) })
        fileCallback = null
    }
    private val pickMany = registerForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        fileCallback?.onReceiveValue(uris.toTypedArray())
        fileCallback = null
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        root = FrameLayout(this)
        web = WebView(this).apply { visibility = View.INVISIBLE }
        loading = buildLoadingView()
        root.addView(web, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
        root.addView(loading, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
        setContentView(root)

        // Android 15 rysuje pod paskami systemowymi — odsuwamy treść o ich wysokość.
        ViewCompat.setOnApplyWindowInsetsListener(root) { v, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout())
            val ime = insets.getInsets(WindowInsetsCompat.Type.ime())
            v.setPadding(bars.left, bars.top, bars.right, maxOf(bars.bottom, ime.bottom))
            WindowInsetsCompat.CONSUMED
        }

        configureWebView()
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (web.canGoBack()) web.goBack() else finish()
            }
        })
        startBackend()
    }

    private fun buildLoadingView(): View {
        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setPadding(48, 48, 48, 48)
        }
        box.addView(ProgressBar(this))
        loadingText = TextView(this).apply {
            text = "Uruchamianie PlagCheck…"
            textSize = 16f
            gravity = Gravity.CENTER
            setPadding(0, 32, 0, 0)
        }
        box.addView(loadingText)
        return box
    }

    private fun startBackend() {
        worker.execute {
            try {
                val modelDir = prepareModel()
                if (!Python.isStarted()) Python.start(AndroidPlatform(this))
                val dataDir = File(filesDir, "data").apply { mkdirs() }
                val port = Python.getInstance().getModule("app.mobile")
                    .callAttr("start", dataDir.absolutePath, modelDir?.absolutePath ?: "")
                    .toInt()
                baseUrl = "http://127.0.0.1:$port"
                val clearCache = webCacheIsStale()
                runOnUiThread {
                    // Po aktualizacji APK pamięć podręczna WebView może trzymać stary interfejs.
                    if (clearCache) web.clearCache(true)
                    web.loadUrl("$baseUrl/app")
                    web.visibility = View.VISIBLE
                    loading.visibility = View.GONE
                }
            } catch (e: Throwable) {
                runOnUiThread { loadingText.text = "Nie udało się uruchomić aplikacji:\n\n${e.message}" }
            }
        }
    }

    /** True raz po każdej instalacji nowej wersji — wtedy czyścimy pamięć podręczną WebView. */
    private fun webCacheIsStale(): Boolean {
        val marker = File(filesDir, "webview-cache.version")
        val version = packageManager.getPackageInfo(packageName, 0).longVersionCode.toString()
        if (marker.isFile && marker.readText() == version) return false
        marker.writeText(version)
        return true
    }

    /** Kopiuje model parafraz z APK do pamięci telefonu (raz na wersję aplikacji). */
    private fun prepareModel(): File? {
        val files = try { assets.list("model")?.toList().orEmpty() } catch (e: Exception) { emptyList() }
        if ("plagcheck_model.npz" !in files || "config.json" !in files) return null
        val dir = File(filesDir, "model")
        val marker = File(dir, ".version")
        val version = packageManager.getPackageInfo(packageName, 0).longVersionCode.toString()
        if (marker.isFile && marker.readText() == version) return dir
        runOnUiThread { loadingText.text = "Przygotowanie modelu wykrywania parafraz (jednorazowo)…" }
        dir.deleteRecursively()
        dir.mkdirs()
        for (name in files) {
            assets.open("model/$name").use { input ->
                File(dir, name).outputStream().use { output -> input.copyTo(output, 1 shl 20) }
            }
        }
        marker.writeText(version)
        return dir
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun configureWebView() {
        web.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            allowFileAccess = false
            allowContentAccess = true
            mediaPlaybackRequiresUserGesture = true
        }
        web.addJavascriptInterface(Bridge(), "AndroidBridge")
        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                val url = request.url.toString()
                if (baseUrl.isNotEmpty() && url.startsWith(baseUrl)) return false
                // Linki do źródeł, Google, mailto — w przeglądarce / aplikacji systemowej.
                try {
                    startActivity(Intent(Intent.ACTION_VIEW, request.url))
                } catch (e: ActivityNotFoundException) {
                    Toast.makeText(this@MainActivity, "Brak aplikacji do otwarcia linku", Toast.LENGTH_SHORT).show()
                }
                return true
            }
        }
        web.webChromeClient = object : WebChromeClient() {
            override fun onShowFileChooser(
                view: WebView, callback: ValueCallback<Array<Uri>>, params: FileChooserParams
            ): Boolean {
                fileCallback?.onReceiveValue(null)
                fileCallback = callback
                val types = arrayOf(
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "application/pdf", "application/vnd.oasis.opendocument.text", "text/plain",
                    "application/octet-stream",
                )
                if (params.mode == FileChooserParams.MODE_OPEN_MULTIPLE) pickMany.launch(types) else pickOne.launch(types)
                return true
            }
        }
    }

    /** Funkcje dostępne z JavaScriptu jako window.AndroidBridge. */
    inner class Bridge {
        @JavascriptInterface
        fun saveFile(name: String, mime: String, content: String): String {
            val safe = name.replace(Regex("[^A-Za-z0-9._ -]"), "_").take(120)
            val values = ContentValues().apply {
                put(MediaStore.Downloads.DISPLAY_NAME, safe)
                put(MediaStore.Downloads.MIME_TYPE, mime)
                put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/PlagCheck")
            }
            val uri = contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
                ?: return "Nie udało się zapisać pliku."
            contentResolver.openOutputStream(uri)?.use { it.write(content.toByteArray(Charsets.UTF_8)) }
            return "Zapisano w Pobrane/PlagCheck/$safe"
        }

        @JavascriptInterface
        fun printPage(title: String) {
            runOnUiThread {
                val manager = getSystemService(PRINT_SERVICE) as PrintManager
                val job = "PlagCheck – " + title.take(60)
                manager.print(job, web.createPrintDocumentAdapter(job), PrintAttributes.Builder().build())
            }
        }

        @JavascriptInterface
        fun toast(message: String) {
            runOnUiThread { Toast.makeText(this@MainActivity, message, Toast.LENGTH_LONG).show() }
        }
    }

    override fun onDestroy() {
        worker.shutdown()
        super.onDestroy()
    }
}
