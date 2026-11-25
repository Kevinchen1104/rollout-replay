# Rollout Replay

A change to checkout targeting can leave the number of enabled customers exactly the same while moving half the audience. Rollout Replay compares the assignments of the **same identities** under two Flagsmith environment documents. A release reviewer or coding agent gets a transition count and an exit code for its review policy.

## Run the example

Use Python 3.10+ in a virtual environment. Install the SDK once. The bundled example then runs offline.

```shell
python -m pip install -r requirements.txt
python replay.py examples/before.json examples/after.json examples/cohort.json --flag expedited_checkout
python -m unittest -v test_replay
```

The original rule grants early access to pilot customers. The candidate selects the west region. Both enable 100 of 200 synthetic accounts. The tool reports 50 newly included and 50 newly excluded. The four combinations of region and channel have 50 accounts each. Regenerate all three fixtures with `python make_examples.py`.

## Use it in a release review

1. Keep two environment documents from the same Flagsmith environment. To capture the current one with the official CLI, run `flagsmith environment document --no-input > before.json` from a configured CLI context. A candidate document can be a local copy edited to represent the proposed change.
2. Prepare a local JSON array of identities with optional flat traits, for example `[{"identifier":"demo-001","traits":{"region":"west"}}]`. Supply representative cohorts. Missing traits or unrepresentative samples will affect the answer. Keep real documents and identity files private.
3. Pick a flag and a maximum acceptable percentage of changed assignments, expressed as a whole number from 0 to 100. Pass `--json` for machine-readable output. A reviewer decides whether to change the rollout or accept the impact.

```shell
python replay.py before.json candidate.json cohort.json --flag expedited_checkout --max-changed-percent 10 --json
```

To compare the currently selected CLI environment directly with a local candidate, pass `"@current"` as the first argument. This explicitly invokes the official read-only environment-document command. It requires a locally installed, authenticated Flagsmith CLI. The fetched document stays in process memory. File-to-file comparisons use the SDK in offline mode throughout.

| Exit | Meaning |
| --- | --- |
| 0 | The comparison succeeded. Any configured change limit was met. |
| 2 | The inputs or the CLI capture need attention. |
| 3 | The observed change exceeds the configured limit and needs human review. |

The comparison counts entering or leaving the rollout and the addition or removal of a flag. For people with the flag enabled on both sides, a changed variant key or typed value counts once. Disabled payloads are ignored, so the tool models clients that gate access on the enabled bit. It checks equality before rounding the reported percentage. The output contains only the requested flag name and aggregate measurements. It neither uploads the cohort nor applies a rollout.

## How Flagsmith fits

The official Python SDK evaluates segment rules, identity overrides and multivariate assignments for each identity. Rollout Replay supplies complete local documents through the SDK's offline-handler interface, calls `get_identity_flags`, and compares the resulting flags. The CLI integration reads the same document format.

### Reproduce the CLI integration check

With the official Flagsmith CLI v2.0.0 installed, pass the path to its executable:

```shell
python cli_integration.py /path/to/flagsmith
```

The check starts a temporary HTTP server on the loopback interface. It supplies a synthetic environment and targets that server with the real CLI. A direct document capture must match the bundled fixture. The test then runs the full `@current` command twice. With a 10% limit the original rule returns 0 (0 assignments changed) and the proposed rule returns 3 (100 of 200 changed). These checks exercise the client integration against controlled responses. Flagsmith Cloud and production authentication were outside this test.

- [Flagsmith CLI document command](https://flagsmith.github.io/flagsmith-cli/environment/document/)
- [Flagsmith Python SDK](https://github.com/Flagsmith/flagsmith-python-client)

Built with AI coding assistance. All bundled identities and configuration examples are synthetic.
