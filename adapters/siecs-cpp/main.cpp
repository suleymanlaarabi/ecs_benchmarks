// Same workloads as the C adapter, written with the idiomatic C++20 API.
// It measures what a C++ user pays for the typed API: it must stay within the
// noise of the hand-written C loop.
//
// Typed C++ component ids outlive ecs::fini() but are not registered again in
// the next world, so one world serves every sample; each sample destroys the
// entities it created. Warmup runs before timing either way.
#include <siecs.h>

#ifndef NDEBUG
#error "Siecs benchmark must be built in release mode"
#endif

#include <chrono>
#include <cinttypes>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string_view>
#include <vector>

#ifndef SIECS_BENCH_VERSION
#define SIECS_BENCH_VERSION "4124e2d"
#endif

struct Position {
    double x;
    double y;
};

struct Velocity {
    double x;
    double y;
};

namespace {

struct Args {
    std::string_view workload;
    uint32_t entities = 0;
    uint32_t iterations = 0;
    uint32_t samples = 0;
    uint32_t warmup = 0;
};

[[noreturn]] void fail(const char *message) {
    std::fprintf(stderr, "error: %s\n", message);
    std::exit(2);
}

uint32_t parse_integer(const char *flag, const char *value, bool allow_zero) {
    char *end = nullptr;
    const unsigned long long parsed = std::strtoull(value, &end, 10);
    if (*value == '\0' || *end != '\0' || parsed > UINT32_MAX || (!allow_zero && parsed == 0)) {
        std::fprintf(stderr, "error: invalid value for %s\n", flag);
        std::exit(2);
    }
    return static_cast<uint32_t>(parsed);
}

Args parse_args(int argc, char **argv) {
    Args args;
    for (int i = 1; i < argc; ++i) {
        if (i + 1 >= argc)
            fail("missing argument value");
        const std::string_view flag = argv[i];
        const char *value = argv[++i];
        if (flag == "--workload")
            args.workload = value;
        else if (flag == "--entities")
            args.entities = parse_integer(argv[i - 1], value, false);
        else if (flag == "--iterations")
            args.iterations = parse_integer(argv[i - 1], value, false);
        else if (flag == "--samples")
            args.samples = parse_integer(argv[i - 1], value, false);
        else if (flag == "--warmup")
            args.warmup = parse_integer(argv[i - 1], value, true);
        else
            fail("unknown argument");
    }
    if (args.workload.empty() || args.entities == 0 || args.iterations == 0 || args.samples == 0)
        fail("workload, entities, iterations and samples are required");
    return args;
}

uint64_t now_ns() {
    return static_cast<uint64_t>(
        std::chrono::duration_cast<std::chrono::nanoseconds>(
            std::chrono::steady_clock::now().time_since_epoch()
        )
            .count()
    );
}

void entity_cycle_once(std::vector<ecs::entity> &ids) {
    for (auto &id : ids)
        id = ecs::spawn().set(Position{ 1.0, 2.0 });
    for (auto id : ids)
        id.kill();
}

void add_remove_once(const std::vector<ecs::entity> &ids) {
    for (auto id : ids)
        id.set(Velocity{ 0.5, -0.25 });
    for (auto id : ids)
        id.remove<Velocity>();
}

double checksum_positions() {
    double checksum = 0.0;
    ecs::query().each([&](const Position &position) { checksum += position.x + position.y; });
    return checksum;
}

uint64_t run_sample(const Args &args, double &checksum) {
    uint64_t start = 0;
    uint64_t end = 0;

    if (args.workload == "entity_cycle") {
        std::vector<ecs::entity> ids(args.entities);
        for (uint32_t i = 0; i < args.warmup; ++i)
            entity_cycle_once(ids);
        start = now_ns();
        for (uint32_t i = 0; i < args.iterations; ++i)
            entity_cycle_once(ids);
        end = now_ns();
    } else if (args.workload == "add_remove") {
        std::vector<ecs::entity> ids(args.entities);
        for (auto &id : ids)
            id = ecs::spawn().set(Position{ 1.0, 2.0 });
        add_remove_once(ids);
        for (uint32_t i = 0; i < args.warmup; ++i)
            add_remove_once(ids);
        start = now_ns();
        for (uint32_t i = 0; i < args.iterations; ++i)
            add_remove_once(ids);
        end = now_ns();
        checksum = checksum_positions();
        for (auto id : ids)
            id.kill();
        return end - start;
    } else if (args.workload == "iterate") {
        std::vector<ecs::entity> ids(args.entities);
        for (auto &id : ids)
            id = ecs::spawn().set(Position{ 1.0, 2.0 }, Velocity{ 0.5, -0.25 });
        auto query = ecs::query<Position &, const Velocity &>().build();
        auto move = [](Position &position, const Velocity &velocity) {
            position.x += velocity.x;
            position.y += velocity.y;
        };
        for (uint32_t i = 0; i < args.warmup; ++i)
            query.each(move);
        start = now_ns();
        for (uint32_t i = 0; i < args.iterations; ++i)
            query.each(move);
        end = now_ns();
        checksum = checksum_positions();
        for (auto id : ids)
            id.kill();
        return end - start;
    } else {
        fail("unsupported workload");
    }

    checksum = checksum_positions();
    return end - start;
}

} // namespace

int main(int argc, char **argv) {
    const Args args = parse_args(argc, argv);
    ecs::init();
    for (uint32_t sample = 0; sample < args.samples; ++sample) {
        double checksum = 0.0;
        const uint64_t duration = run_sample(args, checksum);
        std::printf(
            "{\"protocol\":\"ecs-bench/v1\",\"system\":\"siecs-cpp\","
            "\"system_version\":\"" SIECS_BENCH_VERSION "\",\"language\":\"C++\","
            "\"workload\":\"%.*s\",\"entities\":%" PRIu32 ",\"iterations\":%" PRIu32 ","
            "\"sample\":%" PRIu32 ",\"duration_ns\":%" PRIu64 ","
            "\"ns_per_iteration\":%.6f,\"checksum\":%.6f}\n",
            static_cast<int>(args.workload.size()),
            args.workload.data(),
            args.entities,
            args.iterations,
            sample,
            duration,
            static_cast<double>(duration) / static_cast<double>(args.iterations),
            checksum
        );
    }
    ecs::fini();
    return 0;
}
