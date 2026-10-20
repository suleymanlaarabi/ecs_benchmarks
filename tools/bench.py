#!/usr/bin/env python3
"""Language-agnostic benchmark runner for archetype ECS implementations."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import html
import json
import math
import os
import pathlib
import platform
import re
import shutil
import statistics
import subprocess
import sys
import tomllib
from collections import defaultdict
from typing import Any, Iterable

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROTOCOL = "ecs-bench/v1"
README_TEMPLATE = ROOT / "README.template.md"
README_BEGIN = "<!-- BENCH_RESULTS:BEGIN -->"
README_END = "<!-- BENCH_RESULTS:END -->"


class BenchError(RuntimeError):
    pass


def read_toml(path: pathlib.Path) -> dict[str, Any]:
    try:
        with path.open("rb") as stream:
            return tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise BenchError(f"cannot read {path.relative_to(ROOT)}: {exc}") from exc


def discover_projects(include_disabled: bool = False) -> list[dict[str, Any]]:
    projects = []
    for manifest_path in sorted((ROOT / "adapters").glob("*/project.toml")):
        manifest = read_toml(manifest_path)
        project = manifest.get("project", {})
        if not include_disabled and not project.get("enabled", True):
            continue
        manifest["_path"] = manifest_path
        manifest["_dir"] = manifest_path.parent
        dev = manifest.get("dev")
        manifest["_dev"] = bool(dev and os.environ.get(dev["env"]))
        if manifest["_dev"]:
            project["version"] = dev["version"]
        projects.append(manifest)
    return projects


def select_projects(ids: list[str] | None) -> list[dict[str, Any]]:
    projects = discover_projects()
    if not ids:
        return projects
    wanted = set(ids)
    selected = [p for p in projects if p["project"]["id"] in wanted]
    missing = wanted - {p["project"]["id"] for p in selected}
    if missing:
        raise BenchError(f"unknown system(s): {', '.join(sorted(missing))}")
    return selected


def expand(parts: Iterable[str], manifest: dict[str, Any]) -> list[str]:
    values = {
        "root": str(ROOT),
        "project_dir": str(manifest["_dir"]),
        "binary": str(ROOT / manifest["run"]["binary"]),
    }
    return [part.format(**values) for part in parts]


def command_cwd(value: str | None, manifest: dict[str, Any]) -> pathlib.Path:
    if not value:
        return manifest["_dir"]
    return pathlib.Path(expand([value], manifest)[0])


def run_command(
    command: list[str],
    *,
    cwd: pathlib.Path,
    capture: bool = False,
    quiet: bool = False,
    env: dict[str, str] | None = None,
    cpu: int | None = None,
) -> subprocess.CompletedProcess[str]:
    if not quiet:
        print(f"  $ {' '.join(command)}", flush=True)
    preexec = None
    if cpu is not None:
        def preexec() -> None:
            os.sched_setaffinity(0, {cpu})
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            check=True,
            text=True,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
            env=None if env is None else {**os.environ, **env},
            preexec_fn=preexec,
        )
    except FileNotFoundError as exc:
        raise BenchError(f"command not found: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = ""
        if capture:
            detail = f"\nstdout:\n{exc.stdout}\nstderr:\n{exc.stderr}"
        raise BenchError(
            f"command failed ({exc.returncode}): {' '.join(command)}{detail}"
        ) from exc


def build_project(manifest: dict[str, Any]) -> None:
    project = manifest["project"]
    print(f"\nBuilding {project['name']} ({project['language']})", flush=True)
    build = manifest["build"]
    cwd = command_cwd(build.get("cwd"), manifest)
    commands = list(build["commands"])
    env = None
    if manifest["_dev"]:
        dev = manifest["dev"]
        print(f"  (dev mode: {dev['env']} is set)", flush=True)
        commands = list(dev.get("commands", [])) + commands
        env = {
            key: expand([value], manifest)[0]
            for key, value in dev.get("environment", {}).items()
        }
    for raw_command in commands:
        run_command(expand(raw_command, manifest), cwd=cwd, env=env)
    binary = ROOT / manifest["run"]["binary"]
    if not binary.is_file():
        raise BenchError(f"{project['id']}: binary was not produced at {binary}")


def build_projects(projects: list[dict[str, Any]], keep_going: bool) -> list[dict[str, Any]]:
    ready = []
    for manifest in projects:
        try:
            build_project(manifest)
            ready.append(manifest)
        except BenchError as exc:
            if not keep_going:
                raise
            print(f"warning: skipping {manifest['project']['id']}: {exc}", file=sys.stderr)
    return ready


def suite_config(quick: bool) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    config = read_toml(ROOT / "suite.toml")
    if config.get("schema_version") != 1:
        raise BenchError("suite.toml: unsupported schema_version")
    suite = config["suite"]
    settings = {
        "name": suite["name"],
        "samples": suite["quick_samples"] if quick else suite["samples"],
        "warmup": suite["quick_warmup"] if quick else suite["warmup"],
        "entities": suite["quick_entities"] if quick else suite["entities"],
        "rounds": suite.get("quick_rounds" if quick else "rounds", 1),
        "cpu": suite.get("cpu"),
    }
    workloads = []
    for item in config["workloads"]:
        item = dict(item)
        item["active_iterations"] = (
            item["quick_iterations"] if quick else item["iterations"]
        )
        workloads.append(item)
    return settings, workloads


def validate_record(
    record: dict[str, Any],
    manifest: dict[str, Any],
    workload: dict[str, Any],
    entities: int,
    iterations: int,
    samples: int,
    warmup: int,
) -> None:
    required = {
        "protocol",
        "system",
        "system_version",
        "language",
        "workload",
        "entities",
        "iterations",
        "sample",
        "duration_ns",
        "ns_per_iteration",
        "checksum",
    }
    missing = required - record.keys()
    if missing:
        raise BenchError(f"record misses: {', '.join(sorted(missing))}")
    expected = {
        "protocol": PROTOCOL,
        "system": manifest["project"]["id"],
        "system_version": manifest["project"]["version"],
        "language": manifest["project"]["language"],
        "workload": workload["id"],
        "entities": entities,
        "iterations": iterations,
    }
    for key, value in expected.items():
        if record[key] != value:
            raise BenchError(f"invalid {key}: expected {value!r}, got {record[key]!r}")
    if not isinstance(record["sample"], int) or not 0 <= record["sample"] < samples:
        raise BenchError(f"invalid sample index: {record['sample']!r}")
    if not isinstance(record["duration_ns"], int) or record["duration_ns"] <= 0:
        raise BenchError(f"invalid duration_ns: {record['duration_ns']!r}")
    expected_ns = record["duration_ns"] / iterations
    if not math.isclose(float(record["ns_per_iteration"]), expected_ns, rel_tol=1e-6):
        raise BenchError("ns_per_iteration does not match duration_ns / iterations")
    expected_checksum = {
        "entity_cycle": 0.0,
        "add_remove": 3.0 * entities,
        "iterate": entities * (3.0 + (warmup + iterations) * 0.25),
    }.get(workload["id"])
    if expected_checksum is not None and not math.isclose(
        float(record["checksum"]), expected_checksum, rel_tol=1e-9, abs_tol=1e-6
    ):
        raise BenchError(
            f"invalid checksum: expected {expected_checksum:g}, "
            f"got {record['checksum']!r}"
        )


def invoke_case(
    manifest: dict[str, Any],
    workload: dict[str, Any],
    entities: int,
    iterations: int,
    samples: int,
    warmup: int,
    cpu: int | None = None,
) -> list[dict[str, Any]]:
    run = manifest["run"]
    command = expand(run.get("command", ["{binary}"]), manifest)
    command += [
        "--workload",
        workload["id"],
        "--entities",
        str(entities),
        "--iterations",
        str(iterations),
        "--samples",
        str(samples),
        "--warmup",
        str(warmup),
    ]
    result = run_command(
        command,
        cwd=command_cwd(run.get("cwd"), manifest),
        capture=True,
        quiet=True,
        cpu=cpu,
    )
    records = []
    for line_number, line in enumerate(result.stdout.splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BenchError(
                f"{manifest['project']['id']} emitted invalid JSON on line {line_number}: {line}"
            ) from exc
        validate_record(
            record, manifest, workload, entities, iterations, samples, warmup
        )
        records.append(record)
    if len(records) != samples:
        raise BenchError(
            f"{manifest['project']['id']} emitted {len(records)} samples, expected {samples}"
        )
    if {r["sample"] for r in records} != set(range(samples)):
        raise BenchError(f"{manifest['project']['id']} emitted duplicate sample indices")
    return records


def machine_metadata() -> dict[str, Any]:
    cpu = platform.processor() or "unknown"
    cpuinfo = pathlib.Path("/proc/cpuinfo")
    if cpuinfo.is_file():
        for line in cpuinfo.read_text(errors="replace").splitlines():
            if line.lower().startswith("model name"):
                cpu = line.split(":", 1)[1].strip()
                break
    git_commit = None
    if (ROOT / ".git").exists():
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        if proc.returncode == 0:
            git_commit = proc.stdout.strip()
    return {
        "timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "platform": platform.platform(),
        "cpu": cpu,
        "logical_cpus": os.cpu_count(),
        "python": platform.python_version(),
        "git_commit": git_commit,
    }


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = (len(ordered) - 1) * fraction
    low = math.floor(index)
    high = math.ceil(index)
    if low == high:
        return ordered[low]
    return ordered[low] * (high - index) + ordered[high] * (index - low)


def summarize(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], list[float]] = defaultdict(list)
    versions: dict[str, str] = {}
    languages: dict[str, str] = {}
    for record in records:
        key = (record["workload"], record["entities"], record["system"])
        grouped[key].append(float(record["ns_per_iteration"]))
        versions[record["system"]] = str(record["system_version"])
        languages[record["system"]] = str(record["language"])
    summary = []
    for (workload, entities, system), values in sorted(grouped.items()):
        median = statistics.median(values)
        summary.append(
            {
                "workload": workload,
                "entities": entities,
                "system": system,
                "system_version": versions[system],
                "language": languages[system],
                "samples": len(values),
                "median_ns": round(median, 3),
                "mean_ns": round(statistics.fmean(values), 3),
                "min_ns": round(min(values), 3),
                "max_ns": round(max(values), 3),
                "p95_ns": round(percentile(values, 0.95), 3),
                "mad_ns": round(statistics.median(abs(v - median) for v in values), 3),
            }
        )
    return summary


def write_csv(path: pathlib.Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise BenchError("cannot write an empty summary")
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


PALETTE = ["#e76f51", "#2a9d8f", "#457b9d", "#f4a261", "#8d5cf6", "#6a994e"]


def render_svg(
    workload: dict[str, Any],
    rows: list[dict[str, Any]],
    systems: list[str],
    output: pathlib.Path,
) -> None:
    width, height = 920, 500
    left, right, top, bottom = 88, 24, 64, 84
    plot_w, plot_h = width - left - right, height - top - bottom
    entity_values = sorted({int(row["entities"]) for row in rows})
    values_ms = [float(row["median_ns"]) / 1_000_000 for row in rows]
    positive = [value for value in values_ms if value > 0]
    y_min = min(positive) if positive else 0.001
    y_max = max(positive) if positive else 1.0
    y_min = 10 ** math.floor(math.log10(y_min))
    y_max = 10 ** math.ceil(math.log10(y_max))
    if y_max <= y_min:
        y_max = y_min * 10

    def y(value: float) -> float:
        ratio = (math.log10(value) - math.log10(y_min)) / (
            math.log10(y_max) - math.log10(y_min)
        )
        return top + plot_h * (1 - ratio)

    row_map = {
        (int(row["entities"]), str(row["system"])): float(row["median_ns"]) / 1_000_000
        for row in rows
    }
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        "<style>text{font-family:ui-sans-serif,system-ui,sans-serif;fill:#293241}.title{font-size:20px;font-weight:700}.axis{font-size:12px}.legend{font-size:13px}.grid{stroke:#dfe5ec;stroke-width:1}.bar{shape-rendering:crispEdges}</style>",
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text class="title" x="{left}" y="31">{html.escape(workload["name"])}</text>',
        f'<text class="axis" x="{left}" y="50">median ms / operation — logarithmic scale</text>',
    ]
    tick = y_min
    while tick <= y_max * 1.0001:
        py = y(tick)
        label = f"{tick:g}"
        parts += [
            f'<line class="grid" x1="{left}" y1="{py:.2f}" x2="{left + plot_w}" y2="{py:.2f}"/>',
            f'<text class="axis" text-anchor="end" x="{left - 9}" y="{py + 4:.2f}">{label}</text>',
        ]
        tick *= 10
    group_w = plot_w / max(1, len(entity_values))
    bar_w = min(46.0, group_w * 0.76 / max(1, len(systems)))
    baseline = y(y_min)
    for group_index, entities in enumerate(entity_values):
        center = left + group_w * (group_index + 0.5)
        total_w = bar_w * len(systems)
        for system_index, system in enumerate(systems):
            value = row_map.get((entities, system))
            if value is None:
                continue
            x = center - total_w / 2 + system_index * bar_w
            py = y(max(value, y_min))
            parts.append(
                f'<rect class="bar" x="{x + 1:.2f}" y="{py:.2f}" width="{bar_w - 2:.2f}" height="{max(1, baseline - py):.2f}" fill="{PALETTE[system_index % len(PALETTE)]}"><title>{html.escape(system)}: {value:.4g} ms</title></rect>'
            )
        parts.append(
            f'<text class="axis" text-anchor="middle" x="{center:.2f}" y="{height - bottom + 23}">{entities:,}</text>'
        )
    parts.append(
        f'<text class="axis" text-anchor="middle" x="{left + plot_w / 2}" y="{height - 17}">entities</text>'
    )
    legend_x = left
    for index, system in enumerate(systems):
        parts += [
            f'<rect x="{legend_x}" y="{height - 48}" width="13" height="13" rx="2" fill="{PALETTE[index % len(PALETTE)]}"/>',
            f'<text class="legend" x="{legend_x + 19}" y="{height - 37}">{html.escape(system)}</text>',
        ]
        legend_x += 30 + len(system) * 9
    parts.append("</svg>")
    output.write_text("\n".join(parts) + "\n", encoding="utf-8")


def markdown_results(
    summary: list[dict[str, Any]],
    metadata: dict[str, Any],
    workloads: list[dict[str, Any]],
) -> str:
    systems = sorted({str(row["system"]) for row in summary})
    versions = {
        str(row["system"]): str(row["system_version"])
        for row in summary
    }
    rows_by_key = {
        (str(row["workload"]), int(row["entities"]), str(row["system"])): row
        for row in summary
    }
    lines = [
        "## Latest results",
        "",
        f"Generated `{metadata['timestamp_utc']}` on **{metadata['cpu']}** "
        f"({metadata['logical_cpus']} logical CPUs, `{metadata['platform']}`).",
        "",
        f"Profile: **{'quick smoke run' if metadata.get('quick') else 'full suite'}** "
        f"with {metadata['samples']} samples and {metadata['warmup']} warmup "
        f"iteration(s).",
        "",
        "> **Experimental results.** These benchmarks exercise only a small, "
        "common subset of each ECS API. They do not cover every usage pattern "
        "or configuration, and the adapters may not always express each ECS "
        "at its best. Results can therefore be incomplete or misinterpreted; "
        "use them as exploratory measurements, not as a definitive ranking.",
        "",
        "Values are median milliseconds per operation; lower is better. "
        "Setup is excluded from the timed region.",
        "",
        "| Workload | Entities | " + " | ".join(f"{s} {versions[s]}" for s in systems) + " |",
        "|---|---:|" + "|".join("---:" for _ in systems) + "|",
    ]
    for workload in workloads:
        entities_set = sorted(
            {
                int(row["entities"])
                for row in summary
                if row["workload"] == workload["id"]
            }
        )
        for entities in entities_set:
            values = []
            for system in systems:
                row = rows_by_key.get((workload["id"], entities, system))
                values.append("—" if row is None else f"{float(row['median_ns']) / 1_000_000:.3f}")
            lines.append(
                f"| {workload['name']} | {entities:,} | " + " | ".join(values) + " |"
            )
    for workload in workloads:
        if any(row["workload"] == workload["id"] for row in summary):
            lines += [
                "",
                f"![{workload['name']}](results/latest/{workload['id']}.svg)",
            ]
    lines += [
        "",
        "Raw samples and full statistics: "
        "[raw.jsonl](results/latest/raw.jsonl), "
        "[summary.csv](results/latest/summary.csv), "
        "[run.json](results/latest/run.json).",
    ]
    return "\n".join(lines)


def replace_readme_section(content: str, generated: str) -> str:
    if README_BEGIN not in content or README_END not in content:
        raise BenchError("README template does not contain benchmark result markers")
    before, rest = content.split(README_BEGIN, 1)
    _, after = rest.split(README_END, 1)
    return f"{before}{README_BEGIN}\n\n{generated}\n\n{README_END}{after}"


def publish(
    run_dir: pathlib.Path,
    records: list[dict[str, Any]],
    summary: list[dict[str, Any]],
    metadata: dict[str, Any],
    workloads: list[dict[str, Any]],
) -> None:
    latest = ROOT / "results" / "latest"
    latest.mkdir(parents=True, exist_ok=True)
    for old_chart in latest.glob("*.svg"):
        old_chart.unlink()
    for filename in ("raw.jsonl", "summary.csv", "run.json"):
        source = run_dir / filename
        destination = latest / filename
        if source.resolve() != destination.resolve():
            shutil.copy2(source, destination)
    systems = sorted({str(row["system"]) for row in summary})
    for workload in workloads:
        rows = [row for row in summary if row["workload"] == workload["id"]]
        if rows:
            render_svg(workload, rows, systems, latest / f"{workload['id']}.svg")
    generated = markdown_results(summary, metadata, workloads)
    template = README_TEMPLATE.read_text(encoding="utf-8")
    (ROOT / "README.md").write_text(
        replace_readme_section(template, generated),
        encoding="utf-8",
    )


def check_machine(cpu: int | None) -> None:
    """Warn about machine settings that make timings unreliable."""
    if cpu is None:
        print("warning: CPU pinning disabled; expect noisy timings", file=sys.stderr)
    elif hasattr(os, "sched_getaffinity") and cpu not in os.sched_getaffinity(0):
        raise BenchError(f"cpu {cpu} is not available to this process")
    governor = pathlib.Path(
        f"/sys/devices/system/cpu/cpu{cpu or 0}/cpufreq/scaling_governor"
    )
    if governor.is_file():
        value = governor.read_text().strip()
        if value != "performance":
            print(
                f"warning: cpu{cpu or 0} governor is '{value}', not 'performance'; "
                "frequency scaling adds noise",
                file=sys.stderr,
            )


def print_case(records: list[dict[str, Any]], workload: str, entities: int) -> None:
    rows = [
        row
        for row in summarize(
            [r for r in records if r["workload"] == workload and r["entities"] == entities]
        )
    ]
    if not rows:
        return
    best = min(float(row["median_ns"]) for row in rows)
    for row in sorted(rows, key=lambda r: float(r["median_ns"])):
        median = float(row["median_ns"])
        spread = 100.0 * float(row["mad_ns"]) / median if median else 0.0
        print(
            f"    {row['system']:<12} median {median:>14,.1f} ns  "
            f"min {float(row['min_ns']):>14,.1f} ns  ±{spread:4.1f}%  "
            f"x{median / best:.2f}"
        )


def execute_run(args: argparse.Namespace) -> None:
    projects = select_projects(args.system)
    if not projects:
        raise BenchError("no enabled adapter found")
    settings, workloads = suite_config(args.quick)
    if args.workload:
        wanted = set(args.workload)
        workloads = [w for w in workloads if w["id"] in wanted]
        missing = wanted - {w["id"] for w in workloads}
        if missing:
            raise BenchError(f"unknown workload(s): {', '.join(sorted(missing))}")
    if args.entities:
        settings["entities"] = args.entities
    if args.samples is not None:
        settings["samples"] = args.samples
    if args.warmup is not None:
        settings["warmup"] = args.warmup
    if args.rounds is not None:
        settings["rounds"] = args.rounds
    if args.cpu is not None:
        settings["cpu"] = args.cpu
    if args.no_pin:
        settings["cpu"] = None
    settings["rounds"] = max(1, min(int(settings["rounds"]), settings["samples"]))
    for key in ("samples", "warmup"):
        if settings[key] < (0 if key == "warmup" else 1):
            raise BenchError(f"{key} must be positive")
    if any(value < 1 for value in settings["entities"]):
        raise BenchError("entity counts must be positive")

    if not args.no_build:
        projects = build_projects(projects, args.keep_going)
    if not projects:
        raise BenchError("no adapter could be built")
    check_machine(settings["cpu"])
    publish_results = not args.no_publish and not any(p["_dev"] for p in projects)

    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = ROOT / "results" / "runs" / timestamp
    suffix = 1
    while run_dir.exists():
        run_dir = ROOT / "results" / "runs" / f"{timestamp}-{suffix}"
        suffix += 1
    run_dir.mkdir(parents=True)
    metadata = machine_metadata()
    metadata.update(
        {
            "protocol": PROTOCOL,
            "quick": bool(args.quick),
            "samples": settings["samples"],
            "warmup": settings["warmup"],
            "entities": settings["entities"],
            "rounds": settings["rounds"],
            "pinned_cpu": settings["cpu"],
            "systems": [p["project"] for p in projects],
        }
    )
    (run_dir / "run.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    records: list[dict[str, Any]] = []
    total = len(workloads) * len(settings["entities"])
    current = 0
    for workload in workloads:
        iterations = int(workload["active_iterations"])
        for entities in settings["entities"]:
            current += 1
            runnable = []
            for manifest in projects:
                if workload["id"] in manifest["run"]["workloads"]:
                    runnable.append(manifest)
                else:
                    print(f"  {manifest['project']['id']}/{workload['id']}: unsupported")
            print(
                f"[{current}/{total}] {workload['id']}/{entities}: "
                f"{len(runnable)} system(s), {settings['samples']} samples "
                f"in {settings['rounds']} interleaved round(s)",
                flush=True,
            )
            # Systems alternate round by round, in a rotating order, so slow
            # drifts of the machine (clock, thermals, background load) are
            # spread over every system instead of penalizing whichever ran last.
            offsets = {m["project"]["id"]: 0 for m in runnable}
            failed: set[str] = set()
            for round_index in range(settings["rounds"]):
                count = settings["samples"] // settings["rounds"] + (
                    1 if round_index < settings["samples"] % settings["rounds"] else 0
                )
                if count == 0:
                    continue
                shift = round_index % max(1, len(runnable))
                for manifest in runnable[shift:] + runnable[:shift]:
                    system = manifest["project"]["id"]
                    if system in failed:
                        continue
                    try:
                        batch = invoke_case(
                            manifest,
                            workload,
                            entities,
                            iterations,
                            count,
                            settings["warmup"],
                            settings["cpu"],
                        )
                    except BenchError as exc:
                        if not args.keep_going:
                            raise
                        failed.add(system)
                        print(f"warning: {exc}", file=sys.stderr)
                        continue
                    for record in batch:
                        record["sample"] += offsets[system]
                    offsets[system] += count
                    records.extend(batch)
            print_case(records, workload["id"], entities)
    if not records:
        raise BenchError("the run produced no records")
    raw_path = run_dir / "raw.jsonl"
    raw_path.write_text(
        "".join(json.dumps(record, separators=(",", ":")) + "\n" for record in records),
        encoding="utf-8",
    )
    summary = summarize(records)
    write_csv(run_dir / "summary.csv", summary)
    if publish_results:
        publish(run_dir, records, summary, metadata, workloads)
        print(f"\nPublished {len(records)} samples to {run_dir.relative_to(ROOT)}")
        print("Updated results/latest and README.md")
    else:
        print(f"\nWrote {len(records)} samples to {run_dir.relative_to(ROOT)} (not published)")


def validate_repository() -> None:
    try:
        readme_template = README_TEMPLATE.read_text(encoding="utf-8")
    except OSError as exc:
        raise BenchError(f"cannot read {README_TEMPLATE.name}: {exc}") from exc
    if README_BEGIN not in readme_template or README_END not in readme_template:
        raise BenchError(f"{README_TEMPLATE.name} does not contain result markers")

    config = read_toml(ROOT / "suite.toml")
    workload_ids = [w["id"] for w in config.get("workloads", [])]
    if len(workload_ids) != len(set(workload_ids)):
        raise BenchError("suite.toml contains duplicate workload ids")
    if not workload_ids:
        raise BenchError("suite.toml contains no workload")
    projects = discover_projects(include_disabled=True)
    ids = [p["project"]["id"] for p in projects]
    if len(ids) != len(set(ids)):
        raise BenchError("adapter ids must be unique")
    for manifest in projects:
        project = manifest["project"]
        for key in ("id", "name", "language", "version", "url"):
            if not project.get(key):
                raise BenchError(f"{manifest['_path']}: missing project.{key}")
        for workload in manifest["run"].get("workloads", []):
            if workload not in workload_ids:
                raise BenchError(f"{project['id']}: unknown workload {workload}")
        for command in manifest["build"].get("commands", []):
            expand(command, manifest)
        expand(manifest["run"].get("command", ["{binary}"]), manifest)
    print(f"OK: {len(projects)} adapter(s), {len(workload_ids)} workload(s), protocol {PROTOCOL}")


def render_existing(run_dir_arg: str | None) -> None:
    run_dir = pathlib.Path(run_dir_arg) if run_dir_arg else ROOT / "results" / "latest"
    if not run_dir.is_absolute():
        run_dir = ROOT / run_dir
    raw_path = run_dir / "raw.jsonl"
    if not raw_path.is_file():
        raise BenchError(f"missing {raw_path}")
    records = [json.loads(line) for line in raw_path.read_text().splitlines() if line]
    summary = summarize(records)
    metadata = json.loads((run_dir / "run.json").read_text())
    _, workloads = suite_config(bool(metadata.get("quick")))
    write_csv(run_dir / "summary.csv", summary)
    publish(run_dir, records, summary, metadata, workloads)
    print(f"Rendered {len(records)} samples from {run_dir}")


def scaffold_adapter(args: argparse.Namespace) -> None:
    if not re.fullmatch(r"[a-z][a-z0-9_-]*", args.id):
        raise BenchError("id must match [a-z][a-z0-9_-]*")
    directory = ROOT / "adapters" / args.id
    if directory.exists():
        raise BenchError(f"{directory.relative_to(ROOT)} already exists")
    directory.mkdir(parents=True)
    manifest = f'''[project]
id = "{args.id}"
name = "{args.name}"
language = "{args.language}"
version = "{args.version}"
url = "{args.url}"
enabled = false

[build]
cwd = "{{project_dir}}"
# Replace this with one or more argv arrays. No shell parsing is involved.
commands = []

[run]
# Path relative to the repository root.
binary = "adapters/{args.id}/path/to/binary"
command = ["{{binary}}"]
workloads = ["entity_cycle", "add_remove", "iterate"]
'''
    (directory / "project.toml").write_text(manifest, encoding="utf-8")
    guide = f"""# {args.name} adapter

