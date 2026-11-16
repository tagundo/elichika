/* External diagnostic only: never package this executable in a client. */
#include <Python.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static FILE *stages;
static const char *current_stage = "entry";
static void stage(const char *value) {
    current_stage = value;
    if (stages) { fprintf(stages, "%s\n", value); fflush(stages); }
}
static void checked(PyStatus status) {
    if (PyStatus_Exception(status)) {
        const char *message = status.err_msg ? status.err_msg : "no PyStatus message";
        fprintf(stderr, "Python setup failure at %s: %.8192s\n", current_stage, message);
        fflush(stderr);
        if (stages) { fprintf(stages, "PyStatus_EXCEPTION at %s: %.8192s\n", current_stage, message); fflush(stages); }
        Py_ExitStatusException(status);
    }
}
static void path(PyConfig *config, const char *value) {
    wchar_t *wide = Py_DecodeLocale(value, NULL);
    if (!wide) { fputs("Could not decode diagnostic Python path\n", stderr); exit(2); }
    checked(PyWideStringList_Append(&config->module_search_paths, wide));
    PyMem_RawFree(wide);
}
static void python_error(const char *where) {
    PyObject *type = NULL, *value = NULL, *traceback = NULL;
    PyErr_Fetch(&type, &value, &traceback);
    PyErr_NormalizeException(&type, &value, &traceback);
    PyObject *text = value ? PyObject_Str(value) : NULL;
    const char *message = text ? PyUnicode_AsUTF8(text) : NULL;
    if (!message) { PyErr_Clear(); message = "Python exception without UTF-8 message"; }
    fprintf(stderr, "Python failure at %s: %.8192s\n", where, message); fflush(stderr);
    if (stages) { fprintf(stages, "PYTHON_EXCEPTION at %s: %.8192s\n", where, message); fflush(stages); }
    Py_XDECREF(text);
    PyErr_Restore(type, value, traceback);
    PyErr_Print();
}
int main(int argc, char **argv) {
    if (argc != 5) return 2;
    const char *app = argv[1], *script = argv[2];
    char buffer[8192];
    if (snprintf(buffer, sizeof(buffer), "%s.c-stages.txt", argv[4]) >= (int)sizeof(buffer)) return 2;
    stages = fopen(buffer, "wx");
    if (!stages) { perror("Create C stage evidence"); return 2; }
    stage("entry");
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
    stage("configure_program_and_home");
    checked(PyConfig_SetBytesString(&config, &config.program_name, "ElichikaPlayCoverNativeProbe"));
    if (snprintf(buffer, sizeof(buffer), "%s/global", app) >= (int)sizeof(buffer)) return 2;
    checked(PyConfig_SetBytesString(&config, &config.executable, buffer));
    if (snprintf(buffer, sizeof(buffer), "%s/ElichikaResources/python", app) >= (int)sizeof(buffer)) return 2;
    checked(PyConfig_SetBytesString(&config, &config.home, buffer));
    const char *suffixes[] = {"ElichikaResources/python-app", "ElichikaResources/python/lib/python313.zip",
        "ElichikaResources/python/lib/python3.13", "ElichikaResources/python/lib/python3.13/lib-dynload",
        "ElichikaResources/python/lib/python3.13/site-packages"};
    stage("configure_module_search_paths");
    for (unsigned i = 0; i < sizeof(suffixes)/sizeof(suffixes[0]); i++) {
        if (snprintf(buffer, sizeof(buffer), "%s/%s", app, suffixes[i]) >= (int)sizeof(buffer)) return 2;
        path(&config, buffer);
    }
    char *python_argv[] = {argv[0], argv[1], argv[3], argv[4]};
    checked(PyConfig_SetBytesArgv(&config, 4, python_argv));
    stage("before_Py_InitializeFromConfig");
    checked(Py_InitializeFromConfig(&config));
    stage("after_Py_InitializeFromConfig");
    PyConfig_Clear(&config);
    PyObject *main_module = PyImport_AddModule("__main__");
    PyObject *globals = main_module ? PyModule_GetDict(main_module) : NULL;
    if (!globals) { python_error("main_module"); return 1; }
    stage("before_fd_backed_Python_streams");
    PyObject *redirected = PyRun_StringFlags(
        "import _io, sys\n"
        "sys.stdout = _io.open(1, 'w', encoding='utf-8', buffering=1, closefd=False)\n"
        "sys.stderr = _io.open(2, 'w', encoding='utf-8', buffering=1, closefd=False)\n",
        Py_file_input, globals, globals, NULL);
    if (!redirected) { python_error("fd_backed_Python_streams"); return 1; }
    Py_DECREF(redirected);
    stage("after_fd_backed_Python_streams");
    FILE *input = fopen(script, "rb");
    if (!input) { perror("Open diagnostic script"); return 2; }
    stage("before_probe_script");
    PyObject *reply = PyRun_FileExFlags(input, script, Py_file_input, globals, globals, 1, NULL);
    int status = reply ? 0 : 1;
    if (!reply) python_error("probe_script");
    Py_XDECREF(reply);
    if (stages) { fprintf(stages, "probe_script_return=%d\n", status); fflush(stages); }
    stage("before_Py_FinalizeEx");
    if (Py_FinalizeEx() < 0 && status == 0) status = 120;
    if (stages) { fprintf(stages, "final_return=%d\n", status); fclose(stages); }
    return status == 0 ? 0 : 1;
}
