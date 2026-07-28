import importlib.util
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("bench_module", ROOT / "tools" / "bench.py")
assert SPEC and SPEC.loader
BENCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BENCH)


class BenchTests(unittest.TestCase):
    def test_summary_uses_median_and_p95(self):
        records = [
            {
                "workload": "iterate",
                "entities": 1000,
                "system": "x",
                "system_version": "1",
                "language": "C",
                "ns_per_iteration": value,
            }
            for value in [30.0, 10.0, 20.0]
        ]
        summary = BENCH.summarize(records)
        self.assertEqual(len(summary), 1)
        self.assertEqual(summary[0]["median_ns"], 20.0)
        self.assertEqual(summary[0]["mean_ns"], 20.0)
        self.assertEqual(summary[0]["p95_ns"], 29.0)

    def test_readme_marker_replacement_is_stable(self):
        original = f"before\n{BENCH.README_BEGIN}\nold\n{BENCH.README_END}\nafter\n"
        replaced = BENCH.replace_readme_section(original, "new")
        self.assertEqual(
            replaced,
            f"before\n{BENCH.README_BEGIN}\n\nnew\n\n{BENCH.README_END}\nafter\n",
        )

    def test_record_validation_accepts_valid_data(self):
        manifest = {
            "project": {"id": "x", "version": "1", "language": "C"}
        }
        workload = {"id": "iterate"}
        record = {
            "protocol": BENCH.PROTOCOL,
            "system": "x",
            "system_version": "1",
            "language": "C",
            "workload": "iterate",
            "entities": 10,
            "iterations": 5,
            "sample": 0,
            "duration_ns": 100,
            "ns_per_iteration": 20.0,
            "checksum": 45.0,
        }
        BENCH.validate_record(record, manifest, workload, 10, 5, 1, 1)

    def test_repository_manifests_validate(self):
        BENCH.validate_repository()


if __name__ == "__main__":
    unittest.main()
