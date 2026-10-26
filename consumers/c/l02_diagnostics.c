/* Independent L02 consumer. Only installed public candidate declarations. */
#define _GNU_SOURCE 1
#include "madb_rust_client.h"
#ifdef MADB_LAB_TEST_SUPPORT
#include "test-support.h"
#endif
#include <dlfcn.h>
#include <inttypes.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#define CHECK(x) do { if (!(x)) { fprintf(stderr, "L02 assertion:%d:%s\n", __LINE__, #x); exit(2); } } while (0)
#define STATUS(call, expected) do { MadbStatus got_ = (call); CHECK(got_ == (expected)); } while (0)
_Static_assert(sizeof(MadbCheckedEngineCreateResult) == 24, "checked result size");
_Static_assert(_Alignof(MadbCheckedEngineCreateResult) == 8, "checked result alignment");
_Static_assert(offsetof(MadbCheckedEngineCreateResult, kind) == 0, "checked kind offset");
_Static_assert(offsetof(MadbCheckedEngineCreateResult, native_status) == 4, "checked status offset");
_Static_assert(offsetof(MadbCheckedEngineCreateResult, native_error) == 8, "checked error offset");
_Static_assert(offsetof(MadbCheckedEngineCreateResult, handle) == 16, "checked handle offset");

