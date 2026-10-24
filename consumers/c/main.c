/* Independent Lab consumer: only the installed candidate headers are included. */
#define _GNU_SOURCE 1
#include "madb_rust.h"
#ifdef MADB_LAB_TEST_SUPPORT
#include "test-support.h"
#endif
#include <inttypes.h>
#include <dlfcn.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CHECK(x) do { if (!(x)) { fprintf(stderr, "assertion:%d:%s\n", __LINE__, #x); exit(2); } } while (0)
#define STATUS(call, expected) do { MadbStatus actual_ = (call); CHECK(actual_ == (expected)); } while (0)
static MadbError error;

static void clean_error(void) { CHECK(error.domain == 0 && error.code == 0); }
static MadbHandle create(void) {
    MadbHandle engine = 0;
    STATUS(madb_fixture_create(&engine, &error), MADB_OK);
    CHECK(engine != 0); clean_error(); return engine;
}
static void close_release(MadbHandle handle) {
    STATUS(madb_fixture_request_close(handle, &error), MADB_OK);
    STATUS(madb_fixture_await_closed(handle, 5000, &error), MADB_OK);
    STATUS(madb_fixture_release_handle(handle, &error), MADB_OK);
}
static void decode_identity(const char *hex, uint8_t output[64]) {
    CHECK(strlen(hex) == 128);
    for (size_t i = 0; i < 64; i++) {
        unsigned byte = 0; CHECK(sscanf(hex + i * 2, "%2x", &byte) == 1);
        output[i] = (uint8_t)byte;
    }
}
static int connect(const char *expected_hex) {
    uint8_t actual[64], expected[64]; decode_identity(expected_hex, expected);
    STATUS(madb_fixture_bootstrap(1, actual, sizeof actual), MADB_OK);
    if (memcmp(actual, expected, 32) != 0) {
        puts("{\"rejection\":\"AbiMismatch\"}"); return 40;
    }
    if (memcmp(actual + 32, expected + 32, 32) != 0) {
        puts("{\"rejection\":\"ProfileMismatch\"}"); return 41;
    }
    return 0;
}
static void bootstrap(void) {
    uint8_t value[64]; memset(value, 0xaa, sizeof value);
    STATUS(madb_fixture_bootstrap(2, value, 64), MADB_UNSUPPORTED);
    for (size_t i = 0; i < sizeof value; i++) CHECK(value[i] == 0);
    STATUS(madb_fixture_bootstrap(1, value, 63), MADB_INVALID_ARGUMENT);
    STATUS(madb_fixture_bootstrap(1, NULL, 64), MADB_INVALID_ARGUMENT);
}
static void data(void) {
    MadbHandle engine = create(); uint64_t sum = 99;
    const uint8_t bytes[] = {0, 1, 127, 128, 255};
    STATUS(madb_fixture_checksum(engine, bytes, sizeof bytes, &sum, &error), MADB_OK);
    CHECK(sum == 511); clean_error();
    STATUS(madb_fixture_checksum(engine, NULL, 0, &sum, &error), MADB_OK);
    CHECK(sum == 0);
    uint8_t *maximum = malloc(65536); CHECK(maximum != NULL); memset(maximum, 255, 65536);
    STATUS(madb_fixture_checksum(engine, maximum, 65536, &sum, &error), MADB_OK);
    CHECK(sum == UINT64_C(16711680)); free(maximum);
    sum = 99; error = (MadbError){17, -2};
    STATUS(madb_fixture_checksum(engine, NULL, 1, &sum, &error), MADB_INVALID_ARGUMENT);
    CHECK(sum == 0); clean_error();
    sum = 99;
    STATUS(madb_fixture_checksum(engine, bytes, 65537, &sum, &error), MADB_INVALID_ARGUMENT);
    CHECK(sum == 0); clean_error();
    sum = 99;
    STATUS(madb_fixture_checksum(0, bytes, sizeof bytes, &sum, &error), MADB_INVALID_HANDLE);
    CHECK(sum == 0); clean_error(); close_release(engine);
}
static void lifecycle(void) {
    MadbHandle engine = create(); uint64_t sum = 99;
    STATUS(madb_fixture_await_closed(engine, 0, &error), MADB_BUSY);
    STATUS(madb_fixture_release_handle(engine, &error), MADB_BUSY);
    STATUS(madb_fixture_request_close(engine, &error), MADB_OK);
    STATUS(madb_fixture_request_close(engine, &error), MADB_OK);
    STATUS(madb_fixture_await_closed(engine, 5000, &error), MADB_OK);
    STATUS(madb_fixture_checksum(engine, NULL, 0, &sum, &error), MADB_CLOSED);
    CHECK(sum == 0); clean_error();
    STATUS(madb_fixture_release_handle(engine, &error), MADB_OK);
    STATUS(madb_fixture_release_handle(engine, &error), MADB_INVALID_HANDLE);
    STATUS(madb_fixture_request_close(engine, &error), MADB_INVALID_HANDLE);
    MadbHandle next = create(); CHECK(next > engine); close_release(next);
}
typedef struct Context {
    atomic_uint calls;
    atomic_bool alive;
    uint64_t sequence;
    uint32_t state;
    MadbHandle engine;
    int close_on_callback;
} Context;
static void callback(void *opaque, uint64_t sequence, uint32_t state) {
    Context *context = opaque;
    CHECK(atomic_load(&context->alive));
    CHECK(sequence > context->sequence);
    context->sequence = sequence; context->state = state;
    atomic_fetch_add(&context->calls, 1);
    printf("{\"event\":\"callback-enter\",\"sequence\":%" PRIu64 ",\"state\":%" PRIu32 "}\n", sequence, state);
    if (context->close_on_callback) {
        MadbError own_error;
        STATUS(madb_fixture_request_close(context->engine, &own_error), MADB_OK);
        STATUS(madb_fixture_await_closed(context->engine, 0, &own_error), MADB_WOULD_DEADLOCK);
    }
}
static Context context_for(MadbHandle engine) {
    Context result = {0}; atomic_init(&result.calls, 0); atomic_init(&result.alive, 1);
    result.engine = engine; return result;
}
static void observe(void) {
    MadbHandle engine = create(), subscription = 0; uint64_t sum = 99;
    Context context = context_for(engine);
    STATUS(madb_fixture_observe(engine, callback, &context, &subscription, &error), MADB_OK);
    CHECK(subscription != 0 && subscription != engine);
    CHECK(atomic_load(&context.calls) == 1 && context.sequence == 1 && context.state == 0);
    STATUS(madb_fixture_checksum(subscription, NULL, 0, &sum, &error), MADB_INVALID_HANDLE);
    CHECK(sum == 0);
    STATUS(madb_fixture_request_close(engine, &error), MADB_OK);
    STATUS(madb_fixture_await_closed(engine, 5000, &error), MADB_OK);
    atomic_store(&context.alive, 0);
    STATUS(madb_fixture_await_closed(subscription, 0, &error), MADB_OK);
    STATUS(madb_fixture_release_handle(subscription, &error), MADB_OK);
    STATUS(madb_fixture_release_handle(engine, &error), MADB_OK);
    CHECK(atomic_load(&context.calls) == 1);

    engine = create(); context = context_for(engine); context.close_on_callback = 1;
    subscription = 77;
    STATUS(madb_fixture_observe(engine, callback, &context, &subscription, &error), MADB_CLOSING);
    CHECK(subscription == 0 && atomic_load(&context.calls) == 1);
    STATUS(madb_fixture_await_closed(engine, 5000, &error), MADB_OK);
    atomic_store(&context.alive, 0);
    STATUS(madb_fixture_release_handle(engine, &error), MADB_OK);
}

