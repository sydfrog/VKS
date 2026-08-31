package com.binnight.app.ui

import android.Manifest
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.LocationOn
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.binnight.app.data.BinCollection
import com.binnight.app.data.BinSchedule
import com.binnight.app.data.PropertyMatch
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.time.temporal.ChronoUnit

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MainScreen(viewModel: MainViewModel = viewModel()) {
    val state by viewModel.state.collectAsStateWithLifecycle()

    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { grants ->
        if (grants.values.any { it }) viewModel.locateViaGps()
        else viewModel.onLocationPermissionDenied()
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Bin Night?", fontWeight = FontWeight.Bold) },
                actions = {
                    if (state.phase == Phase.Result) {
                        IconButton(onClick = viewModel::refresh) {
                            Icon(Icons.Default.Refresh, contentDescription = "Refresh")
                        }
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.primary,
                    titleContentColor = Color.White,
                    actionIconContentColor = Color.White,
                ),
            )
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(20.dp),
        ) {
            when (state.phase) {
                Phase.Result -> ResultView(
                    schedule = state.schedule,
                    onEdit = viewModel::editAddress,
                )
                Phase.ChoosingMatch -> MatchChooser(
                    matches = state.matches,
                    onPick = viewModel::selectMatch,
                    onBack = viewModel::editAddress,
                )
                else -> AddressEntry(
                    query = state.query,
                    busy = state.phase == Phase.Searching ||
                        state.phase == Phase.LoadingSchedule,
                    gpsBusy = state.gpsInProgress,
                    onQueryChange = viewModel::onQueryChange,
                    onSearch = viewModel::search,
                    onGps = {
                        permissionLauncher.launch(
                            arrayOf(
                                Manifest.permission.ACCESS_FINE_LOCATION,
                                Manifest.permission.ACCESS_COARSE_LOCATION,
                            )
                        )
                    },
                )
            }

            state.error?.let { msg ->
                Card(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(top = 16.dp),
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.errorContainer,
                    ),
                ) {
                    Text(
                        msg,
                        modifier = Modifier.padding(16.dp),
                        color = MaterialTheme.colorScheme.onErrorContainer,
                    )
                }
            }
        }
    }
}

@Composable
private fun AddressEntry(
    query: String,
    busy: Boolean,
    gpsBusy: Boolean,
    onQueryChange: (String) -> Unit,
    onSearch: () -> Unit,
    onGps: () -> Unit,
) {
    Text(
        "Which bins go out this week?",
        style = MaterialTheme.typography.headlineSmall,
        fontWeight = FontWeight.Bold,
    )
    Spacer(Modifier.size(6.dp))
    Text(
        "Find your collection day by address, or use your location.",
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
    Spacer(Modifier.size(20.dp))

    OutlinedTextField(
        value = query,
        onValueChange = onQueryChange,
        modifier = Modifier.fillMaxWidth(),
        label = { Text("Your address") },
        placeholder = { Text("e.g. 12 Smith St, Baulkham Hills") },
        singleLine = true,
        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
        keyboardActions = KeyboardActions(onSearch = { onSearch() }),
        trailingIcon = { Icon(Icons.Default.Search, contentDescription = null) },
    )
    Spacer(Modifier.size(12.dp))

    Button(
        onClick = onSearch,
        enabled = !busy && !gpsBusy,
        modifier = Modifier.fillMaxWidth(),
    ) {
        if (busy) {
            CircularProgressIndicator(
                modifier = Modifier.size(20.dp),
                strokeWidth = 2.dp,
                color = Color.White,
            )
        } else {
            Text("Check my bins")
        }
    }
    Spacer(Modifier.size(8.dp))

    OutlinedButton(
        onClick = onGps,
        enabled = !busy && !gpsBusy,
        modifier = Modifier.fillMaxWidth(),
    ) {
        if (gpsBusy) {
            CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp)
            Spacer(Modifier.width(10.dp))
            Text("Finding your address…")
        } else {
            Icon(Icons.Default.LocationOn, contentDescription = null)
            Spacer(Modifier.width(8.dp))
            Text("Use my location")
        }
    }
}

