/* Hivemind Assembly SDL2 tick adapter (protocol 1), loaded with LD_PRELOAD.
 *
 * Steps an unmodified SDL2 game one presented frame per input record received over a
 * local socket. At each SDL_RenderPresent, SDL_GL_SwapWindow or
 * SDL_UpdateWindowSurface it captures the frame being presented (scaled to the
 * declared size), sends it as the previous tick's record, then blocks for the next
 * input record and presses or releases the mapped keys. A game that waits for events
 * (SDL_WaitEvent) instead of presenting every frame passes one tick, with the frame it
 * last presented, each time it would block. The game's own calls to SDL
 * and C library clocks see virtual time that advances one fixed frame step per tick
 * (plus any SDL_Delay), and its randomness requests return seeded bytes (ha_entropy.c,
 * built into the same library). HA's key presses are its only input: events from the
 * window system and devices (window, mouse, touch, controllers, text) arrive at times
 * that differ between runs and are not delivered, so a run is a function of the input
 * log. Without HA_TICK_PORT nothing changes.
 */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <dlfcn.h>
#include <errno.h>
#include <link.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>

typedef struct SDL_Window SDL_Window;
typedef struct SDL_Renderer SDL_Renderer;
typedef struct {
    uint32_t flags;
    void *format;
    int w, h, pitch;
    void *pixels;
} SDL_Surface;
typedef union {
    uint32_t type;
    uint8_t padding[56];
} SDL_Event;
typedef struct {
    uint32_t type, timestamp, windowID;
    uint8_t state, repeat, padding2, padding3;
    int32_t scancode, sym;
    uint16_t mod;
    uint32_t unused;
} SDL_KeyboardEvent;

#define SDL_KEYDOWN 0x300
#define SDL_KEYUP 0x301
#define HA_MARK0 'H' /* HA's key events carry this mark in their padding bytes */
#define HA_MARK1 'A'
#define SDL_PIXELFORMAT_ABGR8888 0x16762004u
#define KEYS 512
#define MAX_INPUTS 64
#define BASE_EPOCH 946684800LL /* 2000-01-01, a fixed calendar start */

static int ha_socket = -1;
static unsigned ha_record = 1, ha_inputs = 0, ha_width = 0, ha_height = 0;
static int ha_scancode[MAX_INPUTS], ha_keycode[MAX_INPUTS];
static unsigned char ha_held[MAX_INPUTS];
static unsigned char ha_keys[KEYS];
static uint64_t ha_now_ns, ha_frame_ns = 16666667, ha_frame_start;
static uint32_t ha_ticks;
static uint32_t ha_window;
static uint8_t *ha_frame, *ha_scratch;
static size_t ha_scratch_size;
static uintptr_t ha_ranges[8][2];
static int ha_range_count;

static void *real(const char *name) {
    void *symbol = dlsym(RTLD_NEXT, name);
    if (!symbol) {
        fprintf(stderr, "ha_sdl_tick: %s unavailable\n", name);
        _exit(71);
    }
    return symbol;
}

static int ha_note_object(struct dl_phdr_info *info, size_t size, void *data) {
    (void)size;
    int *index = data;
    const char *name = info->dlpi_name ? info->dlpi_name : "";
    /* The program itself (first entry) and the C++ and Rust runtimes it calls through. */
    if (!(*index == 0 || strstr(name, "libstdc++") || strstr(name, "libc++"))) {
        ++*index;
        return 0;
    }
    ++*index;
    for (int i = 0; i < info->dlpi_phnum && ha_range_count < 8; ++i) {
        const ElfW(Phdr) *segment = &info->dlpi_phdr[i];
        if (segment->p_type == PT_LOAD && (segment->p_flags & PF_X)) {
            ha_ranges[ha_range_count][0] = info->dlpi_addr + segment->p_vaddr;
            ha_ranges[ha_range_count][1] = info->dlpi_addr + segment->p_vaddr + segment->p_memsz;
            ++ha_range_count;
        }
    }
    return 0;
}

/* Only the game's own code (and its language runtime) sees virtual clocks; SDL,
 * drivers and the window system keep real time for their internal timeouts. */
static int ha_from_game(void *caller) {
    uintptr_t address = (uintptr_t)caller;
    for (int i = 0; i < ha_range_count; ++i)
        if (address >= ha_ranges[i][0] && address < ha_ranges[i][1]) return 1;
    return 0;
}