#ifdef MADB_LAB_TEST_SUPPORT
typedef struct Work { MadbHandle handle; int emit; MadbStatus status; uint64_t sum; } Work;
static void *perform(void *opaque) {
    Work *work = opaque; MadbError own_error;
    const uint8_t bytes[] = {1, 2, 3};
    work->status = work->emit
        ? madb_fixture_test_emit(work->handle, 7, &own_error)
        : madb_fixture_checksum(work->handle, bytes, sizeof bytes, &work->sum, &own_error);
    return NULL;
}
static MadbTestCounts snapshot(void) {
    MadbTestCounts counts;
    STATUS(madb_fixture_test_snapshot(&counts, &error), MADB_OK); return counts;
}
static void balanced(MadbTestCounts before) {
    MadbTestCounts after = snapshot();
    CHECK(after.engines_created - before.engines_created == after.engines_released - before.engines_released);
    CHECK(after.subscriptions_created - before.subscriptions_created == after.subscriptions_released - before.subscriptions_released);
    CHECK(after.active_operations == before.active_operations);
    CHECK(after.source_leases == before.source_leases);
    CHECK(after.registry_entries == before.registry_entries);
    CHECK(after.callbacks_started == after.callbacks_finished);
    printf("{\"resources\":{\"engines_created\":%" PRIu64 ",\"engines_released\":%" PRIu64 ",\"subscriptions_created\":%" PRIu64 ",\"subscriptions_released\":%" PRIu64 ",\"callbacks_created\":%" PRIu64 ",\"callbacks_released\":%" PRIu64 ",\"active_operations\":%" PRIu64 ",\"source_leases\":%" PRIu64 ",\"registry_entries\":%" PRIu64 "}}\n",
           after.engines_created - before.engines_created, after.engines_released - before.engines_released,
           after.subscriptions_created - before.subscriptions_created, after.subscriptions_released - before.subscriptions_released,
           after.callbacks_started - before.callbacks_started, after.callbacks_finished - before.callbacks_finished,
           after.active_operations, after.source_leases, after.registry_entries);
}
static void operation_close(void) {
    MadbTestCounts before = snapshot(); MadbHandle engine = create();
    STATUS(madb_fixture_test_arm(1, &error), MADB_OK);
    Work work = {engine, 0, -1, 0}; pthread_t thread;
    CHECK(pthread_create(&thread, NULL, perform, &work) == 0);
    STATUS(madb_fixture_test_wait(1, 5000, &error), MADB_OK);
    puts("{\"event\":\"operation-admitted-and-held\"}");
    CHECK(snapshot().active_operations > before.active_operations);
    STATUS(madb_fixture_request_close(engine, &error), MADB_OK);
    STATUS(madb_fixture_request_close(engine, &error), MADB_OK);
    STATUS(madb_fixture_await_closed(engine, 0, &error), MADB_TIMEOUT);
    STATUS(madb_fixture_release_handle(engine, &error), MADB_BUSY);
    puts("{\"event\":\"closing-await-timeout-release-busy\"}");
    uint64_t sum = 99;
    STATUS(madb_fixture_checksum(engine, NULL, 0, &sum, &error), MADB_CLOSING);
    CHECK(sum == 0 && snapshot().engines_released == before.engines_released);
    STATUS(madb_fixture_test_resume(1, &error), MADB_OK);
    puts("{\"event\":\"operation-resumed\"}");
    CHECK(pthread_join(thread, NULL) == 0); CHECK(work.status == MADB_OK && work.sum == 6);
    STATUS(madb_fixture_await_closed(engine, 5000, &error), MADB_OK);
    puts("{\"event\":\"operation-joined-and-close-confirmed\"}");
    CHECK(snapshot().engines_released == before.engines_released + 1);
    CHECK(snapshot().registry_entries == before.registry_entries + 1);
    STATUS(madb_fixture_release_handle(engine, &error), MADB_OK); balanced(before);
}
static void source_lease(void) {
    MadbTestCounts before = snapshot(); MadbHandle engine = create(), subscription = 0;
    Context context = context_for(engine);
    STATUS(madb_fixture_observe(engine, callback, &context, &subscription, &error), MADB_OK);
    STATUS(madb_fixture_test_arm(2, &error), MADB_OK);
    Work work = {subscription, 1, -1, 0}; pthread_t thread;
    CHECK(pthread_create(&thread, NULL, perform, &work) == 0);
    STATUS(madb_fixture_test_wait(2, 5000, &error), MADB_OK);
    puts("{\"event\":\"source-context-leased-before-bridge\"}");
    CHECK(snapshot().source_leases > before.source_leases);
    STATUS(madb_fixture_request_close(subscription, &error), MADB_OK);
    STATUS(madb_fixture_await_closed(subscription, 0, &error), MADB_TIMEOUT);
    STATUS(madb_fixture_release_handle(subscription, &error), MADB_BUSY);
    CHECK(atomic_load(&context.calls) == 1 && atomic_load(&context.alive));
    puts("{\"event\":\"stop-timeout-context-retained\"}");
    STATUS(madb_fixture_test_resume(2, &error), MADB_OK);
    CHECK(pthread_join(thread, NULL) == 0); CHECK(work.status == MADB_OK);
    STATUS(madb_fixture_await_closed(subscription, 5000, &error), MADB_OK);
    CHECK(atomic_load(&context.calls) == 2 && context.state == 7 && context.sequence == 2);
    atomic_store(&context.alive, 0);
    puts("{\"event\":\"source-joined-close-confirmed-context-released\"}");
    STATUS(madb_fixture_test_emit(subscription, 8, &error), MADB_CLOSED);
    CHECK(atomic_load(&context.calls) == 2);
    STATUS(madb_fixture_release_handle(subscription, &error), MADB_OK);
    close_release(engine); balanced(before);
}
static void registration_failure(void) {
    MadbTestCounts before = snapshot(); MadbHandle engine = create(), subscription = 77;
    Context context = context_for(engine);
    STATUS(madb_fixture_test_set_fault(1, 1, &error), MADB_OK);
    STATUS(madb_fixture_observe(engine, callback, &context, &subscription, &error), MADB_INTERNAL_FAILURE);
    CHECK(subscription == 0 && atomic_load(&context.calls) == 0); clean_error();
    atomic_store(&context.alive, 0); close_release(engine); balanced(before);
}
static void panic_boundary(void) {
    MadbTestCounts before = snapshot(); MadbHandle engine = create(); uint64_t sum = 77;
    STATUS(madb_fixture_test_set_fault(2, 1, &error), MADB_OK);
    STATUS(madb_fixture_checksum(engine, NULL, 0, &sum, &error), MADB_INTERNAL_FAILURE);
    CHECK(sum == 0); clean_error(); close_release(engine); balanced(before);
}
static void diagnostics(void) {
    MadbTestCounts before = snapshot();
    STATUS(madb_fixture_test_set_fault(3, 1, &error), MADB_OK);
    data(); lifecycle(); observe();
    CHECK(snapshot().diagnostic_failures > before.diagnostic_failures);
    STATUS(madb_fixture_test_set_fault(3, 0, &error), MADB_OK); balanced(before);
}
static void token_exhaustion(void) {
    MadbTestCounts before = snapshot();
    STATUS(madb_fixture_test_set_next_token(UINT64_MAX, &error), MADB_OK);
    MadbHandle last = create(); CHECK(last == UINT64_MAX);
    MadbHandle engine = 77;
    MadbStatus status = madb_fixture_create(&engine, &error);
    CHECK(status == MADB_RESOURCE_EXHAUSTED); CHECK(engine == 0); clean_error();
    close_release(last); balanced(before);
}
static void capacity(void) {
    MadbTestCounts before = snapshot(); MadbHandle engine = create(), subscriptions[64];
    Context contexts[64];
    for (size_t i = 0; i < 64; i++) {
        contexts[i] = context_for(engine);
        STATUS(madb_fixture_observe(engine, callback, &contexts[i], &subscriptions[i], &error), MADB_OK);
    }
    MadbHandle rejected = 77; Context extra = context_for(engine);
    STATUS(madb_fixture_observe(engine, callback, &extra, &rejected, &error), MADB_RESOURCE_EXHAUSTED);
    CHECK(rejected == 0 && atomic_load(&extra.calls) == 0);
    STATUS(madb_fixture_request_close(subscriptions[0], &error), MADB_OK);
    STATUS(madb_fixture_await_closed(subscriptions[0], 5000, &error), MADB_OK);
    STATUS(madb_fixture_observe(engine, callback, &extra, &rejected, &error), MADB_RESOURCE_EXHAUSTED);
    CHECK(rejected == 0);
    STATUS(madb_fixture_release_handle(subscriptions[0], &error), MADB_OK);
    STATUS(madb_fixture_observe(engine, callback, &extra, &subscriptions[0], &error), MADB_OK);
    STATUS(madb_fixture_request_close(engine, &error), MADB_OK);
    STATUS(madb_fixture_await_closed(engine, 5000, &error), MADB_OK);
    for (size_t i = 0; i < 64; i++) {
        atomic_store(&contexts[i].alive, 0);
        STATUS(madb_fixture_release_handle(subscriptions[i], &error), MADB_OK);
    }
    atomic_store(&extra.alive, 0);
    STATUS(madb_fixture_release_handle(engine, &error), MADB_OK);
    balanced(before);
}
#endif
int main(int argc, char **argv) {
    CHECK(argc == 4);
    Dl_info module;
    void *bootstrap_symbol = dlsym(RTLD_DEFAULT, "madb_fixture_bootstrap");
    CHECK(bootstrap_symbol != NULL && dladdr(bootstrap_symbol, &module) != 0);
    char *loaded = realpath(module.dli_fname, NULL), *installed = realpath(argv[3], NULL);
    CHECK(loaded != NULL && installed != NULL);
    if (strcmp(loaded, installed) != 0) {
        fprintf(stderr, "ArtifactMismatch: loaded %s instead of installed %s\n", loaded, installed);
        free(loaded); free(installed); return 42;
    }
    printf("{\"loaded_module\":\"%s\"}\n", loaded);
    free(loaded); free(installed);
    if (strcmp(argv[1], "abi-mismatch") == 0 || strcmp(argv[1], "profile-mismatch") == 0) {
        int expected = strcmp(argv[1], "abi-mismatch") == 0 ? 40 : 41;
        CHECK(connect(argv[2]) == expected); puts("{\"result\":\"passed\"}"); return 0;
    }
    int result = connect(argv[2]); if (result) return result;
    if (strcmp(argv[1], "data") == 0) data();
    else if (strcmp(argv[1], "bootstrap") == 0) bootstrap();
    else if (strcmp(argv[1], "lifecycle") == 0) lifecycle();
    else if (strcmp(argv[1], "observe") == 0) observe();
#ifdef MADB_LAB_TEST_SUPPORT
    else if (strcmp(argv[1], "operation-close") == 0) operation_close();
    else if (strcmp(argv[1], "source-lease") == 0) source_lease();
    else if (strcmp(argv[1], "registration-failure") == 0) registration_failure();
    else if (strcmp(argv[1], "panic") == 0) panic_boundary();
    else if (strcmp(argv[1], "diagnostics") == 0) diagnostics();
    else if (strcmp(argv[1], "token-exhaustion") == 0) token_exhaustion();
    else if (strcmp(argv[1], "capacity") == 0) capacity();
#endif
    else CHECK(0);
    puts("{\"result\":\"passed\"}"); return 0;
}
