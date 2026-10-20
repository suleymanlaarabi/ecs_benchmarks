#include <gaia.h>

#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

namespace {

using gaia::ecs::Entity;
using gaia::ecs::Query;
using gaia::ecs::World;

struct Position {
  double x;
  double y;
};

struct Velocity {
  double x;
  double y;
};

struct Args {
  const char *workload = nullptr;
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
  const auto parsed = std::strtoull(value, &end, 10);
  if (*value == '\0' || *end != '\0' || parsed > UINT32_MAX ||
      (!allow_zero && parsed == 0)) {
    std::fprintf(stderr, "error: invalid value for %s\n", flag);
    std::exit(2);
  }
  return static_cast<uint32_t>(parsed);
}

Args parse_args(int argc, char **argv) {
  Args args;
  for (int i = 1; i < argc; ++i) {
    if (i + 1 >= argc) {
      fail("missing argument value");
    }
    const char *flag = argv[i];
    const char *value = argv[++i];
    if (std::strcmp(flag, "--workload") == 0) {
      args.workload = value;
    } else if (std::strcmp(flag, "--entities") == 0) {
      args.entities = parse_integer(flag, value, false);
    } else if (std::strcmp(flag, "--iterations") == 0) {
      args.iterations = parse_integer(flag, value, false);
    } else if (std::strcmp(flag, "--samples") == 0) {
      args.samples = parse_integer(flag, value, false);
    } else if (std::strcmp(flag, "--warmup") == 0) {
      args.warmup = parse_integer(flag, value, true);
    } else {
      fail("unknown argument");
    }
  }
  if (args.workload == nullptr || args.entities == 0 || args.iterations == 0 ||
      args.samples == 0) {
    fail("workload, entities, iterations and samples are required");
  }
  return args;
}

void register_components(World &world) {
  (void)world.add<Position>();
  (void)world.add<Velocity>();
}

void entity_cycle_once(World &world, std::vector<Entity> &ids, uint32_t count) {
  ids.clear();
  for (uint32_t i = 0; i < count; ++i) {
    const Entity entity = world.add();
    world.add<Position>(entity, {1.0, 2.0});
    ids.push_back(entity);
  }
  for (const Entity entity : ids) {
    world.del(entity);
  }
}

void add_remove_once(World &world, const std::vector<Entity> &ids) {
  for (const Entity entity : ids) {
    world.add<Velocity>(entity, {0.5, -0.25});
  }
  for (const Entity entity : ids) {
    world.del<Velocity>(entity);
  }
}

void iterate_once(Query &query) {
  query.each([](Position &position, const Velocity &velocity) {
    position.x += velocity.x;
    position.y += velocity.y;
  });
}

double checksum_positions(World &world) {
  double checksum = 0.0;
  auto query = world.query().all<Position>();
  query.each([&checksum](const Position &position) {
    checksum += position.x + position.y;
  });
  return checksum;
}

uint64_t run_sample(const Args &args, double &checksum) {
  using Clock = std::chrono::steady_clock;
  World world;
  register_components(world);
  Clock::time_point start;
  Clock::time_point end;

  if (std::strcmp(args.workload, "entity_cycle") == 0) {
    std::vector<Entity> ids;
    ids.reserve(args.entities);
    for (uint32_t i = 0; i < args.warmup; ++i) {
      entity_cycle_once(world, ids, args.entities);
    }
    start = Clock::now();
    for (uint32_t i = 0; i < args.iterations; ++i) {
      entity_cycle_once(world, ids, args.entities);
    }
    end = Clock::now();
    checksum = static_cast<double>(world.query().all<Position>().count());
  } else if (std::strcmp(args.workload, "add_remove") == 0) {
    std::vector<Entity> ids;
    ids.reserve(args.entities);
    for (uint32_t i = 0; i < args.entities; ++i) {
      const Entity entity = world.add();
      world.add<Position>(entity, {1.0, 2.0});
      ids.push_back(entity);
    }
    add_remove_once(world, ids);
    for (uint32_t i = 0; i < args.warmup; ++i) {
      add_remove_once(world, ids);
    }
    start = Clock::now();
    for (uint32_t i = 0; i < args.iterations; ++i) {
      add_remove_once(world, ids);
    }
    end = Clock::now();
    checksum = checksum_positions(world);
  } else if (std::strcmp(args.workload, "iterate") == 0) {
    for (uint32_t i = 0; i < args.entities; ++i) {
      const Entity entity = world.add();
      world.add<Position>(entity, {1.0, 2.0});
      world.add<Velocity>(entity, {0.5, -0.25});
    }
    auto query = world.query().all<Position &>().all<Velocity>();
    for (uint32_t i = 0; i < args.warmup; ++i) {
      iterate_once(query);
    }
    start = Clock::now();
    for (uint32_t i = 0; i < args.iterations; ++i) {
      iterate_once(query);
    }
    end = Clock::now();
    checksum = checksum_positions(world);
  } else {
    fail("unsupported workload");
  }

  return static_cast<uint64_t>(
      std::chrono::duration_cast<std::chrono::nanoseconds>(end - start)
          .count());
}

} // namespace

int main(int argc, char **argv) {
  const Args args = parse_args(argc, argv);
  for (uint32_t sample = 0; sample < args.samples; ++sample) {
    double checksum = 0.0;
    const uint64_t duration = run_sample(args, checksum);
    std::printf("{\"protocol\":\"ecs-bench/v1\",\"system\":\"gaia\","
                "\"system_version\":\"1.0.0\",\"language\":\"C++\","
                "\"workload\":\"%s\",\"entities\":%u,\"iterations\":%u,"
                "\"sample\":%u,\"duration_ns\":%llu,"
                "\"ns_per_iteration\":%.6f,\"checksum\":%.6f}\n",
                args.workload, args.entities, args.iterations, sample,
                static_cast<unsigned long long>(duration),
                static_cast<double>(duration) /
                    static_cast<double>(args.iterations),
                checksum);
  }
  return 0;
}
