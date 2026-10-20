#include <siecs.h>

#ifndef NDEBUG
#error "Siecs benchmark must be built in release mode"
#endif

#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#ifndef SIECS_BENCH_VERSION
#define SIECS_BENCH_VERSION "6aa755f"
#endif

ECS_COMPONENT(Position, {
    double x;
    double y;
});

ECS_COMPONENT(Velocity, {
    double x;
    double y;
});

typedef struct {
    const char *workload;
    uint32_t entities;
    uint32_t iterations;
    uint32_t samples;
    uint32_t warmup;
} Args;

static void fail(const char *message) {
    fprintf(stderr, "error: %s\n", message);
    exit(2);
}

static uint32_t parse_integer(const char *flag, const char *value, bool allow_zero) {
    char *end = NULL;
    const unsigned long long parsed = strtoull(value, &end, 10);
    if (*value == '\0' || *end != '\0' || parsed > UINT32_MAX || (!allow_zero && parsed == 0)) {
        fprintf(stderr, "error: invalid value for %s\n", flag);
        exit(2);
    }
    return (uint32_t)parsed;
}

static Args parse_args(int argc, char **argv) {
    Args args = { 0 };
    for (int i = 1; i < argc; ++i) {
        if (i + 1 >= argc) {
            fail("missing argument value");
        }
        const char *flag = argv[i];
        const char *value = argv[++i];
        if (strcmp(flag, "--workload") == 0) {
            args.workload = value;
        } else if (strcmp(flag, "--entities") == 0) {
            args.entities = parse_integer(flag, value, false);
        } else if (strcmp(flag, "--iterations") == 0) {
            args.iterations = parse_integer(flag, value, false);
        } else if (strcmp(flag, "--samples") == 0) {
            args.samples = parse_integer(flag, value, false);
        } else if (strcmp(flag, "--warmup") == 0) {
            args.warmup = parse_integer(flag, value, true);
        } else {
            fail("unknown argument");
        }
    }
    if (args.workload == NULL || args.entities == 0 || args.iterations == 0 || args.samples == 0) {
        fail("workload, entities, iterations and samples are required");
    }
    return args;
}

static uint64_t now_ns(void) {
    struct timespec value;
    if (clock_gettime(CLOCK_MONOTONIC, &value) != 0) {
        fail("clock_gettime failed");
    }
    return (uint64_t)value.tv_sec * UINT64_C(1000000000) + (uint64_t)value.tv_nsec;
}

static void register_components(void) {
    ECS_COMPONENT_REGISTER(Position);
    ECS_COMPONENT_REGISTER(Velocity);
}

static void entity_cycle_once(ecs_entity_t *ids, uint32_t count) {
    for (uint32_t i = 0; i < count; ++i) {
        const ecs_entity_t entity = ecs_new();
        ecs_set(entity, Position, { 1.0, 2.0 });
        ids[i] = entity;
    }
    for (uint32_t i = 0; i < count; ++i) {
        ecs_kill(ids[i]);
    }
}

static void add_remove_once(const ecs_entity_t *ids, uint32_t count) {
    for (uint32_t i = 0; i < count; ++i) {
        ecs_set(ids[i], Velocity, { 0.5, -0.25 });
    }
    for (uint32_t i = 0; i < count; ++i) {
        ecs_remove(ids[i], Velocity);
    }
}

static void iterate_once(ecs_query_id_t query) {
    ecs_iter_t it = ecs_query_iter(query);
    while (ecs_iter_next(&it)) {
        Position *positions = ecs_field(&it, 0);
        const Velocity *velocities = ecs_field(&it, 1);
        for (uint32_t i = 0; i < it.count; ++i) {
            positions[i].x += velocities[i].x;
            positions[i].y += velocities[i].y;
        }
    }
}

static double checksum_positions(void) {
    const ecs_query_id_t query = ecs_query({ .components = { ecs_in(Position) } });
    double checksum = 0.0;
    ecs_iter_t it = ecs_query_iter(query);
    while (ecs_iter_next(&it)) {
        const Position *positions = ecs_field(&it, 0);
        for (uint32_t i = 0; i < it.count; ++i) {
            checksum += positions[i].x + positions[i].y;
        }
    }
    ecs_query_fini(query);
    return checksum;
}

static uint64_t run_sample(const Args *args, double *checksum) {
    ecs_init();
    register_components();
    uint64_t start;
    uint64_t end;

    if (strcmp(args->workload, "entity_cycle") == 0) {
        ecs_entity_t *ids = malloc((size_t)args->entities * sizeof(*ids));
        for (uint32_t i = 0; i < args->warmup; ++i) {
            entity_cycle_once(ids, args->entities);
        }
        start = now_ns();
        for (uint32_t i = 0; i < args->iterations; ++i) {
            entity_cycle_once(ids, args->entities);
        }
        end = now_ns();
        *checksum = checksum_positions();
        free(ids);
    } else if (strcmp(args->workload, "add_remove") == 0) {
        ecs_entity_t *ids = malloc((size_t)args->entities * sizeof(*ids));
        if (ids == NULL) {
            fail("allocation failed");
        }
        for (uint32_t i = 0; i < args->entities; ++i) {
            const ecs_entity_t entity = ecs_new();
            ecs_set(entity, Position, { 1.0, 2.0 });
            ids[i] = entity;
        }
        add_remove_once(ids, args->entities);
        for (uint32_t i = 0; i < args->warmup; ++i) {
            add_remove_once(ids, args->entities);
        }
        start = now_ns();
        for (uint32_t i = 0; i < args->iterations; ++i) {
            add_remove_once(ids, args->entities);
        }
        end = now_ns();
        *checksum = checksum_positions();
        free(ids);
    } else if (strcmp(args->workload, "iterate") == 0) {
        for (uint32_t i = 0; i < args->entities; ++i) {
            const ecs_entity_t entity = ecs_new();
            ecs_set(entity, Position, { 1.0, 2.0 });
            ecs_set(entity, Velocity, { 0.5, -0.25 });
        }
        const ecs_query_id_t query =
            ecs_query({ .components = { ecs_inout(Position), ecs_in(Velocity) } });
        for (uint32_t i = 0; i < args->warmup; ++i) {
            iterate_once(query);
        }
        start = now_ns();
        for (uint32_t i = 0; i < args->iterations; ++i) {
            iterate_once(query);
        }
        end = now_ns();
        *checksum = checksum_positions();
        ecs_query_fini(query);
    } else {
        fail("unsupported workload");
    }

    ecs_fini();
    return end - start;
}

int main(int argc, char **argv) {
    const Args args = parse_args(argc, argv);
    for (uint32_t sample = 0; sample < args.samples; ++sample) {
        double checksum = 0.0;
        const uint64_t duration = run_sample(&args, &checksum);
        printf(
            "{\"protocol\":\"ecs-bench/v1\",\"system\":\"siecs\","
            "\"system_version\":\"" SIECS_BENCH_VERSION "\",\"language\":\"C\","
            "\"workload\":\"%s\",\"entities\":%" PRIu32 ",\"iterations\":%" PRIu32 ","
            "\"sample\":%" PRIu32 ",\"duration_ns\":%" PRIu64 ","
            "\"ns_per_iteration\":%.6f,\"checksum\":%.6f}\n",
            args.workload,
            args.entities,
            args.iterations,
            sample,
            duration,
            (double)duration / (double)args.iterations,
            checksum
        );
    }
    return 0;
}
