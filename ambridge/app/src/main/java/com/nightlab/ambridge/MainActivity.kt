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
            text = "Export an app inventory containing each installed app's display name, package ID, version, app type, and icon. The export is saved to your phone's Downloads folder so the desktop manager can import it."
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
            text = "Privacy: the inventory is created on this device and saved locally. This app does not upload your app list or icons to a server."
            textSize = 12f
            setTextColor(0xFF586579.toInt())
            setPadding(0, dp(18), 0, 0)
        }, matchWrap())
        val scroll = ScrollView(this)
        scroll.addView(outer)
        setContentView(scroll)
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
                val apps = installedApplications()
                val entries = JSONArray()
                for (info in apps) {
                    val item = JSONObject()
                    item.put("packageName", info.packageName)
                    item.put("label", safeLabel(info))
                    item.put("systemApp", (info.flags and ApplicationInfo.FLAG_SYSTEM) != 0)
                    item.put("iconPngBase64", iconAsBase64(info))
                    try {
                        @Suppress("DEPRECATION")
                        val version = packageManager.getPackageInfo(info.packageName, 0)
                        item.put("versionName", version.versionName ?: "")
                        item.put("versionCode", if (android.os.Build.VERSION.SDK_INT >= 28) {
                            version.longVersionCode
                        } else {
                            @Suppress("DEPRECATION")
                            version.versionCode.toLong()
                        })
                    } catch (_: Exception) {
                        item.put("versionName", "")
                        item.put("versionCode", 0)
                    }
                    entries.put(item)
                }

                val root = JSONObject()
                root.put("schemaVersion", 1)
                root.put("app", "NightLab AMBridge")
                root.put("packageName", packageName)
                root.put("exportedAt", SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ssXXX", Locale.US).format(Date()))
                root.put("deviceManufacturer", android.os.Build.MANUFACTURER ?: "")
                root.put("deviceModel", android.os.Build.MODEL ?: "")
                root.put("androidRelease", android.os.Build.VERSION.RELEASE ?: "")
                root.put("applications", entries)

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
                    status.text = "Export complete\n" + apps.size + " apps written to Downloads/NightLab AMBridge/" + fileName
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
