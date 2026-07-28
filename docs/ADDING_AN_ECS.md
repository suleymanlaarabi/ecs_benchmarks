# Adding an ECS

## 1. Create the adapter

Use the scaffold command:

```console
./bench scaffold myecs \
  --name "My ECS" \
  --language C++ \
  --version 1.2.3 \
  --url https://example.com/myecs
```

It creates `adapters/myecs/project.toml` in a disabled state, so an unfinished
adapter never breaks normal runs.

## 2. Build a native executable

Put the source and normal language-specific build files inside the adapter
directory. The executable must implement [the protocol](PROTOCOL.md). Keep
third-party code out of this repository when the package manager or CMake
`FetchContent` can pin it reproducibly.

Fill the manifest:

```toml
[project]
id = "myecs"
name = "My ECS"
language = "C++"
version = "1.2.3"
url = "https://example.com/myecs"
enabled = false

[build]
cwd = "{root}"
commands = [
  ["cmake", "-S", "adapters/myecs", "-B", "build/myecs", "-G", "Ninja",
   "-DCMAKE_BUILD_TYPE=Release"],
  ["cmake", "--build", "build/myecs", "--config", "Release"],
]

[run]
binary = "build/myecs/myecs-bench"
command = ["{binary}"]
workloads = ["entity_cycle", "add_remove", "iterate"]
```

Commands are arrays of arguments, not shell strings. This avoids quoting
differences and works on CI. Available placeholders are `{root}`,
`{project_dir}`, and `{binary}`.

An adapter may deliberately omit unsupported workload ids. The runner marks
them unsupported instead of inventing a score.

## 3. Check semantics

Before timing, compare checksums with an existing adapter using a tiny case:

```console
./bench build --system myecs
./bench --quick --no-build --system myecs --entities 10 --samples 1
```

For `N = 10`, expected checksums are `0` for `entity_cycle`, `30` for
`add_remove`, and `82.5` for quick `iterate` (`1` warmup + `20` measured
iterations).

Do not move setup work into or out of the timed region to make a library look
better. If the API cannot represent the specified operation exactly, document
the difference and leave that workload unsupported.

## 4. Enable and validate

Set `project.enabled = true`, then:

```console
./bench validate
make test
./bench --quick --system myecs
```

No registry update is needed: discovery is automatic.
