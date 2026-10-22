/* Hivemind Assembly seeded randomness for native play-testing (LD_PRELOAD, Linux).
 *
 * While HA drives a game (HA_TICK_PORT is set), requests for operating-system
 * randomness (getrandom, getentropy, syscall(SYS_getrandom) and the arc4random
 * family) return bytes from seeded streams, so a run is a function of HA_TICK_SEED
 * and the input log. Each calling library has its own stream for its main-thread
 * requests and another for other threads, so a game's draws do not shift when a
 * driver or a worker thread asks for randomness at a different moment.
 *
 * Built with HA_UNDEEPBIND (the Godot lane), libraries opened with RTLD_DEEPBIND,
 * as Godot opens GDExtensions written in Rust or C++, are opened without it so their
 * requests reach these functions instead of binding straight to the C library.
 * Hardware instructions (RDRAND) and reads of /dev/urandom are not seeded.
 *
 * Both native lanes load this file, so it also disables core dumps while HA drives
 * the game: a crash then ends the process at once instead of after the system has
 * written or piped a dump, which HA could otherwise mistake for a frozen frame.
 * Without HA_TICK_PORT every function forwards to the C library unchanged.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <sched.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <unistd.h>

#define HA_STREAMS 64

static int ha_entropy_mode = -1; /* -1 not yet known, 0 forward, 1 seeded */
static uint64_t ha_entropy_seed;
static struct {
    uint64_t key, state;
} ha_streams[HA_STREAMS];
static int ha_stream_count;
static int ha_entropy_lock;
static long (*ha_real_syscall)(long, ...);

static void *ha_next(const char *name) {
    return dlsym(RTLD_NEXT, name);
}

/* A core-size limit of 1 byte stops file dumps (smaller than a page) and makes the
 * kernel abort piped dumps (apport, systemd-coredump) as well. */
__attribute__((constructor)) static void ha_no_core_dumps(void) {
    struct rlimit limit;
    if (!getenv("HA_TICK_PORT") || getrlimit(RLIMIT_CORE, &limit) || limit.rlim_max < 1) return;
    limit.rlim_cur = 1;
    setrlimit(RLIMIT_CORE, &limit);
}

static int ha_entropy_on(void) {
    if (ha_entropy_mode < 0) {
        const char *seed = getenv("HA_TICK_SEED");
        ha_entropy_seed = seed ? strtoull(seed, NULL, 10) : 0;
        ha_entropy_mode = getenv("HA_TICK_PORT") != NULL;
    }
    return ha_entropy_mode;
}

static uint64_t ha_mix(uint64_t value) {
    value += 0x9E3779B97F4A7C15ULL;
    value = (value ^ (value >> 30)) * 0xBF58476D1CE4E5B9ULL;
    value = (value ^ (value >> 27)) * 0x94D049BB133111EBULL;
    return value ^ (value >> 31);
}

/* The stream for a caller: its library's path and whether it runs on the main thread. */
static uint64_t ha_stream_key(void *caller) {
    Dl_info info;
    uint64_t key = 1469598103934665603ULL;
    const char *name = dladdr(caller, &info) && info.dli_fname ? info.dli_fname : "";
    const char *slash = strrchr(name, '/');
    for (const unsigned char *p = (const unsigned char *)(slash ? slash + 1 : name); *p; ++p) key = (key ^ *p) * 1099511628211ULL;
    if (!ha_real_syscall) ha_real_syscall = (long (*)(long, ...))ha_next("syscall");
    long thread = ha_real_syscall ? ha_real_syscall(SYS_gettid) : (long)getpid();
    return key ^ (thread == (long)getpid() ? 0x6D61696EULL : 0x6F746865ULL);
}

