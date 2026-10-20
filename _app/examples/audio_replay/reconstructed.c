/* Equivalent integer pulse generator using an explicit replay event queue. */
#include <stdint.h>
#include <stdio.h>

int main(void) {
    struct Event { int tick, level; } events[32];
    int count = 0, tick, level;
    while (scanf("%d %d", &tick, &level) == 2) {
        if (count == 32 || tick < 0 || tick >= 32 || level < -30000 || level > 30000)
            return 2;
        events[count++] = (struct Event){tick, level};
    }
    FILE *out = fopen("audio.pcm", "wb");
    if (!out) return 3;
    int amplitude = 0;
    for (int frame = 0; frame < 32; ++frame) {
        for (int e = 0; e < count; ++e)
            if (events[e].tick == frame) amplitude = events[e].level;
        int left = (frame & 4) ? -amplitude : amplitude;
        for (int channel = 0; channel < 2; ++channel) {
            uint16_t bits = (uint16_t)(channel ? -left : left);
            fputc(bits & 255, out);
            fputc(bits >> 8, out);
        }
    }
    return fclose(out) ? 4 : 0;
}
