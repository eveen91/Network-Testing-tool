import json
import os
import re
import glob
from argparse import ArgumentParser

import yaml


def find_latest_run_dir(ticket, phase):
    """Mirrors diff.py's helper -- duplicated intentionally so this script
    stays runnable standalone without importing diff.py."""
    pattern = os.path.join("captures", ticket, phase, "*")
    candidates = [
        d for d in glob.glob(pattern)
        if os.path.isdir(d) and os.path.exists(os.path.join(d, "capture_manifest.json"))
    ]
    if not candidates:
        raise FileNotFoundError(
            f"No completed capture run found for ticket='{ticket}' phase='{phase}' "
            f"(looked under {pattern})"
        )
    return sorted(candidates)[-1]


def load_manifest(run_dir):
    with open(os.path.join(run_dir, "capture_manifest.json"), 'r') as file:
        return json.load(file)


def load_diff_report(diff_path):
    if not os.path.exists(diff_path):
        print(f"WARNING: {diff_path} not found -- proceeding without diff cross-reference. "
              f"only-in-pre/only-in-post detection will not be available. Run diff.py first "
              f"for a complete evaluation.")
        return []
    with open(diff_path, 'r') as file:
        return json.load(file)


def load_pattern_library():
    """
    Loads pass_pattern/fail_pattern from both command YAML files into a
    single test_id lookup. Previously these were never loaded anywhere --
    evaluate_test_id() always received None for both, regardless of what
    the YAML defined.
    """
    library = {}
    for path in ("commands/checkpoint.yaml", "commands/aruba.yaml"):
        if not os.path.exists(path):
            continue
        with open(path, 'r') as f:
            entries = yaml.safe_load(f) or []
        for entry in entries:
            test_id = entry.get("test_id")
            if test_id:
                library[test_id] = {
                    "pass_pattern": entry.get("pass_pattern"),
                    "fail_pattern": entry.get("fail_pattern"),
                }
    return library


def read_output_text(run_dir, device_name, cmd_entry):
    output_file = cmd_entry.get("output_file")
    if not output_file:
        return None
    path = os.path.join(run_dir, device_name, output_file)
    if not os.path.exists(path):
        return None
    with open(path, 'r') as f:
        return f.read()


def check_patterns(raw_output, pass_pattern=None, fail_pattern=None):
    """Fail is checked first and takes priority -- a real fail signal must
    never be masked by a coincidental pass-pattern match elsewhere in the
    same output."""
    if raw_output is None:
        return None, "no captured output available to check"

    if fail_pattern:
        fail_match = re.search(fail_pattern, raw_output)
        if fail_match:
            return "fail", f"matched fail_pattern '{fail_pattern}': {fail_match.group(0)!r}"

    if pass_pattern:
        pass_match = re.search(pass_pattern, raw_output)
        if pass_match:
            return "pass", f"matched pass_pattern '{pass_pattern}': {pass_match.group(0)!r}"

    return None, "no pattern matched"