@Composable
private fun MatchChooser(
    matches: List<PropertyMatch>,
    onPick: (PropertyMatch) -> Unit,
    onBack: () -> Unit,
) {
    Text(
        "Which one is you?",
        style = MaterialTheme.typography.headlineSmall,
        fontWeight = FontWeight.Bold,
    )
    Spacer(Modifier.size(12.dp))
    matches.forEach { match ->
        Card(
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = 4.dp)
                .clickable { onPick(match) },
        ) {
            Text(match.address, modifier = Modifier.padding(16.dp))
        }
    }
    Spacer(Modifier.size(12.dp))
    TextButton(onClick = onBack) { Text("← Search again") }
}

@Composable
private fun ResultView(schedule: BinSchedule?, onEdit: () -> Unit) {
    if (schedule == null) return

    Text(
        schedule.address,
        style = MaterialTheme.typography.titleMedium,
        fontWeight = FontWeight.SemiBold,
    )
    Spacer(Modifier.size(16.dp))

    if (schedule.nextDate == null || schedule.dueNext.isEmpty()) {
        Card(modifier = Modifier.fillMaxWidth()) {
            Text(
                "No upcoming collections found for this address. " +
                    "Tap edit to try a different address.",
                modifier = Modifier.padding(20.dp),
            )
        }
    } else {
        NextCollectionCard(schedule.nextDate, schedule.dueNext)
        val later = schedule.upcoming.filter { it.nextDate != schedule.nextDate }
        if (later.isNotEmpty()) {
            Spacer(Modifier.size(20.dp))
            Text("Coming up", style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.Bold)
            Spacer(Modifier.size(8.dp))
            later.forEach { UpcomingRow(it) }
        }
    }

    Spacer(Modifier.size(24.dp))
    OutlinedButton(onClick = onEdit, modifier = Modifier.fillMaxWidth()) {
        Text("Not right? Edit address")
    }
}

@Composable
private fun NextCollectionCard(date: LocalDate, bins: List<BinCollection>) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.primary,
        ),
    ) {
        Column(Modifier.padding(24.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            Text(
                relativeDay(date).uppercase(),
                color = Color.White.copy(alpha = 0.85f),
                fontWeight = FontWeight.Bold,
                letterSpacing = 1.sp,
            )
            Text(
                date.format(HEADLINE_DATE),
                color = Color.White,
                fontSize = 26.sp,
                fontWeight = FontWeight.Bold,
                textAlign = TextAlign.Center,
            )
            Spacer(Modifier.size(20.dp))
            Text("Put out", color = Color.White.copy(alpha = 0.85f))
            Spacer(Modifier.size(10.dp))
            bins.forEach { bin ->
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 6.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    BinDot(bin)
                    Spacer(Modifier.width(14.dp))
                    Text(
                        "${bin.type.emoji}  ${bin.type.label}",
                        color = Color.White,
                        fontSize = 18.sp,
                        fontWeight = FontWeight.SemiBold,
                    )
                }
            }
        }
    }
}

@Composable
private fun UpcomingRow(bin: BinCollection) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        BinDot(bin)
        Spacer(Modifier.width(12.dp))
        Text("${bin.type.emoji} ${bin.type.label}", modifier = Modifier.width(160.dp))
        Spacer(Modifier.width(8.dp))
        Column {
            Text(bin.nextDate.format(ROW_DATE), fontWeight = FontWeight.SemiBold)
            Text(
                relativeDay(bin.nextDate),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun BinDot(bin: BinCollection) {
    Box(
        modifier = Modifier
            .size(18.dp)
            .background(Color(bin.type.lidColour), CircleShape),
    )
}

private val HEADLINE_DATE = DateTimeFormatter.ofPattern("EEEE d MMMM")
private val ROW_DATE = DateTimeFormatter.ofPattern("EEE d MMM")

private fun relativeDay(date: LocalDate): String {
    val days = ChronoUnit.DAYS.between(LocalDate.now(), date)
    return when {
        days < 0L -> "Past"
        days == 0L -> "Today"
        days == 1L -> "Tomorrow"
        days < 7L -> "This week"
        days < 14L -> "Next week"
        else -> "In $days days"
    }
}
