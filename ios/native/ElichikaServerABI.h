#ifndef ELICHIKA_SERVER_ABI_H
#define ELICHIKA_SERVER_ABI_H
#ifdef __cplusplus
extern "C" {
#endif
/* Responses are UTF-8 JSON owned by the Go bridge. Always release with Free.
 * Start returns promptly; ready is true only after real initialization/listen.
 * The writable data_root must already contain the prepared complete payload. */
__attribute__((visibility("default"))) char *ElichikaServerStart(char *optionsJSON);
__attribute__((visibility("default"))) char *ElichikaServerStatus(void);
__attribute__((visibility("default"))) char *ElichikaServerStop(void);
__attribute__((visibility("default"))) char *ElichikaServerCommand(char *commandJSON);
__attribute__((visibility("default"))) void ElichikaServerFree(char *response);
#ifdef __cplusplus
}
#endif
#endif