static int ha_read_exact(void *buffer, size_t size) {
    size_t done = 0;
    while (done < size) {
        ssize_t got = recv(ha_socket, (char *)buffer + done, size - done, 0);
        if (got < 0 && errno == EINTR) continue;
        if (got <= 0) return -1;
        done += (size_t)got;
    }
    return 0;
}

static int ha_write_exact(const void *buffer, size_t size) {
    size_t done = 0;
    while (done < size) {
        ssize_t sent = send(ha_socket, (const char *)buffer + done, size - done, MSG_NOSIGNAL);
        if (sent < 0 && errno == EINTR) continue;
        if (sent <= 0) return -1;
        done += (size_t)sent;
    }
    return 0;
}

__attribute__((constructor)) static void ha_start(void) {
    const char *port = getenv("HA_TICK_PORT"), *token = getenv("HA_TICK_TOKEN");
    if (!port || !token) return;
    int index = 0;
    dl_iterate_phdr(ha_note_object, &index);
    const char *value;
    if ((value = getenv("HA_TICK_RECORD"))) ha_record = (unsigned)strtoul(value, NULL, 10);
    if ((value = getenv("HA_TICK_FRAME_NS"))) ha_frame_ns = strtoull(value, NULL, 10);
    if ((value = getenv("HA_TICK_FRAME"))) sscanf(value, "%u,%u", &ha_width, &ha_height);
    if ((value = getenv("HA_TICK_KEYS"))) {
        const char *cursor = value;
        while (*cursor && ha_inputs < MAX_INPUTS) {
            int scancode, keycode, used = 0;
            if (sscanf(cursor, "%d:%d%n", &scancode, &keycode, &used) != 2) break;
            if (scancode < 0 || scancode >= KEYS) break;
            ha_scancode[ha_inputs] = scancode;
            ha_keycode[ha_inputs] = keycode;
            ++ha_inputs;
            cursor += used;
            if (*cursor == ',') ++cursor;
        }
    }
    if (ha_width && ha_height) ha_frame = calloc((size_t)ha_width * ha_height, 4);
    int connection = socket(AF_INET, SOCK_STREAM, 0);
    struct sockaddr_in address = {0};
    address.sin_family = AF_INET;
    address.sin_port = htons((uint16_t)atoi(port));
    address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    if (connection < 0 || connect(connection, (struct sockaddr *)&address, sizeof address)) _exit(70);
    int on = 1;
    setsockopt(connection, IPPROTO_TCP, TCP_NODELAY, &on, sizeof on);
    ha_socket = connection;
    unsigned char hello[5 + 64];
    size_t length = strlen(token) / 2;
    if (length > 64) length = 64;
    memcpy(hello, "HATK", 4);
    hello[4] = 1;
    for (size_t i = 0; i < length; ++i) {
        unsigned byte;
        sscanf(token + 2 * i, "%2x", &byte);
        hello[5 + i] = (unsigned char)byte;
    }
    if (ha_write_exact(hello, 5 + length)) _exit(70);
}

/* Box-filter (or nearest for upscaling) RGBA scaling to the declared frame size. */
static void ha_scale(const uint8_t *source, unsigned width, unsigned height, size_t pitch, int flip) {
    for (unsigned y = 0; y < ha_height; ++y) {
        unsigned y0 = y * height / ha_height, y1 = (y + 1) * height / ha_height;
        if (y1 <= y0) y1 = y0 + 1;
        for (unsigned x = 0; x < ha_width; ++x) {
            unsigned x0 = x * width / ha_width, x1 = (x + 1) * width / ha_width;
            if (x1 <= x0) x1 = x0 + 1;
            unsigned long sum[4] = {0, 0, 0, 0}, count = 0;
            for (unsigned sy = y0; sy < y1 && sy < height; ++sy) {
                const uint8_t *row = source + (size_t)(flip ? height - 1 - sy : sy) * pitch;
                for (unsigned sx = x0; sx < x1 && sx < width; ++sx) {
                    for (int c = 0; c < 4; ++c) sum[c] += row[sx * 4 + c];
                    ++count;
                }
            }
            uint8_t *out = ha_frame + ((size_t)y * ha_width + x) * 4;
            for (int c = 0; c < 4; ++c) out[c] = (uint8_t)(count ? sum[c] / count : 0);
            out[3] = 255;
        }
    }
}