#ifdef MADB_LAB_STUB
/* Limited helper control-flow evidence, never a native SDK substitute. */
static uint8_t stub_identity[64];
static unsigned stub_mode, bootstrap_calls, create_calls;
MadbStatus madb_fixture_bootstrap(uint32_t version, uint8_t *out, uint64_t capacity) {
    CHECK(version == 1 && capacity == 64 && out != NULL); bootstrap_calls++;
    memcpy(out, stub_identity, 64);
    if (stub_mode == 1) return MADB_UNSUPPORTED;
    if (stub_mode == 2 || stub_mode == 5) out[0] ^= 1;
    if (stub_mode == 3 || stub_mode == 5) out[32] ^= 1;
    return MADB_OK;
}
MadbStatus madb_fixture_create(MadbHandle *out, MadbError *error) {
    create_calls++; *out = 0; *error = (MadbError){0, 0};
    if (stub_mode == 4) { *error = (MadbError){7, -9}; return MADB_RESOURCE_EXHAUSTED; }
    *out = 101; return MADB_OK;
}
int main(int argc, char **argv) {
    CHECK(argc == 3 && strlen(argv[2]) == 128);
    stub_mode = (unsigned)strtoul(argv[1], NULL, 10); CHECK(stub_mode <= 5);
    for (size_t i = 0; i < 64; i++) {
        unsigned value; CHECK(sscanf(argv[2] + 2 * i, "%2x", &value) == 1); stub_identity[i] = (uint8_t)value;
    }
    MadbCheckedEngineCreateResult result = madb_engine_create_checked();
    unsigned expected = stub_mode == 5 ? 2 : stub_mode;
    CHECK(result.kind == expected && bootstrap_calls == 1);
    CHECK(create_calls == (stub_mode == 0 || stub_mode == 4 ? 1u : 0u));
    CHECK(result.native_status == (stub_mode == 1 ? MADB_UNSUPPORTED : stub_mode == 4 ? MADB_RESOURCE_EXHAUSTED : MADB_OK));
    CHECK(result.handle == (stub_mode == 0 ? 101u : 0u));
    CHECK(result.native_error.domain == (stub_mode == 4 ? 7 : 0));
    CHECK(result.native_error.code == (stub_mode == 4 ? -9 : 0));
    printf("{\"scope\":\"stub-only\",\"mode\":%u,\"kind\":%u,\"bootstrap_calls\":%u,\"create_calls\":%u,\"result\":\"passed\"}\n",
           stub_mode, (unsigned)result.kind, bootstrap_calls, create_calls);
    return 0;
}
#else
static void zero_error(MadbError error) { CHECK(error.domain == 0 && error.code == 0); }
static MadbHandle checked_create(void) {
    MadbCheckedEngineCreateResult result = madb_engine_create_checked();
    CHECK(result.kind == MADB_CHECKED_ENGINE_OK && result.native_status == MADB_OK && result.handle != 0);
    zero_error(result.native_error); return result.handle;
}
static void release_engine(MadbHandle engine) {
    MadbError error;
    STATUS(madb_fixture_request_close(engine, &error), MADB_OK); zero_error(error);
    STATUS(madb_fixture_await_closed(engine, 5000, &error), MADB_OK); zero_error(error);
    STATUS(madb_fixture_release_handle(engine, &error), MADB_OK); zero_error(error);
}
static void checksum(MadbHandle engine) {
    const uint8_t bytes[] = {0, 1, 127, 128, 255}; uint64_t sum = 999; MadbError error;
    STATUS(madb_fixture_checksum(engine, bytes, sizeof bytes, &sum, &error), MADB_OK);
    CHECK(sum == 511); zero_error(error);
}
typedef struct Context { atomic_uint calls; atomic_bool alive; MadbHandle self_close; } Context;
static void callback(void *opaque, uint64_t sequence, uint32_t state) {
    Context *context = opaque; CHECK(atomic_load(&context->alive));
    unsigned prior = atomic_fetch_add(&context->calls, 1);
    CHECK(sequence == prior + 1 && state == (prior == 0 ? 0u : 7u));
    if (context->self_close) {
        MadbError error;
        STATUS(madb_fixture_request_close(context->self_close, &error), MADB_OK); zero_error(error);
        STATUS(madb_fixture_await_closed(context->self_close, 0, &error), MADB_WOULD_DEADLOCK); zero_error(error);
    }
}
static void close_subscription(MadbHandle engine, MadbHandle subscription, Context *context) {
    MadbError error;
    STATUS(madb_fixture_request_close(engine, &error), MADB_OK); zero_error(error);
    STATUS(madb_fixture_await_closed(engine, 5000, &error), MADB_OK); zero_error(error);
    atomic_store(&context->alive, 0);
    STATUS(madb_fixture_await_closed(subscription, 0, &error), MADB_OK); zero_error(error);
    STATUS(madb_fixture_release_handle(subscription, &error), MADB_OK); zero_error(error);
    STATUS(madb_fixture_release_handle(engine, &error), MADB_OK); zero_error(error);
}
typedef struct ResourcePair { MadbHandle engine, subscription; } ResourcePair;
static ResourcePair ordinary(void) {
    ResourcePair pair = {checked_create(), 0}; MadbError error; uint64_t sum = 999;
    checksum(pair.engine);
    STATUS(madb_fixture_checksum(0, NULL, 0, &sum, &error), MADB_INVALID_HANDLE);
    CHECK(sum == 0); zero_error(error);
    Context context = {0}; atomic_init(&context.calls, 0); atomic_init(&context.alive, 1);
    STATUS(madb_fixture_observe(pair.engine, callback, &context, &pair.subscription, &error), MADB_OK);
    zero_error(error); CHECK(pair.subscription != 0 && pair.subscription != pair.engine && atomic_load(&context.calls) == 1);
    close_subscription(pair.engine, pair.subscription, &context); CHECK(atomic_load(&context.calls) == 1);
    printf("{\"ordinary\":true,\"engine\":%" PRIu64 ",\"subscription\":%" PRIu64 ",\"callbacks\":1,\"sum\":511,\"close\":\"confirmed\"}\n", pair.engine, pair.subscription);
    return pair;
}
static void self_wait(void) {
    MadbHandle engine = checked_create(), subscription = 99; MadbError error;
    Context context = {0}; atomic_init(&context.calls, 0); atomic_init(&context.alive, 1); context.self_close = engine;
    STATUS(madb_fixture_observe(engine, callback, &context, &subscription, &error), MADB_CLOSING);
    zero_error(error); CHECK(subscription == 0 && atomic_load(&context.calls) == 1);
    STATUS(madb_fixture_await_closed(engine, 5000, &error), MADB_OK); zero_error(error);
    atomic_store(&context.alive, 0);
    STATUS(madb_fixture_release_handle(engine, &error), MADB_OK); zero_error(error);
    puts("{\"self_wait\":\"WOULD_DEADLOCK\",\"observe\":\"CLOSING\",\"close\":\"confirmed\"}");
}
static void loaded_module(const char *expected) {
    Dl_info info; void *symbol = dlsym(RTLD_DEFAULT, "madb_fixture_bootstrap");
    CHECK(symbol != NULL && dladdr(symbol, &info));
    char *actual = realpath(info.dli_fname, NULL), *fixed = realpath(expected, NULL);
    CHECK(actual != NULL && fixed != NULL && strcmp(actual, fixed) == 0);
    printf("{\"loaded_module\":\"%s\",\"pid\":%d}\n", actual, (int)getpid()); free(actual); free(fixed);
}
static void identity(void) {
    uint8_t bytes[64]; STATUS(madb_fixture_bootstrap(1, bytes, 64), MADB_OK);
    fputs("{\"actual_identity\":\"", stdout);
    for (size_t i = 0; i < 64; i++) { printf("%02x", bytes[i]); }
    puts("\"}");
}

