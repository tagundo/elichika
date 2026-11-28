#include "../ElichikaHost.h"
#include "../HostCore.hpp"
#include <cassert>
#include <string_view>
int main() {
    using namespace elichika;
    for (auto value : {"auto","en","ko","ja"}) assert(nativeLanguageAllowed(value));
    for (auto value : {"","EN","fr","en-US","ko\n"}) assert(!nativeLanguageAllowed(value));
    assert(!nativeLanguageAllowed(std::string_view("en\0other",8)));
    assert(nativeListenAllowed("127.0.0.1:8080") && nativeListenAllowed("0.0.0.0:8080"));
    for (auto value : {"", "localhost:8080", "127.0.0.1:8772", "0.0.0.0:80", "192.168.1.2:8080", "[::]:8080", "http://127.0.0.1:8080", "0.0.0.0:8080\n"})
        assert(!nativeListenAllowed(value));
    assert(!nativeListenAllowed(std::string_view("127.0.0.1:8080\0x",16)));
    assert(!managementAvailable(false,false,true));
    assert(!managementAvailable(true,true,false));
    assert(managementAvailable(false,true,true));
    HostCore core;
    auto generation=core.begin();
    assert(core.capture(1)); core.report(generation,true,"");
    assert(core.takeStart());
    core.report(generation,false,"");
    assert(core.started() && !core.ready());
    assert(managementAvailable(core.started(),core.ready(),true));
    assert(!core.takeStart());
    core.report(generation,true,"");
    assert(!core.takeStart()); // Stop/start management can never start Unity twice.
}
