package com.tagundo.elichika

import android.app.Activity
import com.google.android.material.tabs.TabLayout

/** Select semantic destinations so adding a tab cannot silently test another page. */
internal object NativeTabsQa {
    fun tab(activity: Activity, id: String): TabLayout.Tab {
        val tabs = activity.findViewById<TabLayout>(R.id.tabs)
        return (0 until tabs.tabCount).mapNotNull(tabs::getTabAt).single { it.tag == id }
    }

    fun selectedId(activity: Activity): String? {
        val tabs = activity.findViewById<TabLayout>(R.id.tabs)
        return tabs.getTabAt(tabs.selectedTabPosition)?.tag as? String
    }
}
