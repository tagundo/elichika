#pragma once
// Pure rules behind SIFASMVCornerHold.mm, kept free of UIKit so a host C++17
// compiler can test them (tests/CornerHoldTests.cpp).
#include <cmath>
#include <cstddef>
#include <cstring>
#include <string>

namespace elichika {
namespace corner {
struct Rect { double x, y, width, height; };
struct Insets { double top, right; };
struct Point { double x, y; };

// _settingsShortcutContains (0x533c) in the pinned SIFASFeatures.dylib:
// x in [max(minX, R - 90), R), y in [T, min(maxY, T + 44)) where
// R = maxX - safeRight - 8 and T = minY + safeTop + 8. The recognizer's
// duration is the immediate 2.0 passed to setMinimumPressDuration: (0x4140).
constexpr double originalInset = 8, originalWidth = 90, originalHeight = 44;
constexpr long originalMilliseconds = 2000;

// The Android in-game panel's choices (dp there, points here).
constexpr long pointChoices[] = {32, 48, 64, 96, 128, 160};
constexpr long millisecondChoices[] = {500, 1000, 1500, 2000, 3000, 4000, 5000};

inline bool usable(const Rect &bounds, const Insets &safe) {
    const double values[] = {bounds.x, bounds.y, bounds.width, bounds.height, safe.top, safe.right};
    for (double value : values)
        if (!std::isfinite(value)) return false;
    return bounds.width > 0 && bounds.height > 0 && safe.top >= 0 && safe.right >= 0;
}

// The centre of the original rectangle; NaN when the view is unusable.
inline Point originalAreaCentre(const Rect &bounds, const Insets &safe) {
    if (!usable(bounds, safe)) return {NAN, NAN};
    const double right = bounds.x + bounds.width - safe.right - originalInset;
    const double left = std::fmax(bounds.x, right - originalWidth);
    const double top = bounds.y + safe.top + originalInset;
    const double bottom = std::fmin(bounds.y + bounds.height, top + originalHeight);
    return {(left + right) / 2, (top + bottom) / 2};
}

// A square of edge points at the safe-area upper-right corner, edges
// included, clamped to the view (Android's CornerHold.inCorner measures from
// the decor view's corner the same way).
inline bool insideCorner(const Rect &bounds, const Insets &safe, Point point, double edge) {
    if (!usable(bounds, safe) || !(edge > 0) || !std::isfinite(point.x) || !std::isfinite(point.y)) return false;
    const double right = bounds.x + bounds.width - safe.right, top = bounds.y + safe.top;
    const double left = std::fmax(bounds.x, right - edge);
    const double bottom = std::fmin(bounds.y + bounds.height, top + edge);
    return left < right && top < bottom && point.x >= left && point.x <= right &&
           point.y >= top && point.y <= bottom;
}

// A saved number counts only when it is exactly one of the choices; 0 means
// "not set" and keeps the original behaviour.
template <size_t count>
long validChoice(double raw, const long (&choices)[count]) {
    for (long choice : choices)
        if (raw == double(choice)) return choice;
    return 0;
}

// "0.5", "1", "1.5": every choice is a multiple of 500 ms.
inline std::string seconds(long milliseconds) {
    std::string text = std::to_string(milliseconds / 1000);
    if (milliseconds % 1000) text += "." + std::to_string(milliseconds % 1000 / 100);
    return text;
}

// The settings menu (its format string is loaded at 0x5924) and every one-off
// status or error alert of the static _message() helper (0x5b10, for example
// "Saved. Restart the game to apply the server URL.") share the title "Client
// settings" and the alert style. Of all the strings in the pinned binary, only
// the menu's format mentions the corner hold, so only that alert gets the
// corner-hold hint and action.
constexpr char settingsMenuMarker[] = "hold the upper-right corner";
inline bool isSettingsMenu(const char *message) {
    return message && std::strstr(message, settingsMenuMarker);
}

// The English sentence fragment SIFASFeatures' menu hint formats with
// "%.0f seconds" and 2.0. points 0 is the original area.
inline std::string hintPhrase(long points, long milliseconds) {
    std::string phrase = "hold the upper-right corner";
    if (points) phrase += " (" + std::to_string(points) + " × " + std::to_string(points) + " pt)";
    return phrase + " in game for " + seconds(milliseconds) + (milliseconds == 1000 ? " second" : " seconds");
}
}
}
