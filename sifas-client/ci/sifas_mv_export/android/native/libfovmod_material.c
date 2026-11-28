/* Writable configuration for the offline-patched ARM64 game library.
 * No process-memory files, executable allocation, runtime code writes, or
 * protection changes are used. The game runs with its original defaults until
 * nativeConfigure receives valid private application preferences.
 */
#define _GNU_SOURCE
#include <android/log.h>
#include <jni.h>
#include <link.h>
#include <math.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

typedef struct {
    char magic[8];
    uint32_t version, size;
    uint64_t bounds_bits; /* adjacent IEEE754 min/max, loaded as one atomic word */
    uint32_t splash, generation;
} Config;
_Static_assert(sizeof(Config) == 32, "configuration ABI");
static pthread_mutex_t guard = PTHREAD_MUTEX_INITIALIZER;
static Config *game_config;
static float pending_min = .75f, pending_max = 1.f;
static uint32_t pending_splash, generation;
static uint64_t export_bounds, export_token, next_export_token;
static int worker_running;
static char status_path[1024];

/* New data-only material binder. Existing FOV Config remains exactly32B. */
extern int mi_android_runtime_try_bind_loaded(void);
extern int amv_game_try_bind_loaded(void);
static int material_bind_result;
static const char *material_bind_status(void) {
    switch (material_bind_result) {
    case 1: case 2: return "bound";
    case 0: return "waiting for the game";
    case -1: return "invalid material runtime callbacks";
    case -2: return "unsupported material hook image or preimage";
    case -3: return "material runtime preparation failed";
    default: return "unexpected material binder result";
    }
}

static void status_locked(int result, const char *message) {
    __android_log_print(result < 0 ? ANDROID_LOG_ERROR : ANDROID_LOG_INFO,
                        "SIFAS-FoV", "%s (%d)", message, result);
    if (!status_path[0]) return;
    char temporary[sizeof(status_path) + 16];
    snprintf(temporary, sizeof(temporary), "%s.native-tmp", status_path);
    FILE *out = fopen(temporary, "w");
    if (!out) return;
    fprintf(out, "Feature configuration: %s (%d)\nBounds: %.6g .. %.6g\nFast intro: %s\n",
            message, result, pending_min, pending_max, pending_splash ? "on" : "off");
    fprintf(out, "Material isolation: %s (%d)\n", material_bind_status(), material_bind_result);
    if (fclose(out) || rename(temporary, status_path)) unlink(temporary);
}

static int find_config(struct dl_phdr_info *info, size_t size, void *userdata) {
    (void)size;
    int *found_library = userdata;
    const char *base = strrchr(info->dlpi_name, '/');
    base = base ? base + 1 : info->dlpi_name;
    if (strcmp(base, "libil2cpp.so")) return 0;
    *found_library = 1;
    for (ElfW(Half) i = 0; i < info->dlpi_phnum; ++i) {
        const ElfW(Phdr) *ph = &info->dlpi_phdr[i];
        if (ph->p_type != PT_LOAD || ph->p_flags != (PF_R | PF_W) ||
            ph->p_filesz != sizeof(Config) || ph->p_memsz != sizeof(Config)) continue;
        Config *config = (Config *)(info->dlpi_addr + ph->p_vaddr);
        if (memcmp(config->magic, "SFOVRW22", 8) || config->version != 1 || config->size != sizeof(Config)) continue;
        game_config = config;
        return 1;
    }
    return 1;
}

static uint64_t bounds_pair(float min, float max) {
    float values[2] = {min, max};
    uint64_t pair;
    memcpy(&pair, values, sizeof(pair));
    return pair;
}

static int valid_bounds(uint64_t pair) {
    float values[2];
    memcpy(values, &pair, sizeof(values));
    return isfinite(values[0]) && isfinite(values[1]) &&
           values[0] >= .5f && values[0] <= values[1] && values[1] <= 2.f;
}

/* Caller holds guard. Returns 0 while the engine has not mapped its image. */
static int apply_locked(void) {
    if (!game_config) {
        int found_library = 0;
        dl_iterate_phdr(find_config, &found_library);
        if (!game_config) return found_library ? -2 : 0;
    }
    /* apply_locked is reached from the existing settings/loader waiter.
     * This call only binds addresses/RW data; it never invokes Unity here. */
    int material_result = mi_android_runtime_try_bind_loaded();
    /* Data-only MV sidecar publication. All Unity calls remain deferred to
     * the exact original Unity-thread callbacks in the MV adapter. */
    (void)amv_game_try_bind_loaded();
    if (material_result != material_bind_result) {
        material_bind_result = material_result;
        __android_log_print(material_result < 0 ? ANDROID_LOG_ERROR : ANDROID_LOG_INFO,
                            "SIFAS-Material", "%s (%d)", material_bind_status(), material_result);
    }
    uint64_t pair = export_token ? export_bounds : bounds_pair(pending_min, pending_max);
    __atomic_store_n(&game_config->bounds_bits, pair, __ATOMIC_RELEASE);
    __atomic_store_n(&game_config->splash, pending_splash, __ATOMIC_RELEASE);
    __atomic_store_n(&game_config->generation, generation, __ATOMIC_RELEASE);
    return 1;
}

