"""Generate deterministic synthetic Flagsmith environment documents and a cohort."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "examples"
FLAG = "expedited_checkout"


def feature(enabled, state_id=1, value=None):
    return {
        "enabled": enabled,
        "feature": {"id": 19, "name": FLAG},
        "feature_state_value": value,
        "featurestate_uuid": f"00000000-0000-4000-8000-{state_id:012d}",
        "multivariate_feature_state_values": [],
    }


def environment(trait, target):
    override = feature(True, 2)
    override["feature_segment"] = {"priority": 1}
    return {
        "name": "Synthetic checkout preview", "api_key": "synthetic-environment",
        "feature_states": [feature(False)], "identity_overrides": [],
        "project": {"segments": [{
            "id": 8, "name": "Early access audience",
            "rules": [{"type": "ALL", "conditions": [
                {"operator": "EQUAL", "property_": trait, "value": target}
            ], "rules": []}], "feature_states": [override],
        }]},
    }


def cohort():
    return [{
        "identifier": f"demo-{n:03d}",
        "traits": {
            "channel": "pilot" if n % 2 == 0 else "general",
            "region": "west" if n % 4 < 2 else "east",
        },
    } for n in range(200)]


if __name__ == "__main__":
    ROOT.mkdir(exist_ok=True)
    examples = {"before": environment("channel", "pilot"), "after": environment("region", "west"),
                "cohort": cohort()}
    for name, data in examples.items():
        (ROOT / f"{name}.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