def evaluate_test_id(device_name, test_id, post_cmd, pattern_library, diff_entry=None,
                      post_run_dir=None, pre_cmd=None):
    """
    Verdict logic (highest-stakes part of the whole tool -- ambiguous or
    absent evidence must NEVER resolve to an auto-pass):

      1. manual-only -> always manual-review-required, human notes attached.
      2. read-only-debug -> always manual-review-required regardless of
         pattern match (capture may be time-truncated); pattern match is
         attached as supporting evidence only, never sets the verdict alone.
      3. read-only-safe with patterns -> check fail_pattern FIRST (priority
         over pass), then pass_pattern; neither matching -> manual-review-required.
      4. read-only-safe with no patterns defined at all -> manual-review-required,
         raw output included so a human has something to look at quickly.
      5. diff_report status of only-in-pre / only-in-post / capture-file-missing
         / not-diffable-manual overrides everything above -> manual-review-required.
    """
    result = {"verdict": None, "evidence": "", "manual_notes": None, "caveats": []}

    if post_cmd is None:
        result["verdict"] = "manual-review-required"
        result["evidence"] = "no post-change capture entry found for this test_id/device"
        return result

    if "output_file" not in post_cmd:
        result["verdict"] = "manual-review-required"
        result["manual_notes"] = post_cmd.get("notes", post_cmd.get("reason", ""))
        result["evidence"] = f"manual-only entry, status: {post_cmd.get('status', 'unknown')}"
        return result

    risk = post_cmd.get("risk", "unknown")
    raw_output = read_output_text(post_run_dir, device_name, post_cmd) if post_run_dir else None
    patterns = pattern_library.get(test_id, {})
    pass_pattern, fail_pattern = patterns.get("pass_pattern"), patterns.get("fail_pattern")

    if risk == "read-only-debug":
        match_result, evidence_text = check_patterns(raw_output, pass_pattern, fail_pattern)
        result["verdict"] = "manual-review-required"
        result["evidence"] = f"(debug/bounded capture -- pattern check is supporting evidence only) {evidence_text}"
        if post_cmd.get("truncated"):
            result["caveats"].append("capture was time-bounded and may be truncated")

    elif risk == "read-only-safe":
        if not pass_pattern and not fail_pattern:
            result["verdict"] = "manual-review-required"
            result["evidence"] = "no pass_pattern/fail_pattern defined for this test in the command library"
            if raw_output is not None:
                result["evidence"] += f" -- raw output: {raw_output[:500]!r}"
        else:
            match_result, evidence_text = check_patterns(raw_output, pass_pattern, fail_pattern)
            result["evidence"] = evidence_text
            result["verdict"] = match_result if match_result else "manual-review-required"

    else:
        result["verdict"] = "manual-review-required"
        result["evidence"] = f"unrecognized risk level '{risk}'"

    if diff_entry and diff_entry.get("status") in (
        "only-in-pre", "only-in-post", "capture-file-missing", "not-diffable-manual"
    ):
        result["verdict"] = "manual-review-required"
        result["caveats"].append(f"diff status: {diff_entry['status']} -- missing/undiffable evidence")

    return result


def main():
    parser = ArgumentParser(description="Evaluate test results from a network baseline capture.")
    parser.add_argument("--ticket", required=True, help="Ticket number (e.g., CHG-12345)")
    parser.add_argument("--pre-phase", default="pre")
    parser.add_argument("--post-phase", default="post")
    parser.add_argument("--diff-report", default="diff_report.json")
    parser.add_argument("--output", default="evaluation_report.json")
    args = parser.parse_args()

    pre_run_dir = find_latest_run_dir(args.ticket, args.pre_phase)
    post_run_dir = find_latest_run_dir(args.ticket, args.post_phase)
    print(f"Evaluating:\n  pre:  {pre_run_dir}\n  post: {post_run_dir}")

    pre_manifest = load_manifest(pre_run_dir)
    post_manifest = load_manifest(post_run_dir)
    diff_report = load_diff_report(args.diff_report)
    pattern_library = load_pattern_library()

    diff_index = {(e["device"], e["test_id"]): e for e in diff_report if e.get("test_id")}

    evaluation_report = []
    pre_devices = pre_manifest.get("per_device", {})
    post_devices = post_manifest.get("per_device", {})

    for device_name in sorted(set(pre_devices.keys()) | set(post_devices.keys())):
        pre_device = pre_devices.get(device_name, {})
        post_device = post_devices.get(device_name, {})
        pre_commands = pre_device.get("commands", {})
        post_commands = post_device.get("commands", {})

        all_test_ids = sorted(set(pre_commands.keys()) | set(post_commands.keys()))

        for test_id in all_test_ids:
            post_cmd = post_commands.get(test_id)
            pre_cmd = pre_commands.get(test_id)
            diff_entry = diff_index.get((device_name, test_id))

            result = evaluate_test_id(
                device_name, test_id, post_cmd, pattern_library,
                diff_entry=diff_entry, post_run_dir=post_run_dir, pre_cmd=pre_cmd
            )

            section = (post_cmd or pre_cmd or {}).get("section", "")
            description = (post_cmd or pre_cmd or {}).get("description", "")

            evaluation_report.append({
                "device": device_name,
                "test_id": test_id,
                "section": section,
                "description": description,
                "verdict": result["verdict"],
                "evidence": result["evidence"],
                "manual_notes": result["manual_notes"],
                "caveats": result["caveats"],
            })

    with open(args.output, 'w') as file:
        json.dump(evaluation_report, file, indent=4)

    pass_count = sum(1 for e in evaluation_report if e["verdict"] == "pass")
    fail_count = sum(1 for e in evaluation_report if e["verdict"] == "fail")
    review_count = sum(1 for e in evaluation_report if e["verdict"] == "manual-review-required")
    print(f"Evaluation complete: {pass_count} pass, {fail_count} fail, "
          f"{review_count} manual-review-required. Saved to {args.output}")


if __name__ == "__main__":
    main()