static void *wait_for_game(void *unused) {
    (void)unused;
    int result = 0;
    /* Bounded to five minutes; the settings page can be left open indefinitely.
     * A later lifecycle/configuration call can start another bounded waiter. */
    for (unsigned i = 0; i < 60000; ++i) {
        pthread_mutex_lock(&guard);
        result = apply_locked();
        if (result) {
            status_locked(result, result > 0 ? "applied" : "unsupported game image");
            worker_running = 0;
            pthread_mutex_unlock(&guard);
            return NULL;
        }
        pthread_mutex_unlock(&guard);
        struct timespec delay = {0, 5000000};
        nanosleep(&delay, NULL);
    }
    pthread_mutex_lock(&guard);
    worker_running = 0;
    result = apply_locked();
    status_locked(result ? result : -4, result > 0 ? "applied" : result < 0 ? "unsupported game image" :
                  "timed out waiting for the game; reopen settings and launch again");
    pthread_mutex_unlock(&guard);
    return NULL;
}

JNIEXPORT jint JNICALL JNI_OnLoad(JavaVM *vm, void *reserved) {
    (void)vm; (void)reserved;
    return JNI_VERSION_1_6;
}

JNIEXPORT jlong JNICALL Java_com_klab_lovelive_allstars_fovmod_FovMod_nativeCaptureExportFov(
        JNIEnv *env, jclass type) {
    (void)env;
    (void)type;
    pthread_mutex_lock(&guard);
    uint64_t bounds = game_config ? __atomic_load_n(&game_config->bounds_bits, __ATOMIC_ACQUIRE) : 0;
    pthread_mutex_unlock(&guard);
    return valid_bounds(bounds) ? (jlong)bounds : 0;
}

JNIEXPORT jlong JNICALL Java_com_klab_lovelive_allstars_fovmod_FovMod_nativeApplyExportFov(
        JNIEnv *env, jclass type, jlong bounds) {
    (void)env;
    (void)type;
    if (!valid_bounds((uint64_t)bounds)) return 0;
    pthread_mutex_lock(&guard);
    uint64_t token = 0;
    if (game_config && !export_token && next_export_token < INT64_MAX &&
        valid_bounds(__atomic_load_n(&game_config->bounds_bits, __ATOMIC_ACQUIRE))) {
        export_bounds = (uint64_t)bounds;
        token = ++next_export_token;
        export_token = token;
        __atomic_store_n(&game_config->bounds_bits, export_bounds, __ATOMIC_RELEASE);
    }
    pthread_mutex_unlock(&guard);
    return (jlong)token;
}

JNIEXPORT jboolean JNICALL Java_com_klab_lovelive_allstars_fovmod_FovMod_nativeRestoreExportFov(
        JNIEnv *env, jclass type, jlong token) {
    (void)env;
    (void)type;
    pthread_mutex_lock(&guard);
    const int owns_override = game_config && token > 0 && export_token == (uint64_t)token;
    if (owns_override) {
        export_token = 0;
        export_bounds = 0;
        __atomic_store_n(&game_config->bounds_bits, bounds_pair(pending_min, pending_max), __ATOMIC_RELEASE);
    }
    pthread_mutex_unlock(&guard);
    return owns_override ? JNI_TRUE : JNI_FALSE;
}

JNIEXPORT jint JNICALL Java_com_klab_lovelive_allstars_fovmod_FovMod_nativeConfigure(
        JNIEnv *env, jclass type, jfloat min, jfloat max, jint splash, jstring files_dir) {
    (void)type;
    if (!isfinite(min) || !isfinite(max) || min < .5f || max > 2.f || min > max ||
        (splash != 0 && splash != 1) || !files_dir) return -1;
    const char *directory = (*env)->GetStringUTFChars(env, files_dir, NULL);
    if (!directory) return -1;
    /* The path comes only from Context.getFilesDir(), never an exported intent. */
    pthread_mutex_lock(&guard);
    int length = snprintf(status_path, sizeof(status_path), "%s/fovmod_status.txt", directory);
    (*env)->ReleaseStringUTFChars(env, files_dir, directory);
    if (length < 0 || (size_t)length >= sizeof(status_path)) status_path[0] = '\0';
    pending_min = min;
    pending_max = max;
    pending_splash = (uint32_t)splash;
    ++generation;
    int result = apply_locked();
    if (!result && !worker_running) {
        pthread_t worker;
        worker_running = 1;
        if (pthread_create(&worker, NULL, wait_for_game, NULL)) {
            worker_running = 0;
            result = -3;
        } else pthread_detach(worker);
    }
    status_locked(result, result > 0 ? "applied" : result == 0 ? "waiting for the game" : "configuration failed");
    pthread_mutex_unlock(&guard);
    return result;
}
