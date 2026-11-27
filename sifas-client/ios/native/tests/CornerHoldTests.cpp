// Host test for SIFASMVCornerHold.hpp. Build with any C++17 compiler:
//   c++ -std=c++17 -Wall -Wextra ios/native/tests/CornerHoldTests.cpp -o corner && ./corner
// The expected centres and edges were measured by running the pinned
// SIFASFeatures.dylib's own gestureRecognizer:shouldReceiveTouch: (0x51ec)
// under an ARM64 emulator with these bounds and safe-area insets.
#include "../SIFASMVCornerHold.hpp"
#include <cassert>
#include <cmath>
#include <cstdio>

using namespace elichika::corner;

static void centre(Rect bounds, Insets safe, double x, double y) {
    const Point point = originalAreaCentre(bounds, safe);
    assert(point.x == x && point.y == y);
}

int main() {
    // Accepted by the original filter; its area is [left, right) x [top, bottom).
    centre({0, 0, 1280, 720}, {0, 0}, 1227, 30);       // [1182, 1272) x [8, 52)
    centre({0, 0, 844, 390}, {0, 47}, 744, 30);        // [699, 789) x [8, 52)
    centre({10, 20, 1024, 768}, {24, 0}, 981, 74);     // [936, 1026) x [52, 96)
    centre({0, 0, 60, 30}, {0, 0}, 26, 19);            // clamped: [0, 52) x [8, 30)
    for (const Rect bad : {Rect{0, 0, 0, 720}, Rect{0, 0, 1280, -1}, Rect{NAN, 0, 1280, 720}}) {
        const Point point = originalAreaCentre(bad, {0, 0});
        assert(std::isnan(point.x) && std::isnan(point.y));
    }
    assert(std::isnan(originalAreaCentre({0, 0, 1280, 720}, {-1, 0}).x));
    assert(std::isnan(originalAreaCentre({0, 0, 1280, 720}, {0, INFINITY}).x));

    // Square corner areas include their edges and start at the safe-area corner.
    const Rect screen{0, 0, 1280, 720};
    assert(insideCorner(screen, {0, 0}, {1216, 0}, 64));
    assert(insideCorner(screen, {0, 0}, {1280, 64}, 64));
    assert(!insideCorner(screen, {0, 0}, {1215.9, 10}, 64));
    assert(!insideCorner(screen, {0, 0}, {1250, 64.1}, 64));
    assert(insideCorner(screen, {0, 47}, {1233, 0}, 64));
    assert(!insideCorner(screen, {0, 47}, {1240, 10}, 64));      // inside the right safe-area inset
    assert(!insideCorner(screen, {24, 0}, {1270, 10}, 64));      // above the top safe-area inset
    assert(insideCorner(screen, {24, 0}, {1270, 88}, 64));
    assert(insideCorner({10, 20, 1024, 768}, {0, 0}, {1034, 20}, 32));
    assert(!insideCorner({10, 20, 1024, 768}, {0, 0}, {1001.9, 20}, 32));
    // Larger than the view: clamped to it.
    assert(insideCorner({0, 0, 40, 30}, {0, 0}, {0, 30}, 160));
    assert(!insideCorner({0, 0, 40, 30}, {0, 0}, {-0.1, 10}, 160));
    // Every square choice reaches the corner and ends exactly edge points from it.
    for (long edge : pointChoices) {
        assert(insideCorner(screen, {0, 0}, {1279, 1}, double(edge)));
        assert(!insideCorner(screen, {0, 0}, {1279 - double(edge) - 1, 1}, double(edge)));
    }
    assert(!insideCorner(screen, {0, 0}, {1270, 10}, 0));
    assert(!insideCorner(screen, {0, 0}, {1270, 10}, -64));
    assert(!insideCorner(screen, {0, 0}, {NAN, 10}, 64));
    assert(!insideCorner(screen, {0, 0}, {1270, INFINITY}, 64));
    assert(!insideCorner({0, 0, 0, 0}, {0, 0}, {0, 0}, 64));

    // Saved values count only when they are one of the choices.
    assert(validChoice(64, pointChoices) == 64);
    assert(validChoice(160, pointChoices) == 160);
    assert(validChoice(64.5, pointChoices) == 0);
    assert(validChoice(90, pointChoices) == 0);
    assert(validChoice(NAN, pointChoices) == 0);
    assert(validChoice(-32, pointChoices) == 0);
    assert(validChoice(500, millisecondChoices) == 500);
    assert(validChoice(5000, millisecondChoices) == 5000);
    assert(validChoice(2500, millisecondChoices) == 0);
    assert(validChoice(2, millisecondChoices) == 0);
    assert(validChoice(INFINITY, millisecondChoices) == 0);

    assert(seconds(500) == "0.5");
    assert(seconds(1000) == "1");
    assert(seconds(1500) == "1.5");
    assert(seconds(2000) == "2");
    assert(seconds(5000) == "5");

    // Only the real settings menu gets the corner-hold action. Its message is
    // the format loaded at 0x5924 as formatted there; the others are every
    // message that SIFASFeatures' _message() helper (0x5b10) shows under the
    // same "Client settings" title and alert style.
    assert(isSettingsMenu("Build 21.2\nFOV scale 0.7500 to 1.0000\nOrientation: Landscape\nFast intro: Off\n\n"
                          "Hide/Show settings button controls the overlay and is saved after restart. While hidden, "
                          "hold the upper-right corner in game for 2 seconds to open this menu. Server URL: "
                          "Connection. Restore defaults shows the button."));
    for (const char *message : {
             "This build has no verified feature configuration section.",
             "Use two numbers from 0.5 to 2.0, with minimum at most maximum.",
             "This build's server URL capacity could not be verified.",
             "Saved. Restart the game to use the server on this Mac/device.",
             "The packaged server URL will apply after restarting the game.",
             "URL was not saved. This build accepts a valid http(s) URL of at most 21 UTF-16 characters, without "
             "spaces, credentials, query, or fragment. Local GL has a 21-character limit; use the primary GL/JP "
             "build for longer LAN URLs.",
             "Saved. Restart the game to apply the server URL.",
             "Key was not saved. Paste compact RSAKeyValue XML with valid base64 Modulus and Exponent, within this "
             "build's length limit.",
             "Saved. Restart the game to apply the public key.",
             "Simulator regression fixture",  // tests/MVMenuProbe.mm
             ""})
        assert(!isSettingsMenu(message));
    assert(!isSettingsMenu(nullptr));

    // hintPhrase(0, 2000) must equal what SIFASFeatures formats, so it is found.
    assert(hintPhrase(0, originalMilliseconds) == "hold the upper-right corner in game for 2 seconds");
    assert(hintPhrase(0, 1500) == "hold the upper-right corner in game for 1.5 seconds");
    assert(hintPhrase(64, 1000) == "hold the upper-right corner (64 × 64 pt) in game for 1 second");
    assert(hintPhrase(160, 500) == "hold the upper-right corner (160 × 160 pt) in game for 0.5 seconds");
    std::puts("CornerHoldTests passed");
    return 0;
}