#if defined(MADB_DIAGNOSTICS) && !defined(MADB_LAB_MISMATCH_ONLY)
_Static_assert(sizeof(MadbDiagnosticEvent) == 64 && _Alignof(MadbDiagnosticEvent) == 8, "event layout");
_Static_assert(sizeof(MadbDiagnosticStats) == 40 && _Alignof(MadbDiagnosticStats) == 8, "stats layout");
#define OFFSET(type, field, offset) _Static_assert(offsetof(type, field) == offset, "diagnostic field offset")
OFFSET(MadbDiagnosticEvent, record_id, 0); OFFSET(MadbDiagnosticEvent, symbol_id, 8);
OFFSET(MadbDiagnosticEvent, phase, 16); OFFSET(MadbDiagnosticEvent, resource_id, 24);
OFFSET(MadbDiagnosticEvent, related_resource_id, 32); OFFSET(MadbDiagnosticEvent, duration_ns, 40);
OFFSET(MadbDiagnosticEvent, status, 48); OFFSET(MadbDiagnosticEvent, status_present, 56);
OFFSET(MadbDiagnosticStats, completed_calls, 0); OFFSET(MadbDiagnosticStats, failed_calls, 8);
OFFSET(MadbDiagnosticStats, completed_callbacks, 16); OFFSET(MadbDiagnosticStats, dropped_events, 24);
OFFSET(MadbDiagnosticStats, capture_enabled, 32);
static void all_zero(const void *pointer, size_t size) {
    const unsigned char *bytes = pointer; for (size_t i = 0; i < size; i++) CHECK(bytes[i] == 0);
}
static void configure(uint32_t enabled) {
    MadbError error = {17, -2}; STATUS(madb_fixture_diagnostics_configure(enabled, &error), MADB_OK); zero_error(error);
}
static uint64_t pull(MadbDiagnosticEvent *event, MadbDiagnosticStats *stats) {
    uint64_t present = 99; MadbError error = {17, -2}; memset(event, 0xaa, sizeof *event); memset(stats, 0xaa, sizeof *stats);
    STATUS(madb_fixture_diagnostics_drain(event, &present, stats, &error), MADB_OK); zero_error(error);
    CHECK(present <= 1); if (!present) all_zero(event, sizeof *event); return present;
}
static void print_stats(MadbDiagnosticStats stats, unsigned events) {
    printf("{\"events\":%u,\"completed_calls\":%" PRIu64 ",\"failed_calls\":%" PRIu64 ",\"completed_callbacks\":%" PRIu64 ",\"dropped_events\":%" PRIu64 ",\"capture_enabled\":%" PRIu64 "}\n",
           events, stats.completed_calls, stats.failed_calls, stats.completed_callbacks, stats.dropped_events, stats.capture_enabled);
}
static void event_row(MadbDiagnosticEvent event) {
    printf("{\"record_id\":%" PRIu64 ",\"symbol_id\":%" PRIu64 ",\"phase\":%" PRIu64 ",\"resource_id\":%" PRIu64 ",\"related_resource_id\":%" PRIu64 ",\"duration_ns\":%" PRIu64 ",\"status\":%" PRId64 ",\"status_present\":%" PRIu64 "}\n",
           event.record_id, event.symbol_id, event.phase, event.resource_id, event.related_resource_id, event.duration_ns, event.status, event.status_present);
}
static void off_or_events(int enabled) {
    MadbDiagnosticEvent event; MadbDiagnosticStats stats;
    CHECK(pull(&event, &stats) == 0); all_zero(&stats, sizeof stats);
    if (enabled) configure(1);
    ResourcePair pair = ordinary();
    const uint64_t symbols[] = {1, 2, 3, 3, 8, 7, 4, 5, 5, 6, 6};
    const uint64_t resources[] = {0, pair.engine, pair.engine, 0, pair.subscription, pair.engine,
                                 pair.engine, pair.engine, pair.subscription, pair.subscription, pair.engine};
    unsigned count = 0;
    for (; count < 65; count++) {
        if (!pull(&event, &stats)) break;
        CHECK(enabled && count < 11 && event.record_id == count + 1 && event.symbol_id == symbols[count]);
        CHECK(event.resource_id == resources[count]);
        CHECK(event.related_resource_id == (count == 4 ? pair.engine : count == 5 ? pair.subscription : 0));
        CHECK(event.phase == (count == 4 ? 2u : 1u) && event.status_present == (count == 4 ? 0u : 1u));
        CHECK(event.status == (count == 3 ? MADB_INVALID_HANDLE : 0)); event_row(event);
    }
    CHECK(count == (enabled ? 11u : 0u));
    CHECK(stats.completed_calls == 10 && stats.failed_calls == 1 && stats.completed_callbacks == 1 && stats.dropped_events == 0);
    CHECK(stats.capture_enabled == (uint64_t)enabled); print_stats(stats, count);
}
static void full(void) {
    MadbHandle engine = checked_create(), subscription = 0; configure(1);
    for (unsigned i = 0; i < 80; i++) checksum(engine);
    Context context = {0}; atomic_init(&context.calls, 0); atomic_init(&context.alive, 1); MadbError error;
    STATUS(madb_fixture_observe(engine, callback, &context, &subscription, &error), MADB_OK);
    CHECK(atomic_load(&context.calls) == 1); close_subscription(engine, subscription, &context);
    MadbDiagnosticEvent event; MadbDiagnosticStats stats; unsigned count = 0;
    for (; count < 65; count++) {
        if (!pull(&event, &stats)) break;
        CHECK(event.record_id == count + 1 && event.symbol_id == 3 && event.phase == 1 && event.resource_id == engine);
        CHECK(event.related_resource_id == 0 && event.status == 0 && event.status_present == 1); event_row(event);
    }
    CHECK(count == 64 && stats.dropped_events == 23 && stats.completed_calls == 88 && stats.completed_callbacks == 1 && stats.failed_calls == 0);
    print_stats(stats, count);
}
static void toggle(void) {
    uint8_t bytes[64]; MadbDiagnosticEvent event; MadbDiagnosticStats stats;
    configure(1); STATUS(madb_fixture_bootstrap(1, bytes, 64), MADB_OK);
    configure(0); configure(0); STATUS(madb_fixture_bootstrap(1, bytes, 64), MADB_OK);
    CHECK(pull(&event, &stats) == 1 && event.record_id == 1 && stats.capture_enabled == 0); event_row(event);
    CHECK(pull(&event, &stats) == 0 && stats.completed_calls == 2 && stats.dropped_events == 0);
    configure(1); configure(1); STATUS(madb_fixture_bootstrap(1, bytes, 64), MADB_OK);
    configure(0); CHECK(pull(&event, &stats) == 1 && event.record_id == 2); event_row(event);
    CHECK(pull(&event, &stats) == 0 && stats.completed_calls == 3 && stats.dropped_events == 0); print_stats(stats, 2);
}
static void rejections(void) {
    MadbError error = {17, -2}; MadbDiagnosticEvent event; MadbDiagnosticStats stats;
    STATUS(madb_fixture_diagnostics_configure(2, &error), MADB_INVALID_ARGUMENT); zero_error(error);
    STATUS(madb_fixture_diagnostics_configure(1, NULL), MADB_INVALID_ARGUMENT);
    _Alignas(8) unsigned char bad_error[16]; memset(bad_error, 0xaa, sizeof bad_error);
    STATUS(madb_fixture_diagnostics_configure(1, (MadbError *)(bad_error + 1)), MADB_INVALID_ARGUMENT);
    for (size_t i = 0; i < sizeof bad_error; i++) CHECK(bad_error[i] == 0xaa);
    CHECK(pull(&event, &stats) == 0); all_zero(&stats, sizeof stats);
    configure(1); uint8_t identity_bytes[64]; STATUS(madb_fixture_bootstrap(1, identity_bytes, 64), MADB_OK);
    const size_t sizes[] = {sizeof event, sizeof(uint64_t), sizeof stats, sizeof error};
    for (unsigned misaligned = 0; misaligned < 2; misaligned++) for (unsigned selected = 0; selected < 4; selected++) {
        _Alignas(8) unsigned char buffers[4][80]; memset(buffers, 0xaa, sizeof buffers);
        void *out[4] = {buffers[0], buffers[1], buffers[2], buffers[3]};
        out[selected] = misaligned ? buffers[selected] + 1 : NULL;
        STATUS(madb_fixture_diagnostics_drain(out[0], out[1], out[2], out[3]), MADB_INVALID_ARGUMENT);
        for (unsigned item = 0; item < 4; item++) {
            if (item != selected) all_zero(buffers[item], sizes[item]);
            size_t start = item == selected ? 0 : sizes[item];
            for (size_t n = start; n < 80; n++) CHECK(buffers[item][n] == 0xaa);
        }
    }
    CHECK(pull(&event, &stats) == 1 && event.record_id == 1 && event.symbol_id == 1);
    CHECK(event.phase == 1 && event.resource_id == 0 && event.related_resource_id == 0 && event.status == 0 && event.status_present == 1);
    event_row(event);
    CHECK(pull(&event, &stats) == 0 && stats.completed_calls == 1 && stats.failed_calls == 0 && stats.completed_callbacks == 0);
    CHECK(stats.dropped_events == 0 && stats.capture_enabled == 1); print_stats(stats, 1);
}
typedef struct Parallel { MadbHandle engine; unsigned iterations, controller_events; uint64_t last_record; atomic_uint completed, busy; } Parallel;
static void *work(void *opaque) {
    Parallel *work = opaque;
    for (unsigned i = 0; i < work->iterations; i++) { checksum(work->engine); atomic_fetch_add(&work->completed, 1); }
    return NULL;
}
static void *controls(void *opaque) {
    Parallel *work = opaque; uint64_t last_id = 0;
    for (unsigned i = 0; i < work->iterations; i++) {
        MadbError error = {17, -2}; MadbStatus status = madb_fixture_diagnostics_configure(i % 2, &error);
        CHECK(status == MADB_OK || status == MADB_BUSY); zero_error(error);
        MadbDiagnosticEvent event; MadbDiagnosticStats stats; uint64_t present = 99;
        memset(&event, 0xaa, sizeof event); memset(&stats, 0xaa, sizeof stats); error = (MadbError){17, -2};
        status = madb_fixture_diagnostics_drain(&event, &present, &stats, &error); zero_error(error);
        CHECK(status == MADB_OK || status == MADB_BUSY);
        if (status == MADB_BUSY) { all_zero(&event, sizeof event); all_zero(&stats, sizeof stats); CHECK(present == 0); atomic_fetch_add(&work->busy, 1); }
        else {
            CHECK(present <= 1 && stats.capture_enabled <= 1);
            if (present) {
                CHECK(event.record_id > last_id && event.symbol_id == 3 && event.resource_id == work->engine);
                CHECK(event.phase == 1 && event.related_resource_id == 0 && event.status == 0 && event.status_present == 1);
                last_id = event.record_id; work->controller_events++; event_row(event);
            }
            else all_zero(&event, sizeof event);
        }
    }
    work->last_record = last_id;
    return NULL;
}
static void concurrent(void) {
    Parallel task = {0}; task.engine = checked_create(); task.iterations = 1000;
    atomic_init(&task.completed, 0); atomic_init(&task.busy, 0); configure(1);
    pthread_t workers[4], controller;
    CHECK(pthread_create(&controller, NULL, controls, &task) == 0);
    for (unsigned i = 0; i < 4; i++) CHECK(pthread_create(&workers[i], NULL, work, &task) == 0);
    for (unsigned i = 0; i < 4; i++) CHECK(pthread_join(workers[i], NULL) == 0);
    CHECK(pthread_join(controller, NULL) == 0 && atomic_load(&task.completed) == 4000);
    configure(0); release_engine(task.engine);
    MadbDiagnosticEvent event; MadbDiagnosticStats stats; unsigned count = 0;
    while (count < 65 && pull(&event, &stats)) {
        CHECK(event.record_id > task.last_record && event.symbol_id == 3 && event.resource_id == task.engine);
        CHECK(event.phase == 1 && event.related_resource_id == 0 && event.status == 0 && event.status_present == 1);
        task.last_record = event.record_id; count++; event_row(event);
    }
    CHECK(count <= 64 && stats.completed_calls == 4005 && stats.failed_calls == 0 && stats.completed_callbacks == 0 && stats.capture_enabled == 0);
    printf("{\"concurrent_work\":4000,\"engine\":%" PRIu64 ",\"controller_events\":%u,\"busy_observed\":%u}\n", task.engine, task.controller_events, atomic_load(&task.busy)); print_stats(stats, count);
}
typedef struct Exporter { pthread_mutex_t mutex; pthread_cond_t condition; int entered, release; MadbDiagnosticEvent value; } Exporter;
static void *blocked_exporter(void *opaque) {
    Exporter *exporter = opaque; CHECK(pthread_mutex_lock(&exporter->mutex) == 0);
    CHECK(exporter->value.record_id == 1); exporter->entered = 1;
    CHECK(pthread_cond_signal(&exporter->condition) == 0);
    while (!exporter->release) CHECK(pthread_cond_wait(&exporter->condition, &exporter->mutex) == 0);
    CHECK(pthread_mutex_unlock(&exporter->mutex) == 0); return NULL; /* consumer deliberately drops/fails export */
}
static void exporter(void) {
    configure(1); uint8_t bytes[64]; STATUS(madb_fixture_bootstrap(1, bytes, 64), MADB_OK);
    Exporter sink = {PTHREAD_MUTEX_INITIALIZER, PTHREAD_COND_INITIALIZER, 0, 0, {0}};
    MadbDiagnosticStats stats; CHECK(pull(&sink.value, &stats) == 1); pthread_t thread;
    CHECK(pthread_create(&thread, NULL, blocked_exporter, &sink) == 0);
    CHECK(pthread_mutex_lock(&sink.mutex) == 0);
    while (!sink.entered) CHECK(pthread_cond_wait(&sink.condition, &sink.mutex) == 0);
    CHECK(pthread_mutex_unlock(&sink.mutex) == 0);
    ordinary(); /* returns and drains owned resources while the consumer exporter is blocked */
    CHECK(pthread_mutex_lock(&sink.mutex) == 0); CHECK(!sink.release); sink.release = 1;
    CHECK(pthread_cond_signal(&sink.condition) == 0); CHECK(pthread_mutex_unlock(&sink.mutex) == 0);
    CHECK(pthread_join(thread, NULL) == 0); CHECK(pthread_cond_destroy(&sink.condition) == 0); CHECK(pthread_mutex_destroy(&sink.mutex) == 0);
    puts("{\"exporter\":\"consumer-blocked-dropped\",\"ordinary_completed_before_exporter_release\":true}");
}
#endif

