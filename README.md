# Network Post-Change Validation Tool

Automates SSH/API execution of the post-change network validation test plan
(Check Point Gaia/ClusterXL + Aruba AOS-CX/VSX): connects to devices,
captures command output, diffs pre/post-change baselines, evaluates
pass/fail, generates reports, and optionally live-monitors abort criteria
during the change window.

**Every command below was actually run against this codebase before being
written down here** -- there should be no gap between what this README says
and what the scripts actually do.

---

## 1. Install dependencies

```sh
pip install -r requirements.txt
```

This installs `netmiko`, `paramiko`, `PyYAML`, `python-dotenv`, and
`requests` -- everything the codebase actually imports. Do not install
packages individually from memory; `requirements.txt` is the single source
of truth and will be kept in sync as the tool changes.

Python 3.11+ is expected.

---

## 2. Set up your device inventory (real IPs -- gitignored)

```sh
cp inventory.yaml.example inventory.yaml
```

Edit `inventory.yaml` and fill in your real device names, IPs, and
credential _references_ (env var names, not the credentials themselves).
`inventory.yaml` itself is gitignored -- it will never be committed. Only
`inventory.yaml.example` (placeholder IPs) is tracked in git.

Each device needs:

| Field                     | Required for         | Notes                                                                                                                                                                                                                                  |
| ------------------------- | -------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `name`                    | all                  | Used as the folder/filename prefix for all captured output                                                                                                                                                                             |
| `role`                    | all                  | `cp-cluster-member` or `aruba-vsx-node`                                                                                                                                                                                                |
| `ip`                      | all                  | Real management IP                                                                                                                                                                                                                     |
| `login`                   | all                  | SSH username                                                                                                                                                                                                                           |
| `password_env_var`        | all                  | Name of the env var holding the SSH password (see step 3)                                                                                                                                                                              |
| `expert_password_env_var` | **Check Point only** | Name of the env var holding the Gaia **expert-mode** password. Required -- most commands in `commands/checkpoint.yaml` run with `mode: expert`, and the connector will raise a clear error if this isn't set when it tries to elevate. |
| `ssh_key_path`            | optional             | Used instead of a password if the key exists                                                                                                                                                                                           |

---

## 3. Set up credentials

```sh
cp .env.example .env
```

Edit `.env` and fill in real values for every `*_env_var` name referenced in
your `inventory.yaml`. At minimum, for a Check Point device, you need
**both** its login password and its separate expert-mode password:

```
CHECKPOINT_DEVICE1_PASSWORD=your_login_password
CHECKPOINT_DEVICE1_EXPERT_PASSWORD=your_expert_password
ARUBA_DEVICE1_PASSWORD=your_aruba_password
```

`.env` is gitignored and will never be committed.