1. Add the {args.language} benchmark source and its normal build files here.
2. Implement the CLI and NDJSON contract from `../../docs/PROTOCOL.md`.
3. Fill `build.commands` and `run.binary` in `project.toml`.
4. Test the executable directly, then set `project.enabled = true`.
5. Run `./bench validate` and `./bench --quick --system {args.id}`.
"""
    (directory / "README.md").write_text(guide, encoding="utf-8")
    print(f"Created disabled adapter scaffold in {directory.relative_to(ROOT)}")
    print("Implement its binary, then set project.enabled = true.")


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="build, benchmark, graph, and publish")
    run_parser.add_argument("--quick", action="store_true", help="small local smoke run")
    run_parser.add_argument("--system", action="append", help="only this adapter id")
    run_parser.add_argument("--workload", action="append", help="only this workload id")
    run_parser.add_argument("--entities", type=int, action="append", help="override entity counts")
    run_parser.add_argument("--samples", type=int, help="override sample count")
    run_parser.add_argument("--warmup", type=int, help="override warmup iterations")
    run_parser.add_argument("--no-build", action="store_true", help="reuse existing binaries")
    run_parser.add_argument("--rounds", type=int, help="interleave samples in this many rounds")
    run_parser.add_argument("--cpu", type=int, help="pin adapters to this logical CPU")
    run_parser.add_argument("--no-pin", action="store_true", help="do not pin adapters")
    run_parser.add_argument(
        "--no-publish", action="store_true", help="keep results/latest and README untouched"
    )
    run_parser.add_argument(
        "--keep-going", action="store_true", help="continue after adapter failures"
    )
    build_parser = subparsers.add_parser("build", help="build adapters only")
    build_parser.add_argument("--system", action="append", help="only this adapter id")
    build_parser.add_argument("--keep-going", action="store_true")
    subparsers.add_parser("list", help="list discovered adapters and workloads")
    render_parser = subparsers.add_parser("render", help="re-render an existing run")
    render_parser.add_argument("run_dir", nargs="?")
    scaffold_parser = subparsers.add_parser(
        "scaffold", help="create a disabled adapter manifest"
    )
    scaffold_parser.add_argument("id", help="stable lowercase adapter id")
    scaffold_parser.add_argument("--name", required=True)
    scaffold_parser.add_argument("--language", required=True)
    scaffold_parser.add_argument("--version", required=True)
    scaffold_parser.add_argument("--url", required=True)
    subparsers.add_parser("validate", help="validate manifests and suite")
    return parser


def main() -> int:
    args = create_parser().parse_args()
    try:
        if args.command == "run":
            execute_run(args)
        elif args.command == "build":
            projects = select_projects(args.system)
            built = build_projects(projects, args.keep_going)
            print(f"\nBuilt {len(built)}/{len(projects)} adapter(s)")
        elif args.command == "validate":
            validate_repository()
        elif args.command == "render":
            render_existing(args.run_dir)
        elif args.command == "scaffold":
            scaffold_adapter(args)
        elif args.command == "list":
            settings, workloads = suite_config(False)
            print("Adapters:")
            for manifest in discover_projects(include_disabled=True):
                project = manifest["project"]
                state = "enabled" if project.get("enabled", True) else "disabled"
                print(
                    f"  {project['id']:<12} {project['name']:<20} "
                    f"{project['language']:<8} {project['version']} ({state})"
                )
            print(f"\nSuite: {settings['name']}")
            for workload in workloads:
                print(f"  {workload['id']:<16} {workload['description']}")
        return 0
    except (BenchError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
