"""Compare effective Flagsmith assignments for a fixed cohort in offline mode."""
import argparse
from collections import Counter
from dataclasses import dataclass
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys

from flagsmith import Flagsmith


def read_cohort(path):
    rows = json.loads(path.read_bytes())
    if not isinstance(rows, list) or not rows:
        raise ValueError("The cohort must be a nonempty JSON array.")
    seen = set()
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"Cohort row {index} must be an object.")
        identifier = row.get("identifier")
        if not isinstance(identifier, str) or not identifier.strip() or identifier in seen:
            raise ValueError(f"Cohort row {index} needs a nonempty, unique string identifier.")
        seen.add(identifier)
        traits = row.get("traits", {})
        if not isinstance(traits, dict) or any(
            not isinstance(value, (str, int, float, bool)) and value is not None
            or isinstance(value, float) and not math.isfinite(value)
            for value in traits.values()
        ):
            raise ValueError(f"Cohort row {index} needs scalar JSON traits.")
    return rows


@dataclass
class DocumentHandler:
    document: dict

    def get_environment(self):
        return self.document


def load_document(source):
    if source != "@current":
        return json.loads(Path(source).read_bytes())
    try:
        binary = shutil.which("flagsmith")
        if binary is None:
            raise FileNotFoundError("flagsmith")
        result = subprocess.run(
            [binary, "environment", "document", "--no-input"],
            capture_output=True, check=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError("Could not read the current environment with the Flagsmith CLI. "
                         "Check the CLI installation and active environment.") from error
    return json.loads(result.stdout)


class Snapshot:
    def __init__(self, source):
        try:
            document = load_document(source)
            self.environment_key = document["api_key"]
            if not isinstance(self.environment_key, str) or not self.environment_key:
                raise ValueError("Missing environment key.")
            self.features = {item["feature"]["name"] for item in document["feature_states"]}
            self.client = Flagsmith(offline_mode=True, offline_handler=DocumentHandler(document))
        except (TypeError, KeyError, AttributeError, IndexError) as error:
            raise ValueError("Invalid Flagsmith environment document.") from error

    def get(self, flag, row):
        if flag not in self.features:
            return Exposure("absent")
        flags = self.client.get_identity_flags(row["identifier"], row.get("traits", {}))
        result = flags.get_flag(flag)
        if not result.enabled:
            return Exposure("off")
        # Explicit type distinguishes a boolean from an integer with the same value.
        return Exposure("on", result.variant, type(result.value).__name__, result.value)


@dataclass(frozen=True)
class Exposure:
    state: str
    variant: str | None = None
    value_type: str | None = None
    value: str | float | int | bool | None = None


def compare(before, after, rows, flag, max_percent=None):
    if before.environment_key != after.environment_key:
        raise ValueError("Snapshots must share one environment key.")
    if flag not in before.features | after.features:
        raise ValueError("Requested flag is absent from both snapshots.")
    changes = Counter()
    before_on = after_on = 0
    for row in rows:
        left = before.get(flag, row)
        right = after.get(flag, row)
        before_on += left.state == "on"
        after_on += right.state == "on"
        if left.state != right.state:
            changes[f"{left.state}_to_{right.state}"] += 1
        elif left != right:
            changes["enabled_assignment_changed"] += 1

    count = len(rows)
    changed = changes.total()
    review = "informational"
    if max_percent is not None:
        review = "threshold_exceeded" if changed * 100 > max_percent * count else "within_threshold"
    return {
        "flag": flag,
        "identities": count,
        "enabled_before": before_on,
        "enabled_after": after_on,
        "changed": changed,
        "unchanged": count - changed,
        "changed_percent": round(100 * changed / count, 4),
        "transitions": dict(sorted(changes.items())),
        "max_changed_percent": max_percent,
        "review": review,
    }


def format_text(report):
    lines = [
        f"Flag: {report['flag']}",
        f"Enabled before / after: {report['enabled_before']} / {report['enabled_after']}",
        f"People whose assignment changed: {report['changed']} of {report['identities']} "
        f"({report['changed_percent']:g}%)",
    ]
    lines.extend(f"  {kind.replace('_', ' ')}: {n}" for kind, n in report["transitions"].items())
    if report["max_changed_percent"] is not None:
        lines.append(f"Limit: {report['max_changed_percent']}% | {report['review'].replace('_', ' ')}")
    return "\n".join(lines)


def main(args=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", help="Environment JSON file, or @current to read via the Flagsmith CLI")
    parser.add_argument("after", type=Path, help="Candidate environment JSON file")
    parser.add_argument("cohort", type=Path)
    parser.add_argument("--flag", required=True)
    parser.add_argument("--max-changed-percent", type=int, metavar="0..100")
    parser.add_argument("--json", action="store_true")
    options = parser.parse_args(args)
    if options.max_changed_percent is not None and not 0 <= options.max_changed_percent <= 100:
        parser.error("The percentage limit must be between 0 and 100.")
    try:
        report = compare(
            Snapshot(options.before), Snapshot(options.after), read_cohort(options.cohort),
            options.flag, options.max_changed_percent,
        )
    except (ValueError, OSError, UnicodeError) as error:
        parser.exit(2, f"Input error: {error}\n")
    print(json.dumps(report, indent=2) if options.json else format_text(report))
    return 3 if report["review"] == "threshold_exceeded" else 0


if __name__ == "__main__":
    sys.exit(main())
