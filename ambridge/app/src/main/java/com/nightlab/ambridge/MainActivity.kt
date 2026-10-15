package com.nightlab.ambridge

import android.app.Activity
import android.content.ContentValues
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.drawable.Drawable
import android.net.Uri
import android.os.Bundle
import android.os.Environment
import android.provider.MediaStore
import android.view.Gravity
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager
import android.util.Base64
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.InetAddress
import java.net.ServerSocket
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class MainActivity : Activity() {
    private lateinit var status: TextView
    private lateinit var exportButton: Button

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        buildScreen()
        refreshSummary()
        startLocalInventoryServer()
    }

    private fun buildScreen() {
        val outer = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(24), dp(28), dp(24), dp(24))
            setBackgroundColor(0xFFF5F7FB.toInt())
        }
        outer.addView(TextView(this).apply {
            text = "NightLab AMBridge"
            textSize = 26f
            setTextColor(0xFF17233A.toInt())
            gravity = Gravity.CENTER_VERTICAL
        }, matchWrap())
        outer.addView(TextView(this).apply {
            text = "App names and icons for ADB App Manager"
            textSize = 15f
            setTextColor(0xFF46536A.toInt())
            setPadding(0, dp(8), 0, dp(18))
        }, matchWrap())
        outer.addView(TextView(this).apply {
            text = "Share installed app names and icons with the desktop manager over a temporary ADB-forwarded local connection. No app list is uploaded to a remote server."
            textSize = 15f
            setTextColor(0xFF263246.toInt())
            setPadding(dp(16), dp(16), dp(16), dp(16))
            setBackgroundColor(0xFFFFFFFF.toInt())
        }, matchWrap())
        status = TextView(this).apply {
            textSize = 14f
            setTextColor(0xFF263246.toInt())
            setPadding(0, dp(20), 0, dp(16))
        }
        outer.addView(status, matchWrap())
        exportButton = Button(this).apply {
            text = "Export app names and icons"
            setOnClickListener { exportInventory() }
        }
        outer.addView(exportButton, matchWrap())
        outer.addView(Button(this).apply {
            text = "Refresh app count"
            setOnClickListener { refreshSummary() }
        }, matchWrap())
        outer.addView(TextView(this).apply {
            text = "Privacy: the bridge listens only on device loopback and serves read-only app metadata. The desktop reaches it through authorized ADB port forwarding; no remote server is used."
            textSize = 12f
            setTextColor(0xFF586579.toInt())
            setPadding(0, dp(18), 0, 0)
        }, matchWrap())
        val scroll = ScrollView(this)
        scroll.addView(outer)
        setContentView(scroll)
    }

    // Read-only HTTP endpoint available only on Android loopback. The desktop accesses it
    // through an authenticated ADB connection using adb forward; it is not exposed to Wi-Fi.
    private fun startLocalInventoryServer() {
        Thread {
            try {
                ServerSocket(39876, 8, InetAddress.getByName("127.0.0.1")).use { server ->
                    server.soTimeout = 1000
                    while (!isFinishing) {
                        try {
                            server.accept().use { client ->
                                client.soTimeout = 15000
                                val reader = BufferedReader(InputStreamReader(client.getInputStream(), Charsets.UTF_8))
                                val requestLine = reader.readLine()
                                if (requestLine != null) {
                                    while (true) {
                                        val header = reader.readLine() ?: break
                                        if (header.isEmpty()) break
                                    }
                                    val isInventoryRequest = requestLine.startsWith("GET /v1/apps ")
                                    val body = if (isInventoryRequest) buildInventoryJson().toString().toByteArray(Charsets.UTF_8)
                                        else JSONObject().put("error", "not_found").toString().toByteArray(Charsets.UTF_8)
                                    val status = if (isInventoryRequest) "200 OK" else "404 Not Found"
                                    val headers = "HTTP/1.1 $status\r\nContent-Type: application/json; charset=utf-8\r\nContent-Length: ${body.size}\r\nConnection: close\r\nCache-Control: no-store\r\n\r\n"
                                    client.getOutputStream().apply {
                                        write(headers.toByteArray(Charsets.UTF_8))
                                        write(body)
                                        flush()
                                    }
                                }
                            }
                        } catch (_: java.net.SocketTimeoutException) {
                            // Periodically check whether the activity is finishing.
                        }
                    }
                }
            } catch (e: Exception) {
                runOnUiThread {
                    if (::status.isInitialized) status.text = "Local bridge unavailable: " + (e.localizedMessage ?: "unknown error")
                }
            }
        }.apply { name = "NightLabAMBridgeServer"; isDaemon = true }.start()
    }

    private fun buildInventoryJson(): JSONObject {
        val entries = JSONArray()
        for (info in installedApplications()) {
            val item = JSONObject()
            item.put("packageName", info.packageName)
            item.put("label", safeLabel(info))
            item.put("systemApp", (info.flags and ApplicationInfo.FLAG_SYSTEM) != 0)
            item.put("iconPngBase64", iconAsBase64(info))
            try {
                @Suppress("DEPRECATION")
                val version = packageManager.getPackageInfo(info.packageName, 0)
                item.put("versionName", version.versionName ?: "")
                item.put("versionCode", if (android.os.Build.VERSION.SDK_INT >= 28) version.longVersionCode else {
                    @Suppress("DEPRECATION")
                    version.versionCode.toLong()
                })
            } catch (_: Exception) {
                item.put("versionName", "")
                item.put("versionCode", 0)
            }
            entries.put(item)
        }
        return JSONObject().apply {
            put("schemaVersion", 1)
            put("app", "NightLab AMBridge")
            put("packageName", packageName)
            put("exportedAt", SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ssXXX", Locale.US).format(Date()))
            put("deviceManufacturer", android.os.Build.MANUFACTURER ?: "")
            put("deviceModel", android.os.Build.MODEL ?: "")
            put("androidRelease", android.os.Build.VERSION.RELEASE ?: "")
            put("applications", entries)
        }
    }

    private fun refreshSummary() {
        try {
            status.text = "Ready to export\n" + installedApplications().size + " installed packages found."
        } catch (e: Exception) {
            status.text = "Could not read installed apps: " + (e.localizedMessage ?: "unknown error")
        }
    }

    private fun installedApplications(): List<ApplicationInfo> {
        @Suppress("DEPRECATION")
        val list = packageManager.getInstalledApplications(PackageManager.GET_META_DATA)
        return list.sortedBy { safeLabel(it).lowercase(Locale.ROOT) }
    }

    private fun safeLabel(info: ApplicationInfo): String {
        return try {
            packageManager.getApplicationLabel(info).toString().ifBlank { info.packageName }
        } catch (_: Exception) {
            info.packageName
        }
    }

    private fun exportInventory() {
        exportButton.isEnabled = false
        status.text = "Building app inventory and icon data…"
        Thread {
            try {
                // Reuse the same schema builder as the desktop HTTP endpoint so
                // exported JSON and live inventory cannot drift apart.
                val root = buildInventoryJson()
                val appCount = root.getJSONArray("applications").length()
                val fileName = "nightlab-ambridge-app-metadata.json"
                val values = ContentValues().apply {
                    put(MediaStore.MediaColumns.DISPLAY_NAME, fileName)
                    put(MediaStore.MediaColumns.MIME_TYPE, "application/json")
                    put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/NightLab AMBridge")
                    put(MediaStore.MediaColumns.IS_PENDING, 1)
                }
                val uri: Uri = contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
                    ?: throw IllegalStateException("Android could not create the export file")
                try {
                    contentResolver.openOutputStream(uri, "w").use { output ->
                        if (output == null) throw IllegalStateException("Could not open export file")
                        output.write(root.toString(2).toByteArray(Charsets.UTF_8))
                    }
                    val done = ContentValues().apply { put(MediaStore.MediaColumns.IS_PENDING, 0) }
                    contentResolver.update(uri, done, null, null)
                } catch (e: Exception) {
                    contentResolver.delete(uri, null, null)
                    throw e
                }

                runOnUiThread {
                    status.text = "Export complete\n" + appCount + " apps written to Downloads/NightLab AMBridge/" + fileName
                    Toast.makeText(this, "App metadata exported", Toast.LENGTH_LONG).show()
                    exportButton.isEnabled = true
                }
            } catch (e: Exception) {
                runOnUiThread {
                    status.text = "Export failed: " + (e.localizedMessage ?: "unknown error")
                    exportButton.isEnabled = true
                }
            }
        }.start()
    }

    private fun iconAsBase64(info: ApplicationInfo): String {
        return try {
            val drawable = packageManager.getApplicationIcon(info)
            val bitmap = drawableToBitmap(drawable)
            val bytes = ByteArrayOutputStream().use { stream ->
                bitmap.compress(Bitmap.CompressFormat.PNG, 100, stream)
                stream.toByteArray()
            }
            Base64.encodeToString(bytes, Base64.NO_WRAP)
        } catch (_: Exception) {
            ""
        }
    }

    private fun drawableToBitmap(drawable: Drawable): Bitmap {
        val bitmap = Bitmap.createBitmap(96, 96, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(bitmap)
        drawable.setBounds(0, 0, 96, 96)
        drawable.draw(canvas)
        return bitmap
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

    private fun matchWrap() = LinearLayout.LayoutParams(
        ViewGroup.LayoutParams.MATCH_PARENT,
        ViewGroup.LayoutParams.WRAP_CONTENT
    )
}
