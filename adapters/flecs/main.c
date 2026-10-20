#include <flecs.h>

#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#endif

typedef struct {
    double x;
    double y;
} Position;

typedef struct {
    double x;
    double y;
} Velocity;

ECS_COMPONENT_DECLARE(Position);
ECS_COMPONENT_DECLARE(Velocity);

typedef struct {
    const char *workload;
    int32_t entities;
    int32_t iterations;
    int32_t samples;
    int32_t warmup;
} Args;

static void fail(const char *message) {
    fprintf(stderr, "error: %s\n", message);
    exit(2);
}

static void validate_build_config(void) {
    const ecs_build_info_t *info = ecs_get_build_info();
    if (info->debug) {
        fail("Flecs must be compiled in release mode");
    }

    bool has_ndebug = false;
    for (const char **flag = info->flags; flag != NULL && *flag != NULL; ++flag) {
        if (strcmp(*flag, "FLECS_NDEBUG") == 0) {
            has_ndebug = true;
        }
    }
    if (!has_ndebug) {
        fail("FLECS_NDEBUG is not active");
    }

    uint32_t addon_count = 0;
    for (const char **addon = info->addons; addon != NULL && *addon != NULL; ++addon) {
        if (strcmp(*addon, "FLECS_OS_API_IMPL") != 0) {
            fprintf(stderr, "error: unexpected Flecs addon: %s\n", *addon);
            exit(2);
        }
        addon_count++;
    }
    if (addon_count != 1) {
        fail("Flecs must only include its OS API implementation");
    }
}

static int32_t parse_positive(const char *flag, const char *value, int allow_zero) {
    if (value == NULL) {
        fail("missing argument value");
    }
    char *end = NULL;
    long parsed = strtol(value, &end, 10);
    if (*value == '\0' || *end != '\0' || parsed < (allow_zero ? 0 : 1) || parsed > INT32_MAX) {
        fprintf(stderr, "error: invalid value for %s\n", flag);
        exit(2);
    }
    return (int32_t)parsed;
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
            args.entities = parse_positive(flag, value, 0);
        } else if (strcmp(flag, "--iterations") == 0) {
            args.iterations = parse_positive(flag, value, 0);
        } else if (strcmp(flag, "--samples") == 0) {
            args.samples = parse_positive(flag, value, 0);
        } else if (strcmp(flag, "--warmup") == 0) {
            args.warmup = parse_positive(flag, value, 1);
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
#ifdef _WIN32
    LARGE_INTEGER counter;
    LARGE_INTEGER frequency;
    QueryPerformanceCounter(&counter);
    QueryPerformanceFrequency(&frequency);
    return (uint64_t)((double)counter.QuadPart * 1000000000.0 / (double)frequency.QuadPart);
#else
    struct timespec value;
    if (clock_gettime(CLOCK_MONOTONIC, &value) != 0) {
        fail("clock_gettime failed");
    }
    return (uint64_t)value.tv_sec * UINT64_C(1000000000) + (uint64_t)value.tv_nsec;
#endif
}

static void register_components(ecs_world_t *world) {
    ECS_COMPONENT_DEFINE(world, Position);
    ECS_COMPONENT_DEFINE(world, Velocity);
}

static void entity_cycle_once(ecs_world_t *world, ecs_entity_t *ids, int32_t count) {
    for (int32_t i = 0; i < count; ++i) {
        ids[i] = ecs_insert(world, ecs_value(Position, { 1.0, 2.0 }));
    }
    for (int32_t i = 0; i < count; ++i) {
        ecs_delete(world, ids[i]);
    }
}

static void add_remove_once(ecs_world_t *world, const ecs_entity_t *ids, int32_t count) {
    for (int32_t i = 0; i < count; ++i) {
        ecs_set(world, ids[i], Velocity, { 0.5, -0.25 });
    }
    for (int32_t i = 0; i < count; ++i) {
        ecs_remove(world, ids[i], Velocity);
    }
}

