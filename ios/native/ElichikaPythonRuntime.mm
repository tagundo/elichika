#import "ElichikaPythonRuntime.h"
#import "ElichikaHost.h"
#import "ElichikaNativeBridges.h"
#import <dispatch/dispatch.h>
#include "ElichikaServerABI.h"
#include <Python.h>
#include <atomic>
#include <cstring>

static const NSUInteger ELJSONLimit = 1024 * 1024;
static PyObject *ELRuntimeModule;
static PyThreadState *ELPythonState;
static std::atomic<bool> ELInterpreterOwned{false};

@interface ELRuntimeWorker : NSObject
@property(nonatomic,strong) NSCondition *condition;
@property(nonatomic,strong) NSMutableArray *tasks;
@property(nonatomic,strong) NSThread *thread;
- (void)enqueue:(void (^)(void))task;
@end
@implementation ELRuntimeWorker
- (instancetype)init {
    if ((self = [super init])) {
        _condition = [NSCondition new]; _tasks = [NSMutableArray new];
        _thread = [[NSThread alloc] initWithTarget:self selector:@selector(run) object:nil];
        _thread.name = @"elichika-python-control"; [_thread start];
    }
    return self;
}
- (void)enqueue:(void (^)(void))task {
    [_condition lock]; [_tasks addObject:[task copy]]; [_condition signal]; [_condition unlock];
}
- (void)run {
    for (;;) { @autoreleasepool {
        [_condition lock]; while (!_tasks.count) [_condition wait];
        void (^task)(void) = _tasks.firstObject; [_tasks removeObjectAtIndex:0]; [_condition unlock];
        task();
    }}
}
@end
static ELRuntimeWorker *ELWorker(void) {
    static ELRuntimeWorker *worker; static dispatch_once_t once;
    dispatch_once(&once, ^{ worker = [ELRuntimeWorker new]; }); return worker;
}
static NSDictionary *ELFailure(NSString *message) {
    return @{@"ready":@NO,@"phase":@"error",@"error":message ?: @"The embedded runtime failed."};
}
static NSString *ELPythonError(void) {
    PyObject *type = NULL, *value = NULL, *trace = NULL;
    PyErr_Fetch(&type, &value, &trace); PyErr_NormalizeException(&type, &value, &trace);
    PyObject *text = value ? PyObject_Str(value) : NULL;
    const char *bytes = text ? PyUnicode_AsUTF8(text) : NULL;
    NSString *message = bytes ? [NSString stringWithUTF8String:bytes] : @"Python initialization failed.";
    Py_XDECREF(text); Py_XDECREF(type); Py_XDECREF(value); Py_XDECREF(trace); PyErr_Clear();
    return message.length <= 2048 ? message : [message substringToIndex:2048];
}
static PyObject *ELCopyGoReply(char *response) {
    if (!response) { PyErr_SetString(PyExc_RuntimeError, "The Go bridge returned no result."); return NULL; }
    size_t length = strnlen(response, ELJSONLimit + 1);
    PyObject *result = length <= ELJSONLimit ? PyUnicode_DecodeUTF8(response, (Py_ssize_t)length, "strict") : NULL;
    ElichikaServerFree(response);
    if (length > ELJSONLimit) PyErr_SetString(PyExc_ValueError, "The Go bridge result exceeds 1 MiB.");
    return result;
}
static PyObject *ELGoStart(PyObject *self, PyObject *argument) {
    (void)self; Py_ssize_t length = 0;
    const char *json = PyUnicode_AsUTF8AndSize(argument, &length);
    if (!json) return NULL;
    if (length < 2 || length > (Py_ssize_t)ELJSONLimit || memchr(json, 0, (size_t)length)) {
        PyErr_SetString(PyExc_ValueError, "Go options must be bounded JSON without NUL bytes."); return NULL;
    }
    char *response;
    Py_BEGIN_ALLOW_THREADS
    response = ElichikaServerStart(const_cast<char *>(json));
    Py_END_ALLOW_THREADS
    return ELCopyGoReply(response);
}
static PyObject *ELGoStatus(PyObject *self, PyObject *args) {
    (void)self; (void)args; char *response;
    Py_BEGIN_ALLOW_THREADS
    response = ElichikaServerStatus();
    Py_END_ALLOW_THREADS
    return ELCopyGoReply(response);
}
static PyObject *ELGoStop(PyObject *self, PyObject *args) {
    (void)self; (void)args; char *response;
    Py_BEGIN_ALLOW_THREADS
    response = ElichikaServerStop();
    Py_END_ALLOW_THREADS
    return ELCopyGoReply(response);
}
static PyObject *ELGoCommand(PyObject *self, PyObject *argument) {
    (void)self; Py_ssize_t length=0;
    const char *json=PyUnicode_AsUTF8AndSize(argument,&length);
    if (!json) return NULL;
    if (length<2 || length>(Py_ssize_t)ELJSONLimit || memchr(json,0,(size_t)length)) {
        PyErr_SetString(PyExc_ValueError,"Go commands must be bounded JSON without NUL bytes."); return NULL;
    }
    char *response;
    Py_BEGIN_ALLOW_THREADS
    response=ElichikaServerCommand(const_cast<char *>(json));
    Py_END_ALLOW_THREADS
    return ELCopyGoReply(response);
}
static PyObject *ELPostEvent(PyObject *self, PyObject *argument) {
    (void)self; Py_ssize_t size = 0; const char *raw = PyUnicode_AsUTF8AndSize(argument, &size);
    if (!raw) return NULL;
    if (size < 2 || size > 65536) { PyErr_SetString(PyExc_ValueError, "Progress JSON exceeds 64 KiB."); return NULL; }
    ElichikaHostReportEvent([[NSString alloc] initWithBytes:raw length:(NSUInteger)size encoding:NSUTF8StringEncoding]);
    Py_RETURN_NONE;
}
static PyMethodDef ELMethods[] = {
    {"go_start", ELGoStart, METH_O, "Start the real Go backend asynchronously; return status JSON."},
    {"go_status", ELGoStatus, METH_NOARGS, "Read real Go readiness JSON."},
    {"go_stop", ELGoStop, METH_NOARGS, "Drain the embedded Go backend; return status JSON."},
    {"go_command", ELGoCommand, METH_O, "Execute an embedded server management command; return JSON."},
    {"report_event", ELPostEvent, METH_O, "Publish bounded startup progress to native UI."},
    {"https_request", (PyCFunction)(void (*)(void))ElichikaHTTPSRequest, METH_VARARGS|METH_KEYWORDS, "OS-trusted bounded HTTPS request."},
    {"https_download", (PyCFunction)(void (*)(void))ElichikaHTTPSDownload, METH_VARARGS|METH_KEYWORDS, "Stream OS-trusted HTTPS into app-private storage."},
    {"pick_document", ElichikaPickDocument, METH_VARARGS, "Import a user-selected document into app storage."},
    {"export_document", ElichikaExportDocument, METH_VARARGS, "Export an app-owned file through the document picker."},
    {NULL,NULL,0,NULL}
};
static PyModuleDef ELModule = {PyModuleDef_HEAD_INIT,"_elichika_ios",NULL,-1,ELMethods,NULL,NULL,NULL,NULL};
PyMODINIT_FUNC PyInit__elichika_ios(void) { return PyModule_Create(&ELModule); }

