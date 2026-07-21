import json

def generate_markdown_table(diff_report):
    markdown = "| Test ID | Device | Status | Summary of change | Caveats |\n"
    markdown += "|---------|--------|--------|-------------------|---------|\n"

    for entry in diff_report:
        test_id = entry["test_id"]
        device = entry["device"]
        status = entry["status"]

        changes_summary = []
        if entry.get("changes"):
            for change in entry["changes"]:
                if entry["comparison_type"] == "structured":
                    changes_summary.append(f"{change['field']}: {change['before']} -> {change['after']}")
                else:
                    changes_summary.append(change["diff"])
        changes_summary = "\n".join(changes_summary)

        caveats = ", ".join(entry.get("caveats", []))

        markdown += f"| {test_id} | {device} | {status} | {changes_summary} | {caveats} |\n"

    return markdown

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate a human-readable summary from diff report.")
    parser.add_argument("--report", required=True, help="Path to the diff_report.json")

    args = parser.parse_args()

    with open(args.report, 'r') as file:
        diff_report = json.load(file)

    markdown_output = generate_markdown_table(diff_report)

    print(markdown_output)