static uint8_t *ha_buffer(size_t size) {
    if (size > ha_scratch_size) {
        free(ha_scratch);
        ha_scratch = malloc(size);
        ha_scratch_size = ha_scratch ? size : 0;
    }
    return ha_scratch;
}

static void ha_apply(const unsigned char *record, uint32_t window) {
    int (*push)(SDL_Event *) = real("SDL_PushEvent");
    for (unsigned i = 0; i < ha_inputs; ++i) {
        unsigned char want = (record[i >> 3] >> (i & 7)) & 1;
        if (want == ha_held[i]) continue;
        ha_held[i] = want;
        ha_keys[ha_scancode[i]] = want;
        SDL_Event event;
        memset(&event, 0, sizeof event);
        SDL_KeyboardEvent *key = (SDL_KeyboardEvent *)&event;
        key->type = want ? SDL_KEYDOWN : SDL_KEYUP;
        key->timestamp = (uint32_t)(ha_now_ns / 1000000);
        key->windowID = window;
        key->state = want;
        key->padding2 = HA_MARK0;
        key->padding3 = HA_MARK1;
        key->scancode = ha_scancode[i];
        key->sym = ha_keycode[i];
        push(&event);
    }
}

/* One tick boundary: send the frame being presented as the previous tick's record,
 * then wait for the next input. 'E' or a closed connection ends play. */
static void ha_boundary(uint32_t window) {
    if (ha_socket < 0) return;
    ha_window = window;
    if (ha_ticks > 0) {
        size_t payload = ha_frame ? (size_t)ha_width * ha_height * 4 : 0;
        unsigned char header[9] = {'T'};
        uint32_t tick = ha_ticks - 1, size = (uint32_t)payload;
        memcpy(header + 1, &tick, 4);
        memcpy(header + 5, &size, 4);
        if (ha_write_exact(header, 9) || (payload && ha_write_exact(ha_frame, payload))) _exit(0);
    }
    unsigned char kind, record[64];
    if (ha_read_exact(&kind, 1) || kind != 'I' || ha_record > sizeof record || ha_read_exact(record, ha_record))
        _exit(0);
    if (ha_now_ns < ha_frame_start + ha_frame_ns) ha_now_ns = ha_frame_start + ha_frame_ns;
    ha_frame_start = ha_now_ns;
    ha_apply(record, window);
    ++ha_ticks;
}

void SDL_RenderPresent(SDL_Renderer *renderer) {
    static void (*present)(SDL_Renderer *);
    if (!present) present = real("SDL_RenderPresent");
    if (ha_socket >= 0) {
        if (ha_frame) {
            int (*size)(SDL_Renderer *, int *, int *) = real("SDL_GetRendererOutputSize");
            int (*read)(SDL_Renderer *, const void *, uint32_t, void *, int) = real("SDL_RenderReadPixels");
            int width = 0, height = 0;
            if (!size(renderer, &width, &height) && width > 0 && height > 0) {
                uint8_t *pixels = ha_buffer((size_t)width * height * 4);
                if (pixels && !read(renderer, NULL, SDL_PIXELFORMAT_ABGR8888, pixels, width * 4))
                    ha_scale(pixels, (unsigned)width, (unsigned)height, (size_t)width * 4, 0);
            }
        }
        SDL_Window *(*window_of)(SDL_Renderer *) = real("SDL_RenderGetWindow");
        uint32_t (*window_id)(SDL_Window *) = real("SDL_GetWindowID");
        SDL_Window *window = window_of(renderer);
        ha_boundary(window ? window_id(window) : 0);
    }
    present(renderer);
}