#ifdef MADB_LAB_TEST_SUPPORT
static MadbTestCounts snapshot(void) {
    MadbTestCounts counts; MadbError error; STATUS(madb_fixture_test_snapshot(&counts, &error), MADB_OK); zero_error(error); return counts;
}
static void balanced(MadbTestCounts before) {
    MadbTestCounts after = snapshot();
    CHECK(after.engines_created - before.engines_created == after.engines_released - before.engines_released);
    CHECK(after.subscriptions_created - before.subscriptions_created == after.subscriptions_released - before.subscriptions_released);
    CHECK(after.registry_entries == before.registry_entries && after.active_operations == before.active_operations && after.source_leases == before.source_leases);
    CHECK(after.callbacks_started == after.callbacks_finished);
    puts("{\"resource_balance\":true,\"context_released_after_drain\":true}");
}
typedef struct HeldWork { MadbHandle handle; int emit; MadbStatus status; uint64_t sum; } HeldWork;
static void *held_work(void *opaque) {
    HeldWork *work = opaque; MadbError error; const uint8_t bytes[] = {1, 2, 3};
    work->status = work->emit ? madb_fixture_test_emit(work->handle, 7, &error)
        : madb_fixture_checksum(work->handle, bytes, 3, &work->sum, &error);
    zero_error(error); return NULL;
}
static void held_close(int source) {
    MadbTestCounts before = snapshot(); MadbHandle engine = checked_create(), subscription = 0; MadbError error;
    Context context = {0}; atomic_init(&context.calls, 0); atomic_init(&context.alive, 1);
    if (source) STATUS(madb_fixture_observe(engine, callback, &context, &subscription, &error), MADB_OK);
    uint32_t gate = source ? 2 : 1; MadbHandle handle = source ? subscription : engine;
    STATUS(madb_fixture_test_arm(gate, &error), MADB_OK);
    HeldWork task = {handle, source, -1, 0}; pthread_t thread; CHECK(pthread_create(&thread, NULL, held_work, &task) == 0);
    STATUS(madb_fixture_test_wait(gate, 5000, &error), MADB_OK);
    MadbTestCounts held = snapshot(); CHECK(source ? held.source_leases > before.source_leases : held.active_operations > before.active_operations);
    STATUS(madb_fixture_request_close(handle, &error), MADB_OK);
    STATUS(madb_fixture_await_closed(handle, 0, &error), MADB_TIMEOUT);
    STATUS(madb_fixture_release_handle(handle, &error), MADB_BUSY);
    CHECK(atomic_load(&context.alive));
    printf("{\"held\":\"%s\",\"await\":\"TIMEOUT\",\"release\":\"BUSY\"}\n", source ? "source-lease" : "operation");
    STATUS(madb_fixture_test_resume(gate, &error), MADB_OK); CHECK(pthread_join(thread, NULL) == 0 && task.status == MADB_OK);
    STATUS(madb_fixture_await_closed(handle, 5000, &error), MADB_OK);
    if (source) {
        CHECK(atomic_load(&context.calls) == 2); atomic_store(&context.alive, 0);
        STATUS(madb_fixture_test_emit(subscription, 8, &error), MADB_CLOSED); CHECK(atomic_load(&context.calls) == 2);
    } else CHECK(task.sum == 6);
    STATUS(madb_fixture_release_handle(handle, &error), MADB_OK); if (source) release_engine(engine);
    balanced(before);
}
static void exhaustion(void) {
    MadbError error; MadbTestCounts before = snapshot();
    STATUS(madb_fixture_test_set_next_token(UINT64_MAX, &error), MADB_OK);
    MadbHandle last = checked_create(); CHECK(last == UINT64_MAX);
    MadbCheckedEngineCreateResult result = madb_engine_create_checked();
    CHECK(result.kind == MADB_CHECKED_ENGINE_CREATE_FAILED && result.native_status == MADB_RESOURCE_EXHAUSTED && result.handle == 0);
    zero_error(result.native_error); release_engine(last); balanced(before);
    puts("{\"checked_kind\":4,\"native_failure\":\"RESOURCE_EXHAUSTED\"}");
}
static void fault_isolation(void) {
    MadbTestCounts before = snapshot(); MadbError error;
    STATUS(madb_fixture_test_set_fault(3, 1, &error), MADB_OK);
    ordinary();
    CHECK(snapshot().diagnostic_failures > before.diagnostic_failures);
    STATUS(madb_fixture_test_set_fault(3, 0, &error), MADB_OK); balanced(before);
    puts("{\"test_fault\":3,\"ordinary_semantics_unchanged\":true}");
}
static void mismatch(unsigned kind) {
    MadbTestCounts before = snapshot(); MadbCheckedEngineCreateResult result = madb_engine_create_checked();
    CHECK((kind == 2 || kind == 3) && result.kind == kind && result.native_status == MADB_OK && result.handle == 0); zero_error(result.native_error);
    MadbTestCounts after = snapshot(); CHECK(memcmp(&before, &after, sizeof before) == 0);
    printf("{\"checked_kind\":%u,\"created_delta\":0,\"native_status\":0}\n", kind);
}
#endif
static void timing(const char *mode) {
    MadbHandle engine = checked_create();
    for (unsigned i = 0; i < 100; i++) checksum(engine);
#if defined(MADB_DIAGNOSTICS) && !defined(MADB_LAB_MISMATCH_ONLY)
    configure(strcmp(mode, "timing-off") != 0);
    if (strcmp(mode, "timing-full") == 0) for (unsigned i = 0; i < 64; i++) checksum(engine);
#else
    CHECK(strcmp(mode, "timing-off") == 0);
#endif
    for (unsigned sample = 0; sample < 5; sample++) {
        uint64_t duration = 0;
        for (unsigned batch = 0; batch < 25; batch++) {
#if defined(MADB_DIAGNOSTICS) && !defined(MADB_LAB_MISMATCH_ONLY)
            if (strcmp(mode, "timing-on") == 0) {
                MadbDiagnosticEvent event; MadbDiagnosticStats stats; unsigned count = 0;
                while (count < 65 && pull(&event, &stats)) count++; CHECK(count <= 64);
            }
#endif
            struct timespec start, end; CHECK(clock_gettime(CLOCK_MONOTONIC, &start) == 0);
            for (unsigned i = 0; i < 32; i++) checksum(engine);
            CHECK(clock_gettime(CLOCK_MONOTONIC, &end) == 0);
            duration += (uint64_t)(end.tv_sec - start.tv_sec) * UINT64_C(1000000000) + (uint64_t)end.tv_nsec - (uint64_t)start.tv_nsec;
        }
        printf("{\"sample\":%u,\"iterations\":800,\"batches\":25,\"duration_ns\":%" PRIu64 "}\n", sample, duration);
    }
    release_engine(engine);
}
int main(int argc, char **argv) {
    CHECK(argc == 3 || argc == 4); loaded_module(argv[2]);
    const char *mode = argv[1];
#ifdef MADB_LAB_MISMATCH_ONLY
    /* Wrong-library probes must reach bootstrap without requiring optional
     * diagnostics symbols from a deliberately mismatched default image. */
    CHECK(strcmp(mode, "mismatch") == 0);
#endif
    if (strcmp(mode, "ordinary") == 0) ordinary();
    else if (strcmp(mode, "self-wait") == 0) {
#if defined(MADB_DIAGNOSTICS) && !defined(MADB_LAB_MISMATCH_ONLY)
        CHECK(argc == 4); unsigned capture = (unsigned)strtoul(argv[3], NULL, 10); CHECK(capture <= 2); configure(capture != 0);
        if (capture == 2) { MadbHandle filler = checked_create(); for (unsigned i = 0; i < 80; i++) checksum(filler); release_engine(filler); }
#endif
        self_wait();
    }
    else if (strncmp(mode, "timing-", 7) == 0) timing(mode);
#if defined(MADB_DIAGNOSTICS) && !defined(MADB_LAB_MISMATCH_ONLY)
    else if (strcmp(mode, "off") == 0) off_or_events(0);
    else if (strcmp(mode, "events") == 0) off_or_events(1);
    else if (strcmp(mode, "full") == 0) full();
    else if (strcmp(mode, "toggle") == 0) toggle();
    else if (strcmp(mode, "rejections") == 0) rejections();
    else if (strcmp(mode, "concurrent") == 0) concurrent();
    else if (strcmp(mode, "exporter") == 0) exporter();
    else if (strcmp(mode, "instance") == 0) { off_or_events(1); }
#endif
#ifdef MADB_LAB_TEST_SUPPORT
    else if (strcmp(mode, "operation-close") == 0 || strcmp(mode, "source-lease") == 0 || strcmp(mode, "fault-isolation") == 0) {
#if defined(MADB_DIAGNOSTICS) && !defined(MADB_LAB_MISMATCH_ONLY)
        CHECK(argc == 4); unsigned capture = (unsigned)strtoul(argv[3], NULL, 10); CHECK(capture <= 2); configure(capture != 0);
        if (capture == 2) { MadbHandle filler = checked_create(); for (unsigned i = 0; i < 80; i++) checksum(filler); release_engine(filler); }
#endif
        if (strcmp(mode, "fault-isolation") == 0) fault_isolation();
        else held_close(strcmp(mode, "source-lease") == 0);
    }
    else if (strcmp(mode, "exhaustion") == 0) exhaustion();
    else if (strcmp(mode, "mismatch") == 0) { CHECK(argc == 4); mismatch((unsigned)strtoul(argv[3], NULL, 10)); }
#endif
    else CHECK(0);
    identity(); puts("{\"result\":\"passed\"}"); return 0;
}
#endif