> **If this repository was ever public with real IPs committed to
> `inventory.yaml`:** removing them now (they're gitignored going forward)
> does not remove them from git history. Treat any previously-committed
> real IPs as exposed regardless of later commits, and consider the repo's
> visibility/history accordingly.

---

## 4. Test connectivity

```sh
python test_connectivity.py
```

Loads `inventory.yaml` and attempts to connect to every device, printing
success/failure per device. Run this before anything else -- if a device
fails here, nothing downstream will work either.

---

## 5. Set your scenario parameters

`scenario_params.yaml` holds the per-change values that get substituted
into parameterized commands (e.g. `show vlan {vlan_id}` -> `show vlan 200`):

```yaml
vlan_id: 200
subnet: "10.200.0.0/24"
vip: "10.200.0.1"
cp_member_1: "10.200.0.2"
cp_member_2: "10.200.0.3"
test_host_ip: "10.200.0.50"
dmz_db_target: "10.10.50.12"
dmz_db_port: 3306
mgmt_isolation_target: "10.0.0.15"
mgmt_isolation_port: 22
internet_target: "8.8.8.8"
```

Edit this file for each new change -- the command library itself never
needs to change, only these values.

---

## 6. Capture a baseline (pre-change and post-change)

`--phase` is **required** and must be exactly `pre` or `post` -- this is
what keeps the two runs in separate, distinct folders so every downstream
tool can find them.

```sh
# Before the change:
python capture.py --ticket CHG-12345 --phase pre --section 2.1,3.C,3.D,3.E --params scenario_params.yaml

# After the change:
python capture.py --ticket CHG-12345 --phase post --section 2.1,3.C,3.D,3.E --params scenario_params.yaml
```

Optional flags:

```sh
# Only run against a subset of devices (useful for testing):
python capture.py --ticket CHG-12345 --phase pre --section 2.1 --params scenario_params.yaml --devices cp_member_1,aruba_vsx_node

# Skip interactive prompts for manual-only commands (records them as "skipped" instead):
python capture.py --ticket CHG-12345 --phase pre --section 2.1,6 --params scenario_params.yaml --skip-manual
```

### Manual-only commands

Some tests (e.g. `T-22`, the planned failover test, and `T-13-review`, the
SmartConsole log review) can't be automated and require a human to confirm
they were executed. If you don't pass `--skip-manual`, capture.py will
interactively prompt for each one that falls within your requested
`--section` list:

```
T-22 -- Planned failover test. Confirm executed manually and add notes, or type 'skip':
```

These are ticket-level (not tied to any single device) and are stored
separately in the manifest under `manual_confirmations`.

### Output produced

Each run creates a new timestamped folder -- running the same `--phase`
twice does **not** overwrite the previous run:

```
captures/
└── CHG-12345/
    ├── pre/
    │   └── 20260730-105812/
    │       ├── capture_manifest.json
    │       ├── cp_member_1/
    │       │   ├── cp_member_1_T-01_20260730-105812.txt
    │       │   ├── cp_member_1_T-02_20260730-105812.txt
    │       │   └── cp_member_1_consolidated.txt
    │       └── aruba_vsx_node/
    │           ├── aruba_vsx_node_T-08_20260730-105812.txt
    │           └── aruba_vsx_node_consolidated.txt
    └── post/
        └── 20260730-112230/
            └── ... (same structure)
```

`capture_manifest.json` is the source of truth every other script reads --
it records, per device, per test ID: which section it belongs to, its risk
level, whether it captured successfully, whether it was time-bounded
(debug commands), and the exact output filename.

---

## 7. Compare pre vs. post

```sh
python diff.py --ticket CHG-12345
```

Auto-resolves the most recent `pre` and `post` runs for that ticket and
writes `diff_report.json`. Every `(device, test_id)` pair is compared and
tagged `changed`, `unchanged`, `only-in-pre`, `only-in-post`,
`not-diffable-manual` (manual-only entries are never diffed), or
`capture-file-missing`. Debug/bounded captures get an explicit
`debug-capture-caveat` note rather than being silently treated as reliable.

You can also compare arbitrary run directories directly instead of the
latest per ticket:

```sh
python diff.py --left captures/CHG-12345/pre/20260730-105812 --right captures/CHG-12345/post/20260730-112230
```

### Human-readable summary

```sh
python report_summary.py --report diff_report.json
```

Prints a quick Markdown table of every diffed test for a fast skim before
the full evaluation.

---

## 8. Evaluate pass/fail

```sh
python evaluate.py --ticket CHG-12345
```

Reads both manifests plus `diff_report.json` and writes
`evaluation_report.json` with a verdict per `(device, test_id)`:
`pass`, `fail`, or `manual-review-required`.

**Ambiguous or missing evidence never resolves to an automatic pass** --
this is deliberate. A test only gets an automated `pass`/`fail` verdict if
the command library defines a `pass_pattern`/`fail_pattern` for it (see
`commands/checkpoint.yaml`'s `T-01` for an example) and the captured output
actually matches. Everything else -- debug/bounded captures, manual-only
commands (including the ticket-level `T-22`/`T-13-review` confirmations),
tests with no defined pattern, and anything the diff marked as missing or
undiffable -- is always `manual-review-required`.

---

## 9. Generate the final report and PIR package

```sh
python report.py --ticket CHG-12345
```

Produces:

- `report_CHG-12345.html` and `report_CHG-12345.md` -- color-coded (HTML)
  or plain-text-labeled (Markdown) tables of every test, with a summary
  line and a review-required banner if anything failed or came back
  missing/undiffable.
- `pir_package_CHG-12345/` -- everything needed for the change record in
  one place: both reports, `evaluation_report.json`, `diff_report.json`,
  both phases' `capture_manifest.json`, and every device's consolidated
  output file.

---

## 10. (Optional) Live-monitor abort criteria during the change window

```sh
cp monitor_thresholds.yaml.example monitor_thresholds.yaml
# edit monitor_thresholds.yaml with your real devices/thresholds, then:
python monitor.py --ticket CHG-12345 --config monitor_thresholds.yaml
```

Polls devices on a loop (default 60s) and alerts on: ClusterXL split-brain
or state flapping, Check Point sync errors, BGP/OSPF neighbor loss
(persistent past a grace period, not on a single blip), VSX out-of-sync,
interface error-count spikes, VIP packet loss, and asymmetric-routing
kernel drops (a bounded `fw ctl zdebug` capture on its own much slower
interval, separate from the main poll loop). A device becoming unreachable
is itself treated as a "loss of management access" trigger.

**This tool never takes corrective action.** It only alerts (console bell +
message, or a webhook if `webhook_url` is set in the config) and logs every
poll cycle to `monitor_logs/<ticket>_monitor.log`, distinct from
`triggers.log` (alerts only). Rollback is always a human decision.

Not automated by this tool, per the underlying test plan -- these stay
manual: throughput degradation, security policy bypass (requires
SmartConsole log interpretation), global policy push failure, and the
maintenance-window time-limit trigger (set a personal timer for that one).

---

## Command library

- `commands/checkpoint.yaml` / `commands/aruba.yaml` -- per-device,
  per-test-ID command definitions (Sections 1-4), each tagged with a `risk`
  level (`read-only-safe`, `read-only-debug`, or referenced via
  `commands/manual.yaml` for anything requiring human judgment).
- `commands/manual.yaml` -- ticket-level manual confirmations (not tied to
  a specific device), e.g. the planned failover test.
- `noise_filters.yaml` -- regex patterns stripped from captured text before
  diffing, so normal fluctuation (timestamps, connection ages, byte
  counters) doesn't get reported as a meaningful change.

---

## Repository layout

```
.
├── inventory.yaml.example          # commit this; copy to inventory.yaml (gitignored)
├── monitor_thresholds.yaml.example # commit this; copy to monitor_thresholds.yaml (gitignored)
├── .env.example                    # commit this; copy to .env (gitignored)
├── requirements.txt
├── scenario_params.yaml            # per-change values, safe to commit (no secrets)
├── noise_filters.yaml
├── commands/
│   ├── checkpoint.yaml
│   ├── aruba.yaml
│   └── manual.yaml
├── connectors/
│   ├── checkpoint_conn.py          # SSH: clish + expert-mode elevation, bounded debug capture
│   └── aruba_conn.py               # SSH/CLI, with a small api-key -> CLI-command map
├── test_connectivity.py
├── capture.py                      # Section 1-4 command execution, writes capture_manifest.json
├── diff.py                         # pre vs. post comparison -> diff_report.json
├── report_summary.py               # quick Markdown skim of a diff report
├── evaluate.py                     # pass/fail/manual-review-required verdicts -> evaluation_report.json
├── report.py                       # final HTML/MD reports + PIR evidence package
├── monitor.py                      # live abort-criteria monitor during the change window
└── captures/                       # generated, gitignored
    └── <ticket>/<phase>/<timestamp>/
```

---

## Design constraints (non-negotiable)

1. **Read-only only.** No command anywhere in this codebase changes device
   configuration.
2. **Bounded debug sessions.** Any Check Point debug command (`fw ctl
zdebug`, `fw monitor`) has a hard timeout enforced in the connector
   itself, and explicitly sends Ctrl+C to stop the remote process --
   nothing is ever left running on the device after the timeout.
3. **No hardcoded credentials.** Everything real (`.env`, `inventory.yaml`,
   `monitor_thresholds.yaml`) is gitignored; only `.example` placeholder
   versions are tracked.
4. **No auto-remediation.** `monitor.py` only observes and alerts. It never
   executes a rollback or corrective action, under any circumstance.
5. **Ambiguous evidence never auto-passes.** `evaluate.py` defaults to
   `manual-review-required` whenever a verdict can't be determined with
   confidence -- see step 8 above.

---

## Troubleshooting

- **`error: the following arguments are required: --phase`** -- `--phase
pre` or `--phase post` is mandatory on every `capture.py` run.
- **Check Point commands failing / expert-mode errors** -- confirm
  `expert_password_env_var` is set in `inventory.yaml` for that device and
  the corresponding variable is filled in in `.env`.
- **`diff.py`/`evaluate.py`/`report.py` can't find a run** -- these
  auto-resolve the _latest_ `pre`/`post` run directory for a ticket; if you
  ran `capture.py` more than once, make sure the run you expect is really
  the most recent one, or pass an explicit path via `diff.py --left/--right`.
- **`ModuleNotFoundError`** -- run `pip install -r requirements.txt`, not a
  manual subset of packages.
