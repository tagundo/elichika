#import "ElichikaNativeBridges.h"
#import "ElichikaHost.h"
#import <dispatch/dispatch.h>
#include <limits.h>
#include <string.h>
#include <cmath>

static NSError *ELError(NSString *message) {
    return [NSError errorWithDomain:@"ElichikaNative" code:1 userInfo:@{NSLocalizedDescriptionKey:message}];
}
static BOOL ELWritablePath(NSString *path) {
    return ElichikaHostWritablePath(path);
}

@interface ELHTTPTransaction : NSObject <NSURLSessionDataDelegate>
@property(nonatomic,strong) dispatch_semaphore_t finished;
@property(nonatomic,strong) NSMutableData *body;
@property(nonatomic,strong) NSFileHandle *file;
@property(nonatomic,strong) NSError *error;
@property(nonatomic,strong) NSHTTPURLResponse *response;
@property(nonatomic,assign) unsigned long long maximum;
@property(nonatomic,assign) unsigned long long received;
@property(nonatomic,assign) NSUInteger redirects;
@end
@implementation ELHTTPTransaction
- (instancetype)init {
    if ((self=[super init])) { _finished=dispatch_semaphore_create(0); _body=[NSMutableData new]; }
    return self;
}
- (void)URLSession:(NSURLSession *)session dataTask:(NSURLSessionDataTask *)task
 didReceiveResponse:(NSURLResponse *)response completionHandler:(void (^)(NSURLSessionResponseDisposition))completion {
    (void)session; (void)task;
    if (![response isKindOfClass:NSHTTPURLResponse.class] ||
        (![task.currentRequest.HTTPMethod isEqual:@"HEAD"] && response.expectedContentLength > 0 &&
         (unsigned long long)response.expectedContentLength > _maximum)) {
        _error=ELError(@"The HTTPS response exceeds its size limit."); completion(NSURLSessionResponseCancel); return;
    }
    _response=(NSHTTPURLResponse *)response; completion(NSURLSessionResponseAllow);
}
- (void)URLSession:(NSURLSession *)session dataTask:(NSURLSessionDataTask *)task didReceiveData:(NSData *)data {
    (void)session;
    if (data.length > _maximum-_received) { _error=ELError(@"The HTTPS response exceeds its size limit."); [task cancel]; return; }
    _received+=data.length;
    @try { if (_file) [_file writeData:data]; else [_body appendData:data]; }
    @catch (NSException *exception) { _error=ELError(exception.reason ?: @"Could not write the download."); [task cancel]; }
}
- (void)URLSession:(NSURLSession *)session task:(NSURLSessionTask *)task
 willPerformHTTPRedirection:(NSHTTPURLResponse *)response newRequest:(NSURLRequest *)request
 completionHandler:(void (^)(NSURLRequest *))completion {
    (void)session; (void)task; (void)response;
    if (++_redirects > 5 || ![request.URL.scheme.lowercaseString isEqual:@"https"] || request.URL.user || request.URL.password) {
        _error=ELError(@"An HTTPS redirect was rejected."); completion(nil); return;
    }
    NSMutableURLRequest *redirect=[request mutableCopy];
    if (![task.currentRequest.URL.host.lowercaseString isEqual:request.URL.host.lowercaseString]) {
        [redirect setValue:nil forHTTPHeaderField:@"Authorization"];
        [redirect setValue:nil forHTTPHeaderField:@"Cookie"];
        [redirect setValue:nil forHTTPHeaderField:@"X-Elichika-Local-Access"];
    }
    completion(redirect);
}
- (void)URLSession:(NSURLSession *)session task:(NSURLSessionTask *)task didCompleteWithError:(NSError *)error {
    (void)session; (void)task; if (!_error) _error=error;
    if (_file) {
        @try { [_file synchronizeFile]; [_file closeFile]; }
        @catch (NSException *exception) { if (!_error) _error=ELError(exception.reason ?: @"Could not finish the download."); }
        _file=nil;
    }
    dispatch_semaphore_signal(_finished);
}
@end

