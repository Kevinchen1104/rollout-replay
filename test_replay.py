import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from make_examples import FLAG, cohort, environment, feature
from replay import Snapshot, compare, main, read_cohort


class ReplayTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.old = environment("channel", "pilot")
        self.new = environment("region", "west")
        self.rows = cohort()

    def write(self, name, obj, encoding="utf-8"):
        path = self.root / name
        path.write_text(json.dumps(obj, ensure_ascii=False), encoding=encoding)
        return path

    def run_comparison(self, left=None, right=None, rows=None, limit=None):
        old = Snapshot(self.write("old.json", self.old if left is None else left))
        new = Snapshot(self.write("new.json", self.new if right is None else right))
        return compare(old, new, self.rows if rows is None else rows, FLAG, limit)

    def test_same_totals_different_people(self):
        with patch("requests.sessions.Session.request", side_effect=AssertionError("network call")):
            result = self.run_comparison(limit=10)
        self.assertEqual((result["enabled_before"], result["enabled_after"]), (100, 100))
        self.assertEqual(result["transitions"], {"on_to_off": 50, "off_to_on": 50})
        self.assertEqual((result["changed"], result["unchanged"], result["review"]),
                         (100, 100, "threshold_exceeded"))

    def test_unchanged_and_threshold_equality(self):
        self.assertEqual(self.run_comparison(right=self.old, limit=0)["changed"], 0)
        self.assertEqual(self.run_comparison(limit=50)["review"], "within_threshold")

    def test_reversed_rows_same_result(self):
        self.assertEqual(self.run_comparison(), self.run_comparison(rows=self.rows[::-1]))

    def test_identity_override_takes_precedence(self):
        self.new["identity_overrides"] = [{"identifier": "demo-001", "identity_features": [feature(False)]}]
        result = self.run_comparison()
        self.assertEqual(result["transitions"], {"on_to_off": 50, "off_to_on": 49})

    def test_missing_flags_are_a_distinct_state(self):
        self.new["feature_states"] = []
        self.new["project"]["segments"] = []
        result = self.run_comparison()
        self.assertEqual(result["transitions"], {"off_to_absent": 100, "on_to_absent": 100})
        self.assertEqual(self.run_comparison(left=self.new, right=self.old)["changed"], 200)
        with self.assertRaisesRegex(ValueError, "absent from both"):
            self.run_comparison(left=self.new, right=self.new)

    def test_values_and_variants(self):
        for doc in [self.old, self.new]:
            doc["project"]["segments"] = []
            doc["feature_states"] = [feature(True, value=False)]
        self.new["feature_states"][0]["feature_state_value"] = 0
        self.assertEqual(self.run_comparison()["transitions"], {"enabled_assignment_changed": 200})
        for doc, arm in [(self.old, "first"), (self.new, "second")]:
            doc["feature_states"][0]["multivariate_feature_state_values"] = [{
                "id": 1, "percentage_allocation": 100,
                "multivariate_feature_option": {"key": arm, "value": "same text"}}]
        self.assertEqual(self.run_comparison()["transitions"], {"enabled_assignment_changed": 200})
        for doc in [self.old, self.new]:
            doc["feature_states"][0]["enabled"] = False
        self.assertEqual(self.run_comparison()["changed"], 0)

    def test_multivariate_allocation_is_deterministic(self):
        self.old["project"]["segments"] = []
        self.old["feature_states"] = [feature(True)]
        self.old["feature_states"][0]["multivariate_feature_state_values"] = [
            {"id": n, "percentage_allocation": 50,
             "multivariate_feature_option": {"value": value, "key": value}}
            for n, value in [(1, "left"), (2, "right")]]
        doc = Snapshot(self.write("split.json", self.old))
        variants = {doc.get(FLAG, row).variant for row in self.rows}
        self.assertEqual(variants, {"left", "right"})
        self.assertEqual(self.run_comparison(right=self.old)["changed"], 0)

    def test_environment_mismatch(self):
        self.new["api_key"] = "another-synthetic-environment"
        with self.assertRaisesRegex(ValueError, "share one environment"):
            self.run_comparison()

    def test_rejects_invalid_cohort(self):
        for obj in [[], {}, [None], [{}], [{"identifier": "  "}], self.rows[:1] * 2,
                    [{"identifier": "x", "traits": {"region": []}}],
                    [{"identifier": "x", "traits": {"number": float("nan")}}]]:
            with self.subTest(obj=obj), self.assertRaises(ValueError):
                read_cohort(self.write("bad.json", obj))

    def test_unicode_files_and_private_report(self):
        self.rows[0]["identifier"] = "測試身分"
        result = self.run_comparison(rows=read_cohort(self.write("user.json", self.rows, "utf-16")))
        text = json.dumps(result, ensure_ascii=False)
        for private_field in ["測試身分", "demo-", "synthetic-environment", "pilot", "region"]:
            self.assertNotIn(private_field, text)

    def test_cli_read_contract(self):
        completed = subprocess.CompletedProcess([], 0, json.dumps(self.old).encode(), b"")
        with patch("shutil.which", return_value="/local/bin/flagsmith"), patch("subprocess.run", return_value=completed) as run:
            snap = Snapshot("@current")
        self.assertTrue(snap.get(FLAG, self.rows[0]).state == "on")
        run.assert_called_once_with(["/local/bin/flagsmith", "environment", "document", "--no-input"],
                                    check=True, capture_output=True, timeout=30)

    def test_cli_error_is_actionable(self):
        with patch("subprocess.run", side_effect=FileNotFoundError()), self.assertRaisesRegex(
                ValueError, "CLI installation"):
            Snapshot("@current")

    def test_actual_cli_entrypoint(self):
        args = [str(self.write("old", self.old)), str(self.write("new", self.new)),
                str(self.write("people", self.rows)), "--flag", FLAG]
        with contextlib.redirect_stdout(io.StringIO()) as stream:
            self.assertEqual(main(args + ["--json", "--max-changed-percent", "10"]), 3)
        self.assertEqual(json.loads(stream.getvalue())["changed_percent"], 50)
        with contextlib.redirect_stdout(io.StringIO()) as stream:
            self.assertEqual(main(args), 0)
        self.assertIn("100 of 200", stream.getvalue())
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as err:
            main(args + ["--max-changed-percent", "-1"])
        self.assertEqual(err.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
