# Benchmark protocol (`ecs-bench/v1`)

This document is normative. An adapter may be written in any language and use
any build system, but it must expose the same command-line and output
semantics.

## Invocation

The runner invokes an adapter once per `(workload, entity count)`:

```text
binary
  --workload <id>
  --entities <positive integer>
  --iterations <positive integer>
  --samples <positive integer>
  --warmup <non-negative integer>
```

The process must emit exactly one compact JSON object per sample on stdout,
separated by newlines. Diagnostics belong on stderr. Process startup and JSON
serialization are not timed.

Required fields:

| Field | JSON type | Meaning |
|---|---|---|
| `protocol` | string | Exactly `ecs-bench/v1` |
| `system` | string | Same stable id as `project.toml` |
| `system_version` | string | Pinned release or commit |
| `language` | string | Language used by the adapter |
| `workload` | string | Requested workload id |
| `entities` | integer | Requested entity count |
| `iterations` | integer | Timed repetitions in this sample |
| `sample` | integer | Zero-based index, unique in the invocation |
| `duration_ns` | integer | Total timed duration, greater than zero |
| `ns_per_iteration` | number | `duration_ns / iterations` |
| `checksum` | number | Value derived from final ECS state |

Example:

```json
{"protocol":"ecs-bench/v1","system":"example","system_version":"1.2.3","language":"C","workload":"iterate","entities":10000,"iterations":100,"sample":0,"duration_ns":4200000,"ns_per_iteration":42000.0,"checksum":280000.0}
```

The runner rejects malformed records, mismatched parameters, duplicate sample
indices, non-positive durations, and inconsistent normalized durations.

## Components

All adapters use semantically equivalent table-stored components:

```text
Position { x: f64 = 1.0, y: f64 = 2.0 }
Velocity { x: f64 = 0.5, y: f64 = -0.25 }
```

Use ordinary dense/archetype storage. Do not opt into sparse storage, change
tracking filters, parallel iteration, deferred command buffers, relationships,
or library-specific bulk APIs unless a future workload explicitly asks for
them.

## Workloads

### `entity_cycle`

Per repetition:

1. create `N` entities one by one, each born with `Position`;
2. retain their entity handles;
3. destroy those entities one by one.

The world is empty before and after each repetition. Handle-array reuse is
allowed, but pushing handles and growing it on its first use is included.
Component registration is setup; entity allocation and destruction are timed.
The final checksum is the number of remaining `Position` entities (`0`).

### `add_remove`

Setup creates `N` entities with `Position`, stores their handles, and creates
the destination archetype once. Per repetition:

1. add `Velocity` with the standard values to every entity;
2. remove `Velocity` from every entity.

The checksum is the sum of `Position.x + Position.y`, expected to be `3 * N`.
Both migrations and component initialization are timed.

### `iterate`

Setup creates `N` entities with both components and builds the query once. Per
repetition, a single-threaded cached query performs:

```text
position.x += velocity.x
position.y += velocity.y
```

Query traversal and component updates are timed. Query construction and the
final checksum traversal are excluded. After `W` warmups and `I` timed
iterations, the checksum is:

```text
N * (3.0 + (W + I) * 0.25)
```

## Samples and timing

Each sample uses a new world. Warmup repetitions happen immediately before the
timed repetitions in that world. Use the language/platform monotonic
high-resolution clock, and measure one contiguous region per sample.

The report uses median nanoseconds per repetition. It also retains mean, min,
max, and interpolated p95. Graphs convert medians to milliseconds and use a
logarithmic axis.

Run benchmarks on an idle machine in a fixed performance/power mode when
publishing comparative claims. Keep compiler flags and dependency pins visible
in the adapter.