void SDL_GL_SwapWindow(SDL_Window *window) {
    static void (*swap)(SDL_Window *);
    if (!swap) swap = real("SDL_GL_SwapWindow");
    if (ha_socket >= 0) {
        if (ha_frame) {
            void *(*address)(const char *) = real("SDL_GL_GetProcAddress");
            void (*drawable)(SDL_Window *, int *, int *) = real("SDL_GL_GetDrawableSize");
            void (*read)(int, int, int, int, unsigned, unsigned, void *) = address("glReadPixels");
            void (*store)(unsigned, int) = address("glPixelStorei");
            void (*integer)(unsigned, int *) = address("glGetIntegerv");
            void (*bind)(unsigned, unsigned) = address("glBindFramebuffer");
            void (*buffer)(unsigned) = address("glReadBuffer");
            int width = 0, height = 0;
            drawable(window, &width, &height);
            if (read && store && integer && width > 0 && height > 0) {
                int alignment = 4, framebuffer = 0, source = 0;
                integer(0x0D05, &alignment);      /* GL_PACK_ALIGNMENT */
                integer(0x8CAA, &framebuffer);    /* GL_READ_FRAMEBUFFER_BINDING */
                integer(0x0C02, &source);         /* GL_READ_BUFFER */
                if (framebuffer && bind) bind(0x8CA8, 0);
                if (buffer) buffer(0x0405);       /* GL_BACK */
                store(0x0D05, 1);
                uint8_t *pixels = ha_buffer((size_t)width * height * 4);
                if (pixels) {
                    read(0, 0, width, height, 0x1908, 0x1401, pixels); /* GL_RGBA, GL_UNSIGNED_BYTE */
                    ha_scale(pixels, (unsigned)width, (unsigned)height, (size_t)width * 4, 1);
                }
                store(0x0D05, alignment);
                if (buffer && source) buffer((unsigned)source);
                if (framebuffer && bind) bind(0x8CA8, (unsigned)framebuffer);
            }
        }
        uint32_t (*window_id)(SDL_Window *) = real("SDL_GetWindowID");
        ha_boundary(window_id(window));
    }
    swap(window);
}

int SDL_UpdateWindowSurface(SDL_Window *window) {
    static int (*update)(SDL_Window *);
    if (!update) update = real("SDL_UpdateWindowSurface");
    if (ha_socket >= 0) {
        if (ha_frame) {
            SDL_Surface *(*surface_of)(SDL_Window *) = real("SDL_GetWindowSurface");
            SDL_Surface *(*convert)(SDL_Surface *, uint32_t, uint32_t) = real("SDL_ConvertSurfaceFormat");
            void (*release)(SDL_Surface *) = real("SDL_FreeSurface");
            SDL_Surface *surface = surface_of(window);
            SDL_Surface *copy = surface ? convert(surface, SDL_PIXELFORMAT_ABGR8888, 0) : NULL;
            if (copy) {
                ha_scale(copy->pixels, (unsigned)copy->w, (unsigned)copy->h, (size_t)copy->pitch, 0);
                release(copy);
            }
        }
        uint32_t (*window_id)(SDL_Window *) = real("SDL_GetWindowID");
        ha_boundary(window_id(window));
    }
    return update(window);
}

/* Whether an event reaches the game while HA drives it: HA's own key events, quit,
 * render resets and the game's own events do; window-system and device events do not. */
static int ha_deliver(const SDL_Event *event) {
    uint32_t type = event->type;
    if (type == SDL_KEYDOWN || type == SDL_KEYUP) {
        const SDL_KeyboardEvent *key = (const SDL_KeyboardEvent *)event;
        return key->padding2 == HA_MARK0 && key->padding3 == HA_MARK1;
    }
    return !((type >= 0x101 && type <= 0x1FF) ||  /* application lifecycle, locale, display */
             (type >= 0x200 && type <= 0x2FF) ||  /* window and window-manager events */
             (type >= 0x302 && type <= 0x3FF) ||  /* text input, keymap changes */
             (type >= 0x400 && type <= 0x1FFF));  /* mouse, controllers, touch, gestures, clipboard, drops, audio devices, sensors */
}

/* The next deliverable event, or 0; a null event only asks whether any is pending. */
static int ha_poll(SDL_Event *event) {
    static int (*poll)(SDL_Event *);
    if (!poll) poll = real("SDL_PollEvent");
    if (!event) return poll(NULL);
    while (poll(event))
        if (ha_deliver(event)) return 1;
    return 0;
}

/* For waits: SDL ends each poll batch at a marker it queues, and events queued after
 * the marker (HA's presses among them) come with the next poll, so a wait polls twice. */
static int ha_poll_waiting(SDL_Event *event) {
    return ha_poll(event) || ha_poll(event);
}

int SDL_PollEvent(SDL_Event *event) {
    static int (*poll)(SDL_Event *);
    if (!poll) poll = real("SDL_PollEvent");
    if (ha_socket < 0) return poll(event);
    return ha_poll(event);
}

