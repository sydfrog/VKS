package com.binnight.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import com.binnight.app.ui.MainScreen
import com.binnight.app.ui.theme.BinNightTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            BinNightTheme {
                MainScreen()
            }
        }
    }
}
