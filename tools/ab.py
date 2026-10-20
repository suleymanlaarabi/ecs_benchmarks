#!/usr/bin/env python3
"""A/B comparison of two Siecs revisions on the benchmark workloads.

Both sides are built from an amalgamation generated with the Siecs
`tools/rebuild_distr.sh` script, compiled with the same adapter and flags, pinned
to the same CPU and run in alternating rounds. The report gives the median ratio
B/A with a bootstrap confidence interval, so a change is only called faster or
slower when the interval excludes 1.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import pathlib
import random
import shutil
import statistics
import subprocess
import sys
import tarfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import bench  # noqa: E402

ROOT = bench.ROOT
AB_ROOT = ROOT / "build" / "ab"
ADAPTERS = {"siecs": "siecs-bench", "siecs-cpp": "siecs-cpp-bench"}


def git(siecs: pathlib.Path, *args: str, binary: bool = False):
    proc = subprocess.run(
        ["git", "-C", str(siecs), *args],
        check=True,
        stdout=subprocess.PIPE,
        text=not binary,
    )
    return proc.stdout if binary else proc.stdout.strip()


def tree_from_ref(siecs: pathlib.Path, ref: str) -> pathlib.Path:
    commit = git(siecs, "rev-parse", "--verify", f"{ref}^{{commit}}")
    tree = AB_ROOT / f"src-{commit[:12]}"
    if not (tree / "src").is_dir():
        if tree.exists():
            shutil.rmtree(tree)
        tree.mkdir(parents=True)
        archive = git(siecs, "archive", "--format=tar", commit, binary=True)
        with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
            stream.extractall(tree, filter="data")
    return tree


def working_tree_key(siecs: pathlib.Path) -> str:
    digest = hashlib.sha256()
    for folder in ("src", "include", "tools"):
        for path in sorted((siecs / folder).rglob("*")):
            if path.is_file():
                digest.update(str(path.relative_to(siecs)).encode())
                digest.update(path.read_bytes())
    digest.update((siecs / "project.json").read_bytes())
    return digest.hexdigest()[:12]


def build_side(
    name: str, tree: pathlib.Path, key: str, adapters: list[str]
) -> dict[str, pathlib.Path]:
    distr = AB_ROOT / f"distr-{key}"
    if not (distr / "distr" / "siecs.c").is_file():
        print(f"[{name}] generating amalgamation from {tree}", flush=True)
        subprocess.run(
            ["bash", str(ROOT / "tools" / "siecs_distr.sh"), str(tree), str(distr)], check=True
        )
    env = {"SIECS_DISTR_ROOT": str(distr), "SIECS_BENCH_VERSION": name}
    binaries = {}
    for adapter in adapters:
        build_dir = AB_ROOT / f"build-{name}-{adapter}"
        bench.run_command(
            ["cmake", "-S", str(ROOT / "adapters" / adapter), "-B", str(build_dir),
             "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release",
             f"-DSIECS_ROOT={ROOT.parent / 'siecs'}"],
            cwd=ROOT, env=env, quiet=True, capture=True,
        )
        bench.run_command(
            ["cmake", "--build", str(build_dir)], cwd=ROOT, env=env, quiet=True, capture=True
        )
        binaries[adapter] = build_dir / ADAPTERS[adapter]
    return binaries


def run(binary: pathlib.Path, workload: str, entities: int, iterations: int,
        samples: int, warmup: int, cpu: int | None) -> list[float]:
    result = bench.run_command(
        [str(binary), "--workload", workload, "--entities", str(entities),
         "--iterations", str(iterations), "--samples", str(samples),
         "--warmup", str(warmup)],
        cwd=ROOT, capture=True, quiet=True, cpu=cpu,
    )
    return [
        float(json.loads(line)["ns_per_iteration"])
        for line in result.stdout.splitlines()
        if line
    ]


def bootstrap_ratio(a: list[float], b: list[float], rounds: int = 4000) -> tuple[float, float]:
    rng = random.Random(0x5EC5)
    ratios = sorted(
        statistics.median(rng.choices(b, k=len(b)))
        / statistics.median(rng.choices(a, k=len(a)))
        for _ in range(rounds)
    )
    return ratios[int(0.025 * rounds)], ratios[int(0.975 * rounds) - 1]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--siecs", default=str(ROOT.parent / "siecs"), help="Siecs repository")
    parser.add_argument("--base", default="HEAD", help="git ref for side A (default HEAD)")
    parser.add_argument("--head", help="git ref for side B (default: the working tree)")
    parser.add_argument("--adapter", action="append", choices=sorted(ADAPTERS),
                        help="adapter(s), default siecs")
    parser.add_argument("--workload", action="append", help="workload id(s), default all")
    parser.add_argument("--entities", type=int, action="append", help="entity count(s)")
    parser.add_argument("--samples", type=int, default=20, help="samples per side")
    parser.add_argument("--rounds", type=int, default=10, help="alternating rounds")
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--cpu", type=int, help="logical CPU to pin (default from suite.toml)")
    args = parser.parse_args()

    siecs = pathlib.Path(args.siecs).resolve()
    settings, workloads = bench.suite_config(False)
    cpu = settings["cpu"] if args.cpu is None else args.cpu
    bench.check_machine(cpu)
    adapters = args.adapter or ["siecs"]
    if args.workload:
        workloads = [w for w in workloads if w["id"] in set(args.workload)]
    entity_counts = args.entities or settings["entities"]

    base_tree = tree_from_ref(siecs, args.base)
    side_a = build_side("base", base_tree, base_tree.name.removeprefix("src-"), adapters)
    if args.head:
        head_tree = tree_from_ref(siecs, args.head)
        side_b = build_side("head", head_tree, head_tree.name.removeprefix("src-"), adapters)
    else:
        side_b = build_side("head", siecs, "wt-" + working_tree_key(siecs), adapters)

    rounds = max(1, min(args.rounds, args.samples))
    print(f"\nA = {args.base}, B = {args.head or 'working tree'}; cpu {cpu}; "
          f"{args.samples} samples per side in {rounds} rounds\n")
    print(f"{'adapter':<10} {'workload':<13} {'entities':>9} {'A median ns':>14} "
          f"{'B median ns':>14} {'B/A':>7}  95% CI")
    for adapter in adapters:
        for workload in workloads:
            for entities in entity_counts:
                a: list[float] = []
                b: list[float] = []
                for index in range(rounds):
                    count = args.samples // rounds + (1 if index < args.samples % rounds else 0)
                    order = [(side_a, a), (side_b, b)]
                    if index % 2:
                        order.reverse()
                    for side, out in order:
                        out += run(side[adapter], workload["id"], entities,
                                   int(workload["iterations"]), count, args.warmup, cpu)
                ratio = statistics.median(b) / statistics.median(a)
                low, high = bootstrap_ratio(a, b)
                verdict = "faster" if high < 1 else "slower" if low > 1 else "same"
                print(f"{adapter:<10} {workload['id']:<13} {entities:>9,} "
                      f"{statistics.median(a):>14,.1f} {statistics.median(b):>14,.1f} "
                      f"{ratio:>7.3f}  [{low:.3f}, {high:.3f}] {verdict}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