int SDL_WaitEvent(SDL_Event *event) {
    static int (*wait)(SDL_Event *);
    if (!wait) wait = real("SDL_WaitEvent");
    if (ha_socket < 0) return wait(event);
    /* Instead of blocking, each wait without events passes a tick. */
    while (!ha_poll_waiting(event)) ha_boundary(ha_window);
    return 1;
}

int SDL_WaitEventTimeout(SDL_Event *event, int timeout) {
    static int (*wait)(SDL_Event *, int);
    if (!wait) wait = real("SDL_WaitEventTimeout");
    if (ha_socket < 0) return wait(event, timeout);
    if (ha_poll_waiting(event)) return 1;
    ha_boundary(ha_window);
    return ha_poll_waiting(event);
}

const uint8_t *SDL_GetKeyboardState(int *count) {
    static const uint8_t *(*state)(int *);
    if (!state) state = real("SDL_GetKeyboardState");
    if (ha_socket < 0) return state(count);
    if (count) *count = KEYS;
    return ha_keys;
}

int SDL_GetModState(void) {
    static int (*state)(void);
    if (!state) state = real("SDL_GetModState");
    return ha_socket < 0 ? state() : 0;
}

uint32_t SDL_GetTicks(void) {
    static uint32_t (*ticks)(void);
    if (!ticks) ticks = real("SDL_GetTicks");
    return ha_socket < 0 ? ticks() : (uint32_t)(ha_now_ns / 1000000);
}

uint64_t SDL_GetTicks64(void) {
    static uint64_t (*ticks)(void);
    if (!ticks) ticks = real("SDL_GetTicks64");
    return ha_socket < 0 ? ticks() : ha_now_ns / 1000000;
}

uint64_t SDL_GetPerformanceCounter(void) {
    static uint64_t (*counter)(void);
    if (!counter) counter = real("SDL_GetPerformanceCounter");
    return ha_socket < 0 ? counter() : ha_now_ns;
}

uint64_t SDL_GetPerformanceFrequency(void) {
    static uint64_t (*frequency)(void);
    if (!frequency) frequency = real("SDL_GetPerformanceFrequency");
    return ha_socket < 0 ? frequency() : 1000000000ULL;
}

void SDL_Delay(uint32_t ms) {
    static void (*delay)(uint32_t);
    if (!delay) delay = real("SDL_Delay");
    if (ha_socket < 0) {
        delay(ms);
        return;
    }
    /* Frame limiters wait for virtual time, which a delay advances at once. */
    if (ms > 1000) ms = 1000;
    ha_now_ns += (uint64_t)ms * 1000000;
}

time_t time(time_t *result) {
    static time_t (*clock_time)(time_t *);
    if (!clock_time) clock_time = real("time");
    if (ha_socket < 0 || !ha_from_game(__builtin_return_address(0))) return clock_time(result);
    time_t value = (time_t)(BASE_EPOCH + ha_now_ns / 1000000000ULL);
    if (result) *result = value;
    return value;
}

int gettimeofday(struct timeval *value, void *zone) {
    static int (*clock_time)(struct timeval *, void *);
    if (!clock_time) clock_time = real("gettimeofday");
    if (ha_socket < 0 || !ha_from_game(__builtin_return_address(0))) return clock_time(value, zone);
    if (value) {
        value->tv_sec = (time_t)(BASE_EPOCH + ha_now_ns / 1000000000ULL);
        value->tv_usec = (suseconds_t)(ha_now_ns % 1000000000ULL / 1000);
    }
    return 0;
}

int clock_gettime(clockid_t clock, struct timespec *value) {
    static int (*clock_time)(clockid_t, struct timespec *);
    if (!clock_time) clock_time = real("clock_gettime");
    if (ha_socket < 0 || !ha_from_game(__builtin_return_address(0)) || !value) return clock_time(clock, value);
    uint64_t now = ha_now_ns + (clock == CLOCK_REALTIME || clock == CLOCK_REALTIME_COARSE ? (uint64_t)BASE_EPOCH * 1000000000ULL : 0);
    value->tv_sec = (time_t)(now / 1000000000ULL);
    value->tv_nsec = (long)(now % 1000000000ULL);
    return 0;
}
