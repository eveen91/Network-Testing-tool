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
