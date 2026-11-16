#include "../NavigationPolicy.hpp"
#include <cassert>
#include <cstring>
int main() {
    using namespace elichika;
    assert(!wideNavigation(390) && !wideNavigation(759) && wideNavigation(760) && wideNavigation(1024));
    assert(!wideNavigation(NAN) && !wideNavigation(INFINITY));
    assert(webSection(Destination::server)==webSection(Destination::appSettings));
    assert(webSection(Destination::server)==webSection(Destination::serverSettings));
    assert(webSection(Destination::assetTools)==webSection(Destination::viewer));
    assert(webSection(Destination::accounts)!=webSection(Destination::content));
    assert(webSection(Destination::gameSettings)==-1);
    assert(webSection(static_cast<Destination>(99))==-1);
    assert(std::strcmp(managementPage(Destination::serverSettings),"server_settings")==0);
    assert(std::strcmp(managementPage(Destination::appSettings),"app_settings")==0);
    assert(!managementPage(Destination::viewer));
    assert(std::strcmp(editorPage(Destination::viewer),"viewer")==0);
    assert(std::strcmp(editorPage(Destination::assetTools),"tools")==0);
    assert(!editorPage(Destination::accounts));
}
