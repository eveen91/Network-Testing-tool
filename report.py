import json
from argparse import ArgumentParser
import os
import shutil
import glob


VERDICT_LABELS = {
    "pass": "PASS",
    "fail": "FAIL",
    "manual-review-required": "REVIEW",
}


def verdict_label(verdict):
    """
    The previous code did `entry["verdict"].upper()` and used that directly
    as a dict key against {"PASS": 0, "FAIL": 0, "REVIEW": 0}. Since
    evaluate.py's real verdict string is "manual-review-required",
    .upper() produces "MANUAL-REVIEW-REQUIRED" -- never a key in that dict,
    so get_summary() would KeyError on the first manual-review-required
    entry. This maps real verdict strings to display labels explicitly.
    """
    return VERDICT_LABELS.get(verdict, verdict.upper())


def find_latest_run_dir(ticket, phase):
    """Same helper as diff.py/evaluate.py -- duplicated so this script stays
    runnable standalone."""
    pattern = os.path.join("captures", ticket, phase, "*")
    candidates = [
        d for d in glob.glob(pattern)
        if os.path.isdir(d) and os.path.exists(os.path.join(d, "capture_manifest.json"))
    ]
    if not candidates:
        return None
    return sorted(candidates)[-1]


def load_json_file(path):
    if not os.path.exists(path):
        raise FileNotFoundError(f"Required file not found: {path}")
    with open(path, 'r') as file:
        return json.load(file)


