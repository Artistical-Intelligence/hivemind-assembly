/* Software reconstruction: explicit event queue and sprite overlay. */
#include <stdio.h>

static int clamp(int value) { return value < 0 ? 0 : value > 14 ? 14 : value; }

int main(void) {
    struct Event { int tick, dx, dy; } events[64];
    int count = 0, tick, dx, dy, fields;
    while ((fields = scanf("%d %d %d", &tick, &dx, &dy)) == 3) {
        if (count == 64 || tick < 0 || tick >= 16 || dx < -16 || dx > 16 || dy < -16 || dy > 16)
            return 2;
        events[count++] = (struct Event){tick, dx, dy};
    }
    if (fields != EOF) return 2;
    FILE *capture = fopen("frames.rgba", "wb");
    if (!capture) return 3;
    int x = 1, y = 1;
    for (int frame = 0; frame < 16; ++frame) {
        for (int e = 0; e < count; ++e) {
            if (events[e].tick == frame) {
                x = clamp(x + events[e].dx);
                y = clamp(y + events[e].dy);
            }
        }
        unsigned char pixels[16][16][4];
        for (int row = 0; row < 16; ++row) {
            for (int col = 0; col < 16; ++col) {
                pixels[row][col][0] = (unsigned char)(col * 8);
                pixels[row][col][1] = (unsigned char)(row * 8);
                pixels[row][col][2] = 32;
                pixels[row][col][3] = 255;
            }
        }
        for (int row = y; row < y + 2; ++row) {
            for (int col = x; col < x + 2; ++col) {
                pixels[row][col][0] = 240;
                pixels[row][col][1] = 80;
                pixels[row][col][2] = 20;
            }
        }
        if (fwrite(pixels, 1, sizeof pixels, capture) != sizeof pixels) {
            fclose(capture); return 4;
        }
    }
    if (fclose(capture)) return 4;
    FILE *state = fopen("final.bin", "wb");
    if (!state) return 3;
    unsigned char position[2] = {(unsigned char)x, (unsigned char)y};
    int failed = fwrite(position, 1, sizeof position, state) != sizeof position;
    return (fclose(state) || failed) ? 4 : 0;
}
