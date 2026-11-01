package com.tagundo.elichika

import android.content.Context
import android.util.AttributeSet
import android.view.View
import android.view.ViewGroup
import kotlin.math.max
import kotlin.math.roundToInt

/** Reflows existing action buttons using the width of this group, including in split screen. */
class ConsoleActionGrid @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
) : ViewGroup(context, attrs) {
    var columnCount: Int = 1
        private set

    private var columnWidths = IntArray(0)
    private var rowHeights = IntArray(0)
    private val gap: Int
        get() = resources.getDimensionPixelSize(R.dimen.console_action_gap)

    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
        val fontScale = max(1f, resources.configuration.fontScale)
        val minimumColumn = (resources.getDimension(R.dimen.console_action_min_column_width) * fontScale).roundToInt()
        val width = if (MeasureSpec.getMode(widthMeasureSpec) == MeasureSpec.UNSPECIFIED) {
            minimumColumn + paddingLeft + paddingRight
        } else MeasureSpec.getSize(widthMeasureSpec)
        val available = (width - paddingLeft - paddingRight).coerceAtLeast(0)
        val children = visibleChildren()
        columnCount = ((available + gap) / (minimumColumn + gap))
            .coerceIn(1, minOf(3, children.size.coerceAtLeast(1)))
        val buttonSpace = (available - gap * (columnCount - 1)).coerceAtLeast(0)
        columnWidths = IntArray(columnCount) { column ->
            buttonSpace / columnCount + if (column < buttonSpace % columnCount) 1 else 0
        }
        rowHeights = IntArray((children.size + columnCount - 1) / columnCount)
        var childState = 0
        children.forEachIndexed { index, child ->
            child.measure(MeasureSpec.makeMeasureSpec(columnWidths[index % columnCount], MeasureSpec.EXACTLY),
                MeasureSpec.makeMeasureSpec(0, MeasureSpec.UNSPECIFIED))
            rowHeights[index / columnCount] = max(rowHeights[index / columnCount], child.measuredHeight)
            childState = combineMeasuredStates(childState, child.measuredState)
        }
        // Long translated labels can grow a row without clipping their neighbours.
        children.forEachIndexed { index, child ->
            child.measure(MeasureSpec.makeMeasureSpec(columnWidths[index % columnCount], MeasureSpec.EXACTLY),
                MeasureSpec.makeMeasureSpec(rowHeights[index / columnCount], MeasureSpec.EXACTLY))
        }
        val height = paddingTop + paddingBottom + rowHeights.sum() + gap * (rowHeights.size - 1).coerceAtLeast(0)
        setMeasuredDimension(resolveSizeAndState(width, widthMeasureSpec, childState),
            resolveSizeAndState(height, heightMeasureSpec, childState shl MEASURED_HEIGHT_STATE_SHIFT))
    }

    override fun onLayout(changed: Boolean, left: Int, top: Int, right: Int, bottom: Int) {
        val children = visibleChildren()
        var rowTop = paddingTop
        var index = 0
        for (rowHeight in rowHeights) {
            var offset = 0
            for (column in 0 until columnCount) {
                if (index >= children.size) break
                val childWidth = columnWidths[column]
                val childLeft = if (layoutDirection == LAYOUT_DIRECTION_RTL) {
                    width - paddingRight - offset - childWidth
                } else paddingLeft + offset
                children[index++].layout(childLeft, rowTop, childLeft + childWidth, rowTop + rowHeight)
                offset += childWidth + gap
            }
            rowTop += rowHeight + gap
        }
    }

    private fun visibleChildren(): List<View> =
        (0 until childCount).map { getChildAt(it) }.filter { it.visibility != GONE }

    override fun generateDefaultLayoutParams(): LayoutParams =
        LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT)
}
