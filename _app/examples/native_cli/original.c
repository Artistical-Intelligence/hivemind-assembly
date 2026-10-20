#include <stdio.h>
#include <stdint.h>
#ifdef _WIN32
#include <io.h>
#include <fcntl.h>
#endif
int main(void) {
#ifdef _WIN32
    _setmode(_fileno(stdout), _O_BINARY);
#endif
    uint32_t value;
    while (scanf("%u", &value) == 1)
        printf("%u\n", (unsigned)(value * 3u + 1u));
    return 0;
}
