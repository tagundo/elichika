/* External diagnostic only: never package this executable in a client. */
#include <Python.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void checked(PyStatus status) {
    if (PyStatus_Exception(status)) Py_ExitStatusException(status);
}
static void path(PyConfig *config, const char *value) {
    wchar_t *wide = Py_DecodeLocale(value, NULL);
    if (!wide) { fputs("Could not decode diagnostic Python path\n", stderr); exit(2); }
    checked(PyWideStringList_Append(&config->module_search_paths, wide));
    PyMem_RawFree(wide);
}
int main(int argc, char **argv) {
    if (argc != 5) return 2;
    const char *app = argv[1], *script = argv[2];
    char buffer[8192];
    PyConfig config;
    PyConfig_InitIsolatedConfig(&config);
    config.install_signal_handlers = 0;
    config.use_environment = 0;
    config.site_import = 0;
    config.user_site_directory = 0;
    config.write_bytecode = 0;
    config.parse_argv = 0;
    config.safe_path = 1;
    config.module_search_paths_set = 1;
    checked(PyConfig_SetBytesString(&config, &config.program_name, "ElichikaPlayCoverNativeProbe"));
    if (snprintf(buffer, sizeof(buffer), "%s/global", app) >= (int)sizeof(buffer)) return 2;
    checked(PyConfig_SetBytesString(&config, &config.executable, buffer));
    if (snprintf(buffer, sizeof(buffer), "%s/ElichikaResources/python", app) >= (int)sizeof(buffer)) return 2;
    checked(PyConfig_SetBytesString(&config, &config.home, buffer));
    const char *suffixes[] = {"ElichikaResources/python-app", "ElichikaResources/python/lib/python313.zip",
        "ElichikaResources/python/lib/python3.13", "ElichikaResources/python/lib/python3.13/lib-dynload",
        "ElichikaResources/python/lib/python3.13/site-packages"};
    for (unsigned i = 0; i < sizeof(suffixes)/sizeof(suffixes[0]); i++) {
        if (snprintf(buffer, sizeof(buffer), "%s/%s", app, suffixes[i]) >= (int)sizeof(buffer)) return 2;
        path(&config, buffer);
    }
    char *python_argv[] = {argv[0], argv[1], argv[3], argv[4]};
    checked(PyConfig_SetBytesArgv(&config, 4, python_argv));
    checked(Py_InitializeFromConfig(&config));
    PyConfig_Clear(&config);
    FILE *input = fopen(script, "rb");
    if (!input) { perror("Open diagnostic script"); return 2; }
    int status = PyRun_SimpleFileEx(input, script, 1);
    if (Py_FinalizeEx() < 0 && status == 0) status = 120;
    return status == 0 ? 0 : 1;
}
