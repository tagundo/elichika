/* Pure overlay policy and safe-area geometry. No UIKit or game dependencies. */
#ifndef SIFAS_SETTINGS_OVERLAY_H
#define SIFAS_SETTINGS_OVERLAY_H

typedef struct {
    double left, top, right, bottom;
    int valid;
} SIFASSettingsShortcutRegion;

static inline int SIFASSettingsButtonVisible(int preferencePresent, int savedValue) {
    return !preferencePresent || savedValue;
}

static inline SIFASSettingsShortcutRegion SIFASSettingsShortcutBounds(
    double originX, double originY, double width, double height,
    double insetTop, double insetRight) {
    SIFASSettingsShortcutRegion region = {0, 0, 0, 0, 0};
    if (!__builtin_isfinite(originX) || !__builtin_isfinite(originY) ||
        !__builtin_isfinite(width) || !__builtin_isfinite(height) ||
        !__builtin_isfinite(insetTop) || !__builtin_isfinite(insetRight) ||
        width <= 0 || height <= 0 || insetTop < 0 || insetRight < 0) return region;
    region.right = originX + width - insetRight - 8;
    region.left = region.right - 90;
    region.top = originY + insetTop + 8;
    region.bottom = region.top + 44;
    if (region.left < originX) region.left = originX;
    if (region.bottom > originY + height) region.bottom = originY + height;
    region.valid = region.left < region.right && region.top < region.bottom &&
        region.right <= originX + width && region.top >= originY &&
        __builtin_isfinite(region.left) && __builtin_isfinite(region.top) &&
        __builtin_isfinite(region.right) && __builtin_isfinite(region.bottom);
    return region;
}

static inline int SIFASSettingsShortcutContains(SIFASSettingsShortcutRegion region,
                                               double x, double y) {
    return region.valid && __builtin_isfinite(x) && __builtin_isfinite(y) &&
        x >= region.left && x < region.right && y >= region.top && y < region.bottom;
}
#endif