static void iterate_once(ecs_world_t *world, ecs_query_t *query) {
    ecs_iter_t it = ecs_query_iter(world, query);
    while (ecs_query_next(&it)) {
        Position *positions = ecs_field(&it, Position, 0);
        const Velocity *velocities = ecs_field(&it, Velocity, 1);
        for (int32_t i = 0; i < it.count; ++i) {
            positions[i].x += velocities[i].x;
            positions[i].y += velocities[i].y;
        }
    }
}

static double checksum_positions(ecs_world_t *world) {
    ecs_query_t *query =
        ecs_query(world, { .terms = { { .id = ecs_id(Position), .inout = EcsIn } } });
    double checksum = 0.0;
    ecs_iter_t it = ecs_query_iter(world, query);
    while (ecs_query_next(&it)) {
        const Position *positions = ecs_field(&it, Position, 0);
        for (int32_t i = 0; i < it.count; ++i) {
            checksum += positions[i].x + positions[i].y;
        }
    }
    ecs_query_fini(query);
    return checksum;
}

static uint64_t run_sample(const Args *args, double *checksum) {
    ecs_world_t *world = ecs_init();
    register_components(world);
    uint64_t start;
    uint64_t end;

    if (strcmp(args->workload, "entity_cycle") == 0) {
        ecs_entity_t *ids = malloc((size_t)args->entities * sizeof(ecs_entity_t));
        if (ids == NULL) {
            fail("allocation failed");
        }
        for (int32_t i = 0; i < args->warmup; ++i) {
            entity_cycle_once(world, ids, args->entities);
        }
        start = now_ns();
        for (int32_t i = 0; i < args->iterations; ++i) {
            entity_cycle_once(world, ids, args->entities);
        }
        end = now_ns();
        *checksum = (double)ecs_count(world, Position);
        free(ids);
    } else if (strcmp(args->workload, "add_remove") == 0) {
        ecs_entity_t *ids = malloc((size_t)args->entities * sizeof(ecs_entity_t));
        if (ids == NULL) {
            fail("allocation failed");
        }
        for (int32_t i = 0; i < args->entities; ++i) {
            ids[i] = ecs_insert(world, ecs_value(Position, { 1.0, 2.0 }));
        }
        add_remove_once(world, ids, args->entities);
        for (int32_t i = 0; i < args->warmup; ++i) {
            add_remove_once(world, ids, args->entities);
        }
        start = now_ns();
        for (int32_t i = 0; i < args->iterations; ++i) {
            add_remove_once(world, ids, args->entities);
        }
        end = now_ns();
        *checksum = checksum_positions(world);
        free(ids);
    } else if (strcmp(args->workload, "iterate") == 0) {
        for (int32_t i = 0; i < args->entities; ++i) {
            ecs_insert(
                world,
                ecs_value(Position, { 1.0, 2.0 }),
                ecs_value(Velocity, { 0.5, -0.25 })
            );
        }
        ecs_query_t *query = ecs_query(
        world, {
                   .terms =
                       {
                           {.id = ecs_id(Position), .inout = EcsInOut},
                           {.id = ecs_id(Velocity), .inout = EcsIn},
                       },
                   .cache_kind = EcsQueryCacheAuto,
               });
        for (int32_t i = 0; i < args->warmup; ++i) {
            iterate_once(world, query);
        }
        start = now_ns();
        for (int32_t i = 0; i < args->iterations; ++i) {
            iterate_once(world, query);
        }
        end = now_ns();
        *checksum = checksum_positions(world);
        ecs_query_fini(query);
    } else {
        fail("unsupported workload");
    }
    ecs_fini(world);
    return end - start;
}

int main(int argc, char **argv) {
    validate_build_config();
    const Args args = parse_args(argc, argv);
    for (int32_t sample = 0; sample < args.samples; ++sample) {
        double checksum = 0.0;
        const uint64_t duration = run_sample(&args, &checksum);
        printf(
            "{\"protocol\":\"ecs-bench/v1\",\"system\":\"flecs\","
            "\"system_version\":\"4.1.6\",\"language\":\"C\","
            "\"workload\":\"%s\",\"entities\":%" PRId32 ",\"iterations\":%" PRId32 ","
            "\"sample\":%" PRId32 ",\"duration_ns\":%" PRIu64 ","
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