static void ha_entropy_fill(void *buffer, size_t size, void *caller) {
    uint64_t key = ha_stream_key(caller);
    unsigned char *out = buffer;
    while (__atomic_exchange_n(&ha_entropy_lock, 1, __ATOMIC_ACQUIRE)) sched_yield();
    int index = 0;
    while (index < ha_stream_count && ha_streams[index].key != key) ++index;
    if (index == ha_stream_count) {
        if (ha_stream_count < HA_STREAMS) ++ha_stream_count;
        else index = (int)(key % HA_STREAMS);
        ha_streams[index].key = key;
        ha_streams[index].state = ha_mix(ha_entropy_seed ^ ha_mix(key));
    }
    for (size_t i = 0; i < size; i += 8) {
        uint64_t word = ha_mix(ha_streams[index].state += 0x9E3779B97F4A7C15ULL);
        size_t take = size - i < 8 ? size - i : 8;
        memcpy(out + i, &word, take);
    }
    __atomic_store_n(&ha_entropy_lock, 0, __ATOMIC_RELEASE);
}

ssize_t getrandom(void *buffer, size_t size, unsigned int flags) {
    static ssize_t (*forward)(void *, size_t, unsigned int);
    if (!ha_entropy_on()) {
        if (!forward) forward = (ssize_t (*)(void *, size_t, unsigned int))ha_next("getrandom");
        if (forward) return forward(buffer, size, flags);
        errno = ENOSYS;
        return -1;
    }
    ha_entropy_fill(buffer, size, __builtin_return_address(0));
    return (ssize_t)size;
}

int getentropy(void *buffer, size_t size) {
    static int (*forward)(void *, size_t);
    if (!ha_entropy_on()) {
        if (!forward) forward = (int (*)(void *, size_t))ha_next("getentropy");
        if (forward) return forward(buffer, size);
        errno = ENOSYS;
        return -1;
    }
    if (size > 256) {
        errno = EIO;
        return -1;
    }
    ha_entropy_fill(buffer, size, __builtin_return_address(0));
    return 0;
}

long syscall(long number, ...) {
    va_list arguments;
    va_start(arguments, number);
    long a = va_arg(arguments, long), b = va_arg(arguments, long), c = va_arg(arguments, long);
    long d = va_arg(arguments, long), e = va_arg(arguments, long), f = va_arg(arguments, long);
    va_end(arguments);
    if (number == SYS_getrandom && ha_entropy_on()) {
        ha_entropy_fill((void *)a, (size_t)b, __builtin_return_address(0));
        return b;
    }
    if (!ha_real_syscall) ha_real_syscall = (long (*)(long, ...))ha_next("syscall");
    return ha_real_syscall(number, a, b, c, d, e, f);
}

void arc4random_buf(void *buffer, size_t size) {
    static void (*forward)(void *, size_t);
    if (!ha_entropy_on()) {
        if (!forward) forward = (void (*)(void *, size_t))ha_next("arc4random_buf");
        if (forward) forward(buffer, size);
        return;
    }
    ha_entropy_fill(buffer, size, __builtin_return_address(0));
}

uint32_t arc4random(void) {
    static uint32_t (*forward)(void);
    uint32_t value = 0;
    if (!ha_entropy_on()) {
        if (!forward) forward = (uint32_t (*)(void))ha_next("arc4random");
        return forward ? forward() : 0;
    }
    ha_entropy_fill(&value, sizeof value, __builtin_return_address(0));
    return value;
}

uint32_t arc4random_uniform(uint32_t bound) {
    static uint32_t (*forward)(uint32_t);
    if (!ha_entropy_on()) {
        if (!forward) forward = (uint32_t (*)(uint32_t))ha_next("arc4random_uniform");
        return forward ? forward(bound) : 0;
    }
    if (bound < 2) return 0;
    uint32_t floor = (uint32_t)(-bound) % bound, value;
    do ha_entropy_fill(&value, sizeof value, __builtin_return_address(0));
    while (value < floor);
    return value % bound;
}

#ifdef HA_UNDEEPBIND
void *dlopen(const char *file, int mode) {
    static void *(*forward)(const char *, int);
    if (!forward) forward = (void *(*)(const char *, int))ha_next("dlopen");
    if (ha_entropy_on()) mode &= ~RTLD_DEEPBIND;
    return forward(file, mode);
}
#endif
