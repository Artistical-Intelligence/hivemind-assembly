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
    uint32_t input;
    while (scanf("%u", &input) == 1) {
        uint32_t recovered = input + input;
        recovered += input;
        recovered += 1u;
        printf("%u\n", (unsigned)recovered);
    }
    return 0;
}
