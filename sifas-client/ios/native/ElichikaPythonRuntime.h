#import <Foundation/Foundation.h>
NS_ASSUME_NONNULL_BEGIN
typedef void (^ElichikaRuntimeReply)(NSDictionary *reply);
void ElichikaPythonStart(NSDictionary *configuration, ElichikaRuntimeReply completion);
void ElichikaPythonCall(NSString *method, ElichikaRuntimeReply completion);
void ElichikaPythonCallWithArguments(NSString *method, NSDictionary *arguments, ElichikaRuntimeReply completion);
void ElichikaPythonLifecycle(NSString *event);
NS_ASSUME_NONNULL_END