static ELHTTPTransaction *ELPerform(NSString *url, NSString *method, NSString *headersJSON, NSData *body,
                                   unsigned long long maximum, double timeout, NSString *destination) {
    ELHTTPTransaction *result=[ELHTTPTransaction new]; result.maximum=maximum;
    NSURL *target=[NSURL URLWithString:url];
    if (![target.scheme.lowercaseString isEqual:@"https"] || !target.host.length || target.user || target.password || target.fragment) {
        result.error=ELError(@"Only HTTPS URLs without embedded credentials are accepted."); return result;
    }
    id headers=[NSJSONSerialization JSONObjectWithData:[headersJSON dataUsingEncoding:NSUTF8StringEncoding] options:0 error:NULL];
    if (![headers isKindOfClass:NSDictionary.class] || ![@[@"GET",@"HEAD",@"POST",@"PUT",@"DELETE",@"PATCH"] containsObject:method]) {
        result.error=ELError(@"Invalid HTTPS method or headers."); return result;
    }
    NSMutableURLRequest *request=[NSMutableURLRequest requestWithURL:target];
    request.HTTPMethod=method; request.HTTPBody=body; request.timeoutInterval=timeout;
    for (id key in headers) {
        id value=headers[key];
        if (![key isKindOfClass:NSString.class] || ![value isKindOfClass:NSString.class] ||
            [key rangeOfCharacterFromSet:NSCharacterSet.controlCharacterSet].location!=NSNotFound ||
            [value rangeOfCharacterFromSet:NSCharacterSet.controlCharacterSet].location!=NSNotFound ||
            [@[@"host",@"content-length",@"connection"] containsObject:[key lowercaseString]]) {
            result.error=ELError(@"Invalid HTTPS header."); return result;
        }
        [request setValue:value forHTTPHeaderField:key];
    }
    if (destination) {
        if (!ELWritablePath(destination)) { result.error=ELError(@"Downloads must stay in app storage."); return result; }
        NSError *error;
        if (![NSFileManager.defaultManager createDirectoryAtPath:destination.stringByDeletingLastPathComponent withIntermediateDirectories:YES attributes:nil error:&error]) {
            result.error=error; return result;
        }
        if (![NSFileManager.defaultManager createFileAtPath:destination contents:nil attributes:@{NSFileProtectionKey:NSFileProtectionCompleteUntilFirstUserAuthentication}]) {
            result.error=ELError(@"Could not create the download."); return result;
        }
        result.file=[NSFileHandle fileHandleForWritingAtPath:destination];
        if (!result.file) { result.error=ELError(@"Could not open the download."); return result; }
    }
    NSURLSessionConfiguration *config=NSURLSessionConfiguration.ephemeralSessionConfiguration;
    config.timeoutIntervalForRequest=timeout; config.timeoutIntervalForResource=timeout;
    config.HTTPShouldSetCookies=NO; config.URLCache=nil;
    NSOperationQueue *queue=[NSOperationQueue new]; queue.maxConcurrentOperationCount=1;
    NSURLSession *session=[NSURLSession sessionWithConfiguration:config delegate:result delegateQueue:queue];
    NSURLSessionDataTask *task=[session dataTaskWithRequest:request]; [task resume];
    if (dispatch_semaphore_wait(result.finished,dispatch_time(DISPATCH_TIME_NOW,(int64_t)((timeout+5)*NSEC_PER_SEC)))!=0) {
        [task cancel]; [session invalidateAndCancel];
        /* Wait for cancellation to finish before returning a path/file to Python. */
        dispatch_semaphore_wait(result.finished,DISPATCH_TIME_FOREVER);
        if (!result.error) result.error=ELError(@"The HTTPS request timed out.");
    } else [session finishTasksAndInvalidate];
    return result;
}
static PyObject *ELResponse(ELHTTPTransaction *result, NSString *path) {
    if (result.error) { PyErr_SetString(PyExc_OSError,result.error.localizedDescription.UTF8String); return NULL; }
    PyObject *headers=PyDict_New();
    if (!headers) return NULL;
    for (id key in result.response.allHeaderFields) {
        PyObject *value=PyUnicode_FromString([result.response.allHeaderFields[key] description].UTF8String);
        if (!value || PyDict_SetItemString(headers,[key description].UTF8String,value)<0) { Py_XDECREF(value); Py_DECREF(headers); return NULL; }
        Py_DECREF(value);
    }
    PyObject *body=PyBytes_FromStringAndSize((const char *)result.body.bytes,(Py_ssize_t)result.body.length);
    if (!body) { Py_DECREF(headers); return NULL; }
    PyObject *reply=Py_BuildValue("{s:i,s:O,s:O,s:K}","status",(int)result.response.statusCode,"headers",headers,"body",body,"received",result.received);
    Py_DECREF(headers); Py_DECREF(body);
    if (reply && path) {
        PyObject *value=PyUnicode_FromString(path.fileSystemRepresentation);
        if (!value || PyDict_SetItemString(reply,"path",value)<0) { Py_XDECREF(value); Py_DECREF(reply); return NULL; }
        Py_DECREF(value);
    }
    return reply;
}
PyObject *ElichikaHTTPSRequest(PyObject *self, PyObject *args, PyObject *kwargs) {
    (void)self; const char *url,*method="GET",*headers="{}"; Py_buffer body={0};
    unsigned long long maximum=16*1024*1024; double timeout=30;
    static char *keys[]={(char *)"url",(char *)"method",(char *)"headers_json",(char *)"body",(char *)"max_bytes",(char *)"timeout",NULL};
    if (!PyArg_ParseTupleAndKeywords(args,kwargs,"s|ssy*Kd:https_request",keys,&url,&method,&headers,&body,&maximum,&timeout)) return NULL;
    if (!maximum || maximum>64ULL*1024*1024 || !std::isfinite(timeout) || timeout<1 || timeout>300 || body.len>16*1024*1024 ||
        strnlen(url,8193)>8192 || strnlen(headers,65537)>65536 || strnlen(method,17)>16) {
        PyBuffer_Release(&body); PyErr_SetString(PyExc_ValueError,"Invalid HTTPS request limits."); return NULL;
    }
    NSData *data=body.buf ? [NSData dataWithBytes:body.buf length:(NSUInteger)body.len] : nil;
    ELHTTPTransaction *result;
    Py_BEGIN_ALLOW_THREADS
    result=ELPerform([NSString stringWithUTF8String:url],[NSString stringWithUTF8String:method],[NSString stringWithUTF8String:headers],data,maximum,timeout,nil);
    Py_END_ALLOW_THREADS
    PyBuffer_Release(&body); return ELResponse(result,nil);
}
PyObject *ElichikaHTTPSDownload(PyObject *self, PyObject *args, PyObject *kwargs) {
    (void)self; const char *url,*path,*headers="{}"; unsigned long long maximum=4ULL*1024*1024*1024; double timeout=300;
    static char *keys[]={(char *)"url",(char *)"path",(char *)"headers_json",(char *)"max_bytes",(char *)"timeout",NULL};
    if (!PyArg_ParseTupleAndKeywords(args,kwargs,"ss|sKd:https_download",keys,&url,&path,&headers,&maximum,&timeout)) return NULL;
    if (!maximum || maximum>4ULL*1024*1024*1024 || !std::isfinite(timeout) || timeout<1 || timeout>1800 ||
        strnlen(url,8193)>8192 || strnlen(path,PATH_MAX+1)>PATH_MAX || strnlen(headers,65537)>65536) {
        PyErr_SetString(PyExc_ValueError,"Invalid download limits."); return NULL;
    }
    NSString *destination=[NSString stringWithUTF8String:path];
    NSString *temporary=[destination stringByAppendingFormat:@".%@.download",NSUUID.UUID.UUIDString];
    ELHTTPTransaction *result; NSError *moveError=nil;
    Py_BEGIN_ALLOW_THREADS
    result=ELPerform([NSString stringWithUTF8String:url],@"GET",[NSString stringWithUTF8String:headers],nil,maximum,timeout,temporary);
    if (!result.error && result.response.statusCode>=200 && result.response.statusCode<300) {
        if ([NSFileManager.defaultManager fileExistsAtPath:destination]) {
            if (![NSFileManager.defaultManager replaceItemAtURL:[NSURL fileURLWithPath:destination] withItemAtURL:[NSURL fileURLWithPath:temporary] backupItemName:nil options:0 resultingItemURL:NULL error:&moveError]) result.error=moveError;
        } else if (![NSFileManager.defaultManager moveItemAtPath:temporary toPath:destination error:&moveError]) result.error=moveError;
    } else if (!result.error) result.error=ELError([NSString stringWithFormat:@"HTTPS download returned %ld.",(long)result.response.statusCode]);
    [NSFileManager.defaultManager removeItemAtPath:temporary error:NULL];
    Py_END_ALLOW_THREADS
    return ELResponse(result,destination);
}
PyObject *ElichikaPickDocument(PyObject *self, PyObject *args) {
    (void)self; PyObject *types=NULL;
    if (!PyArg_ParseTuple(args,"|O:pick_document",&types)) return NULL;
    NSMutableArray *identifiers=[NSMutableArray new];
    if (types && types!=Py_None) {
        PyObject *sequence=PySequence_Fast(types,"Document types must be a sequence of identifiers."); if (!sequence) return NULL;
        for (Py_ssize_t i=0;i<PySequence_Fast_GET_SIZE(sequence);++i) {
            const char *value=PyUnicode_AsUTF8(PySequence_Fast_GET_ITEM(sequence,i));
            if (!value) { Py_DECREF(sequence); return NULL; }
            [identifiers addObject:[NSString stringWithUTF8String:value]];
        }
        Py_DECREF(sequence);
    }
    NSError *error=nil; NSString *path;
    Py_BEGIN_ALLOW_THREADS
    path=ElichikaHostImportDocument(identifiers,&error);
    Py_END_ALLOW_THREADS
    if (!path) { PyErr_SetString(PyExc_OSError,(error.localizedDescription ?: @"Document selection cancelled.").UTF8String); return NULL; }
    return PyUnicode_FromString(path.fileSystemRepresentation);
}
PyObject *ElichikaExportDocument(PyObject *self, PyObject *args) {
    (void)self; const char *raw; if (!PyArg_ParseTuple(args,"s:export_document",&raw)) return NULL;
    NSString *path=[NSString stringWithUTF8String:raw];
    if (!ELWritablePath(path)) { PyErr_SetString(PyExc_ValueError,"Only app-owned files can be exported."); return NULL; }
    NSError *error=nil; BOOL good;
    Py_BEGIN_ALLOW_THREADS
    good=ElichikaHostExportDocument(path,&error);
    Py_END_ALLOW_THREADS
    if (!good && error && !(error.code==2 && [error.domain isEqual:@"ElichikaDocument"])) { PyErr_SetString(PyExc_OSError,error.localizedDescription.UTF8String); return NULL; }
    return PyBool_FromLong(good);
}
