#pragma once
#include <cmath>

namespace elichika {
// Destinations share four retained documents. Switching within management or
// between the asset editor and viewer never replaces their WebKit document.
enum class Destination : int {
    server, accounts, serverSettings, content, assetTools, viewer,
    appSettings, gameSettings, downloads, help, count
};
inline int webSection(Destination destination) {
    switch (destination) {
        case Destination::server: case Destination::serverSettings:
        case Destination::appSettings: case Destination::downloads: case Destination::help: return 0;
        case Destination::accounts: return 1;
        case Destination::content: return 2;
        case Destination::assetTools: case Destination::viewer: return 3;
        default: return -1;
    }
}
inline const char *managementPage(Destination destination) {
    switch (destination) {
        case Destination::server: return "server";
        case Destination::serverSettings: return "server_settings";
        case Destination::appSettings: return "app_settings";
        case Destination::downloads: return "downloads";
        case Destination::help: return "help";
        default: return nullptr;
    }
}
inline const char *editorPage(Destination destination) {
    switch (destination) {
        case Destination::assetTools: return "tools";
        case Destination::viewer: return "viewer";
        default: return nullptr;
    }
}
inline bool wideNavigation(double width) { return std::isfinite(width) && width>=760; }
}