static BOOL ELConfigString(PyConfig *config, wchar_t **field, NSString *value, NSString **error) {
    PyStatus status = PyConfig_SetBytesString(config, field, value.fileSystemRepresentation);
    if (PyStatus_Exception(status)) { *error = @"Could not configure the embedded Python paths."; return NO; }
    return YES;
}
static BOOL ELInitialize(NSDictionary *configuration, NSString **error) {
    NSCAssert(NSThread.currentThread == ELWorker().thread, @"Python is owned by its worker thread.");
    if (ELInterpreterOwned) { PyEval_RestoreThread(ELPythonState); ELPythonState = NULL; return YES; }
    if (Py_IsInitialized()) { *error = @"Another Python interpreter is already initialized."; return NO; }
    if (PyImport_AppendInittab("_elichika_ios", PyInit__elichika_ios) != 0) {
        *error = @"Could not register the iOS runtime bridge."; return NO;
    }
    NSString *home = configuration[@"python_home"], *app = configuration[@"python_app_root"];
    if (![home isKindOfClass:NSString.class] || ![app isKindOfClass:NSString.class]) {
        *error = @"The packaged Python resource paths are missing."; return NO;
    }
    PyConfig config; PyConfig_InitIsolatedConfig(&config);
    config.install_signal_handlers = 0; config.use_environment = 0;
    config.site_import = 0; config.user_site_directory = 0; config.write_bytecode = 0;
    config.parse_argv = 0; config.safe_path = 1; config.module_search_paths_set = 1;
    BOOL good = ELConfigString(&config, &config.program_name, @"ElichikaEmbedded", error)
        && ELConfigString(&config, &config.executable, NSBundle.mainBundle.executablePath, error)
        && ELConfigString(&config, &config.home, home, error);
    NSArray *paths = @[app,[home stringByAppendingPathComponent:@"lib/python313.zip"],
                       [home stringByAppendingPathComponent:@"lib/python3.13"],
                       [home stringByAppendingPathComponent:@"lib/python3.13/lib-dynload"],
                       [home stringByAppendingPathComponent:@"lib/python3.13/site-packages"]];
    if (good) for (NSString *path in paths) {
        wchar_t *wide = Py_DecodeLocale(path.fileSystemRepresentation, NULL);
        if (!wide) { good = NO; break; }
        PyStatus status = PyWideStringList_Append(&config.module_search_paths, wide); PyMem_RawFree(wide);
        if (PyStatus_Exception(status)) { good = NO; break; }
    }
    if (!good) { PyConfig_Clear(&config); if (!*error) *error = @"Could not prepare Python module paths."; return NO; }
    PyStatus status = Py_InitializeFromConfig(&config); PyConfig_Clear(&config);
    if (PyStatus_Exception(status)) {
        *error = status.err_msg ? [NSString stringWithUTF8String:status.err_msg] : @"Python could not initialize.";
        return NO;
    }
    ELInterpreterOwned = YES; return YES; // caller owns GIL until SaveThread
}
static NSDictionary *ELReadReply(PyObject *result) {
    if (!result) return ELFailure(ELPythonError());
    PyObject *text = result;
    if (!PyUnicode_Check(text)) {
        PyObject *json = PyImport_ImportModule("json");
        text = json ? PyObject_CallMethod(json,"dumps","O",result) : NULL;
        Py_XDECREF(json); Py_DECREF(result);
        if (!text) return ELFailure(ELPythonError());
    }
    Py_ssize_t length = 0; const char *raw = PyUnicode_AsUTF8AndSize(text,&length);
    NSData *data = raw && length > 0 && length <= (Py_ssize_t)ELJSONLimit
        ? [NSData dataWithBytes:raw length:(NSUInteger)length] : nil;
    Py_DECREF(text);
    id reply = data ? [NSJSONSerialization JSONObjectWithData:data options:0 error:NULL] : nil;
    if (!reply || ![reply isKindOfClass:NSDictionary.class]) {
        PyErr_Clear(); return ELFailure(@"The embedded runtime returned invalid status JSON.");
    }
    return reply;
}
static void ELInvoke(NSString *method, NSDictionary *configuration, ElichikaRuntimeReply completion) {
    [ELWorker() enqueue:^{
        NSString *error = nil;
        if (!ELInterpreterOwned && !configuration) {
            dispatch_async(dispatch_get_main_queue(), ^{ completion(ELFailure(@"Python has not started.")); }); return;
        }
        NSDictionary *config = configuration ?: ElichikaHostConfiguration();
        if (!ELInitialize(config, &error)) {
            dispatch_async(dispatch_get_main_queue(), ^{ completion(ELFailure(error)); }); return;
        }
        if (!ELRuntimeModule) ELRuntimeModule = PyImport_ImportModule("elichika_ios_runtime");
        NSDictionary *reply;
        if (!ELRuntimeModule) reply = ELFailure(ELPythonError());
        else {
            PyObject *result = NULL;
            if (configuration) {
                NSData *json = [NSJSONSerialization dataWithJSONObject:configuration options:0 error:NULL];
                NSString *text = json ? [[NSString alloc] initWithData:json encoding:NSUTF8StringEncoding] : nil;
                result = text ? PyObject_CallMethod(ELRuntimeModule,method.UTF8String,"s",text.UTF8String) : NULL;
            } else result = PyObject_CallMethod(ELRuntimeModule,method.UTF8String,NULL);
            reply = ELReadReply(result);
        }
        ELPythonState = PyEval_SaveThread();
        dispatch_async(dispatch_get_main_queue(), ^{ completion(reply); });
    }];
}
void ElichikaPythonStart(NSDictionary *configuration, ElichikaRuntimeReply completion) { ELInvoke(@"start",configuration,completion); }
void ElichikaPythonCall(NSString *method, ElichikaRuntimeReply completion) { ELInvoke(method,nil,completion); }
void ElichikaPythonLifecycle(NSString *event) {
    if (!ELInterpreterOwned) return;
    [ELWorker() enqueue:^{
        PyEval_RestoreThread(ELPythonState); ELPythonState = NULL;
        if (ELRuntimeModule) {
            PyObject *callback = PyObject_GetAttrString(ELRuntimeModule,"lifecycle");
            if (callback && PyCallable_Check(callback)) {
                PyObject *reply = PyObject_CallFunction(callback,"s",event.UTF8String); Py_XDECREF(reply);
            }
            Py_XDECREF(callback); if (PyErr_Occurred()) { NSLog(@"Elichika lifecycle: %@",ELPythonError()); }
        }
        ELPythonState = PyEval_SaveThread();
    }];
}
