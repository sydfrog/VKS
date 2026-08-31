package com.binnight.app.data

import java.time.LocalDate

/** The three kerbside streams in The Hills, plus an "unknown" fallback. */
enum class BinType(val label: String, val lidColour: Long, val emoji: String) {
    GENERAL("General waste", 0xFF757575, "🗑️"),   // grey/red lid
    RECYCLING("Recycling", 0xFFFFC107, "♻️"),          // yellow lid
    ORGANICS("Garden / FOGO", 0xFF2E7D32, "🌿"),        // green lid
    OTHER("Other collection", 0xFF546E7A, "📦");

    companion object {
        /** Classify a raw service name from the API into a bin stream. */
        fun fromServiceName(raw: String): BinType {
            val n = raw.lowercase()
            return when {
                listOf("recycl", "yellow", "commingle", "co-mingle").any { it in n } -> RECYCLING
                listOf("organic", "garden", "fogo", "green waste", "vegetation", "green bin")
                    .any { it in n } -> ORGANICS
                listOf("general", "garbage", "rubbish", "waste", "red", "domestic", "landfill")
                    .any { it in n } -> GENERAL
                else -> OTHER
            }
        }
    }
}

/** A property returned by the address search. */
data class PropertyMatch(
    val propertyKey: String,
    val address: String,
)

/** One bin stream's next collection. */
data class BinCollection(
    val type: BinType,
    val rawName: String,
    val nextDate: LocalDate,
)

/**
 * Everything the UI needs to answer "which bins this week?".
 * [dueNext] are the bins going out on the soonest upcoming [nextDate];
 * [upcoming] is the full sorted list so a user can glance ahead.
 */
data class BinSchedule(
    val address: String,
    val nextDate: LocalDate?,
    val dueNext: List<BinCollection>,
    val upcoming: List<BinCollection>,
)