def generate_html_table(evaluation_report, diff_report, capture_manifests):
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Test Execution Report</title>
        <style>
            table { width: 100%; border-collapse: collapse; }
            th, td { border: 1px solid #ddd; padding: 8px; }
            th { background-color: #f2f2f2; }
            .pass { background-color: #d4edda; }
            .fail { background-color: #f8d7da; }
            .review { background-color: #fff3cd; }
        </style>
    </head>
    <body>
    """

    summary = get_summary(evaluation_report)
    html_content += f"<h1>{summary}</h1>"

    if review_required(evaluation_report, diff_report):
        html_content += "<h2 style='color: red;'>Review is required before closing the change!</h2>"

    html_content += """
    <table>
        <tr>
            <th>Test ID</th>
            <th>Section</th>
            <th>Device</th>
            <th>Description</th>
            <th>Verdict</th>
            <th>Evidence/Notes</th>
            <th>Caveats</th>
        </tr>
    """

    for entry in evaluation_report:
        label = verdict_label(entry["verdict"])
        evidence_notes = " | ".join(
            filter(None, [entry.get("evidence", ""), entry.get("manual_notes") or ""])
        )
        caveats = ", ".join(entry.get("caveats", []))
        row_class = {"PASS": "pass", "FAIL": "fail", "REVIEW": "review"}.get(label, "")

        html_content += f"""
        <tr class="{row_class}">
            <td>{entry["test_id"]}</td>
            <td>{entry["section"]}</td>
            <td>{entry["device"]}</td>
            <td>{entry["description"]}</td>
            <td>{label}</td>
            <td>{evidence_notes}</td>
            <td>{caveats}</td>
        </tr>
        """

    html_content += "</table></body></html>"
    return html_content


def generate_markdown_table(evaluation_report, diff_report, capture_manifests):
    md_content = "# Test Execution Report\n"

    summary = get_summary(evaluation_report)
    md_content += f"## {summary}\n"

    if review_required(evaluation_report, diff_report):
        md_content += "## Review is required before closing the change!\n"

    md_content += (
        "\n| Test ID | Section | Device | Description | Verdict | Evidence/Notes | Caveats |\n"
        "|---------|---------|--------|-------------|---------|----------------|---------|\n"
    )

    for entry in evaluation_report:
        label = verdict_label(entry["verdict"])
        evidence_notes = " | ".join(
            filter(None, [entry.get("evidence", ""), entry.get("manual_notes") or ""])
        )
        caveats = ", ".join(entry.get("caveats", []))
        md_content += (
            f"| {entry['test_id']} | {entry['section']} | {entry['device']} | "
            f"{entry['description']} | {label} | {evidence_notes} | {caveats} |\n"
        )

    return md_content


def get_summary(evaluation_report):
    counts = {"PASS": 0, "FAIL": 0, "REVIEW": 0}
    for entry in evaluation_report:
        label = verdict_label(entry["verdict"])
        counts[label] = counts.get(label, 0) + 1

    summary_parts = [f"{count} {label}" for label, count in counts.items() if count > 0]
    return ", ".join(summary_parts) if summary_parts else "No test results"


def review_required(evaluation_report, diff_report):
    """
    Broadened to match every diff status evaluate.py itself treats as
    forcing manual-review-required, plus any FAIL verdict -- not just
    only-in-pre/only-in-post.
    """
    if any(verdict_label(entry["verdict"]) == "FAIL" for entry in evaluation_report):
        return True
    concerning_statuses = {"only-in-pre", "only-in-post", "capture-file-missing", "not-diffable-manual"}
    if any(entry.get("status") in concerning_statuses for entry in diff_report):
        return True
    return False


def create_pir_package(ticket, evaluation_report, diff_report, capture_manifests):
    package_dir = f"pir_package_{ticket}"
    os.makedirs(package_dir, exist_ok=True)

    with open(os.path.join(package_dir, f"report_{ticket}.html"), 'w') as file:
        file.write(generate_html_table(evaluation_report, diff_report, capture_manifests))

    with open(os.path.join(package_dir, f"report_{ticket}.md"), 'w') as file:
        file.write(generate_markdown_table(evaluation_report, diff_report, capture_manifests))

    for json_file in ("evaluation_report.json", "diff_report.json"):
        if os.path.exists(json_file):
            shutil.copy(json_file, os.path.join(package_dir, json_file))

    for phase in ("pre", "post"):
        run_dir = find_latest_run_dir(ticket, phase)
        if not run_dir:
            continue

        manifest_src = os.path.join(run_dir, "capture_manifest.json")
        if os.path.exists(manifest_src):
            shutil.copy(manifest_src, os.path.join(package_dir, f"capture_manifest_{phase}.json"))

        for root, _, files in os.walk(run_dir):
            for file in files:
                if file.endswith("_consolidated.txt"):
                    shutil.copy(os.path.join(root, file), os.path.join(package_dir, file))

    print(f"PIR evidence package written to {package_dir}/")


def main():
    parser = ArgumentParser(description="Generate reports from evaluation and diff data.")
    parser.add_argument("--ticket", required=True, help="Ticket number (e.g., CHG-12345)")
    parser.add_argument("--pre-phase", default="pre")
    parser.add_argument("--post-phase", default="post")
    parser.add_argument("--evaluation-report", default="evaluation_report.json")
    parser.add_argument("--diff-report", default="diff_report.json")
    args = parser.parse_args()

    ticket = args.ticket

    evaluation_report = load_json_file(args.evaluation_report)
    diff_report = load_json_file(args.diff_report)

    pre_run_dir = find_latest_run_dir(ticket, args.pre_phase)
    post_run_dir = find_latest_run_dir(ticket, args.post_phase)
    if not pre_run_dir or not post_run_dir:
        raise FileNotFoundError(
            f"Could not locate both a pre and post capture run for ticket {ticket}. "
            f"pre found: {bool(pre_run_dir)}, post found: {bool(post_run_dir)}"
        )
    pre_capture_manifest = load_json_file(os.path.join(pre_run_dir, "capture_manifest.json"))
    post_capture_manifest = load_json_file(os.path.join(post_run_dir, "capture_manifest.json"))

    capture_manifests = {"pre": pre_capture_manifest, "post": post_capture_manifest}

    html_content = generate_html_table(evaluation_report, diff_report, capture_manifests)
    md_content = generate_markdown_table(evaluation_report, diff_report, capture_manifests)

    with open(f"report_{ticket}.html", 'w') as file:
        file.write(html_content)

    with open(f"report_{ticket}.md", 'w') as file:
        file.write(md_content)

    create_pir_package(ticket, evaluation_report, diff_report, capture_manifests)

    print(f"Reports written: report_{ticket}.html, report_{ticket}.md")


if __name__ == "__main__":
    main()