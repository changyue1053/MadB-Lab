/* I01 initial recipe only: independent public C consumer, no producer oracle. */
#ifndef _GNU_SOURCE
#define _GNU_SOURCE 1
#endif
#include <dlfcn.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include "reading_demo.h"
#include "reading_demo_native.h"

static unsigned checks;
#define CHECK(e) do { ++checks; if (!(e)) { fprintf(stderr, "I01 values assertion:%d:%s\n", __LINE__, #e); exit(2); } } while (0)
_Static_assert(sizeof(reading_demo_Reading) == 72, "initial Reading size");
_Static_assert(_Alignof(reading_demo_Reading) == 4, "initial Reading alignment");

static void hex(const uint8_t *bytes, size_t size) {
    for (size_t i = 0; i < size; ++i) printf("%02x", bytes[i]);
}

static void json_string(const char *value) {
    putchar('"');
    for (const unsigned char *p = (const unsigned char *)value; *p; ++p) {
        if (*p == '"' || *p == '\\') { putchar('\\'); putchar(*p); }
        else if (*p < 32) printf("\\u%04x", *p);
        else putchar(*p);
    }
    putchar('"');
}

static void binding(const char *expected) {
    uint8_t identity[64], want[64];
    CHECK(strlen(expected) == 128);
    for (unsigned i = 0; i < 64; ++i) {
        unsigned n = 0;
        char pair[3] = {expected[2*i], expected[2*i+1], 0};
        CHECK(sscanf(pair, "%2x", &n) == 1); want[i] = (uint8_t)n;
    }
    CHECK(reading_demo_bootstrap_v1(1, identity, 64) == 0);
    CHECK(memcmp(identity, want, 64) == 0);
    Dl_info image;
    CHECK(dladdr((void *)(uintptr_t)reading_demo_bootstrap_v1, &image) != 0);
    CHECK(image.dli_fname != NULL);
    printf("{\"event\":\"binding\",\"image\":"); json_string(image.dli_fname);
    printf(",\"identity\":\""); hex(identity, 64);
    printf("\",\"pid\":%ld}\n", (long)getpid());
}

static void bootstrap(void) {
    uint8_t out[65]; memset(out, 0xa5, sizeof out);
    CHECK(reading_demo_bootstrap_v1(1, out, 63) == 1);
    CHECK(reading_demo_bootstrap_v1(1, out, 65) == 1);
    CHECK(reading_demo_bootstrap_v1(1, NULL, 64) == 1);
    for (unsigned i = 0; i < 65; ++i) CHECK(out[i] == 0xa5);
    CHECK(reading_demo_bootstrap_v1(2, out, 64) == 11);
    for (unsigned i = 0; i < 64; ++i) CHECK(out[i] == 0);
    CHECK(out[64] == 0xa5);
}

static void ordinary_vector(const char *name, int32_t value, const uint8_t *input,
                            uint32_t input_size, const uint8_t *expected, uint32_t expected_size) {
    CHECK(input_size <= 64 && expected_size <= 64);
    reading_demo_Reading in = {0};
    in.value = value; in.label.byte_count = input_size;
    memset(in.label.bytes, 0xa5, sizeof in.label.bytes);
    memcpy(in.label.bytes, input, input_size);
    reading_demo_Reading before = in;
    reading_demo_ReadingResult result = reading_demo_normalize(in);
    CHECK(memcmp(&in, &before, sizeof in) == 0);
    CHECK(result.kind == 0 && result.status == 0);
    CHECK(result.error.domain == 0 && result.error.code == 0);
    CHECK(result.value.value == value && result.value.label.byte_count == expected_size);
    CHECK(memcmp(result.value.label.bytes, expected, expected_size) == 0);
    for (unsigned i = expected_size; i < 64; ++i) CHECK(result.value.label.bytes[i] == 0);
    printf("{\"event\":\"value\",\"id\":\"%s\",\"value\":%d,\"hex\":\"", name, (int)result.value.value);
    hex(result.value.label.bytes, result.value.label.byte_count);
    printf("\",\"input_preserved\":true,\"tail_zero\":true,\"kind\":%u,\"status\":%d,\"domain\":%u,\"code\":%d}\n",
           (unsigned)result.kind, (int)result.status, (unsigned)result.error.domain, (int)result.error.code);
}

static void ordinary(void) {
    const uint8_t ascii[] = "  x  ", x[] = "x", spaces[] = " \t\r\n ", empty[] = "";
    const uint8_t unicode[] = {0xe3,0x80,0x80,0xe6,0xb8,0xa9,0xe5,0xba,0xa6,0xc2,0xa0};
    const uint8_t temperature[] = {0xe6,0xb8,0xa9,0xe5,0xba,0xa6};
    const uint8_t nul[] = {32,'a',0,'b',32}, inner_nul[] = {'a',0,'b'};
    const uint8_t emoji[] = {0xf0,0x9f,0x8c,0xa1};
    const uint8_t not_space[] = {32,0xe2,0x80,0x8b,32}, zero_width[] = {0xe2,0x80,0x8b};
    uint8_t full[64], full_unicode[64]; memset(full, 'x', sizeof full);
    for (unsigned i = 0; i < 64; i += 4) memcpy(full_unicode+i, emoji, 4);
    ordinary_vector("ascii", 7, ascii, 5, x, 1);
    ordinary_vector("whitespace", 7, spaces, 5, empty, 0);
    ordinary_vector("unicode", -7, unicode, sizeof unicode, temperature, sizeof temperature);
    ordinary_vector("empty", 0, empty, 0, empty, 0);
    ordinary_vector("nul", 7, nul, sizeof nul, inner_nul, sizeof inner_nul);
    ordinary_vector("supplementary", 7, emoji, sizeof emoji, emoji, sizeof emoji);
    ordinary_vector("capacity-ascii", 7, full, 64, full, 64);
    ordinary_vector("capacity-unicode", 7, full_unicode, 64, full_unicode, 64);
    ordinary_vector("minimum", INT32_MIN, ascii, 5, x, 1);
    ordinary_vector("maximum", INT32_MAX, ascii, 5, x, 1);
    ordinary_vector("non-whitespace", 7, not_space, sizeof not_space, zero_width, sizeof zero_width);
}

int main(int argc, char **argv) {
    CHECK(argc == 3);
    CHECK(strcmp(argv[1], "bootstrap") == 0 || strcmp(argv[1], "ordinary") == 0);
    binding(argv[2]);
    if (strcmp(argv[1], "bootstrap") == 0) bootstrap(); else ordinary();
    printf("{\"result\":\"passed\",\"mode\":\"%s\",\"checks\":%u,\"vectors\":%u,\"scope\":\"i01-initial-native-values\"}\n",
           argv[1], checks, strcmp(argv[1], "ordinary") == 0 ? 11u : 0u);
    return 0;
}
