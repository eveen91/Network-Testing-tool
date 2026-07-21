import json
from argparse import ArgumentParser
import os
import shutil
import glob

def load_json_files(json_paths):
    data = {}
    for path in json_paths:
        with open(path, 'r') as file:
            data[path.split('/')[-1]] = json.load(file)
    return data

def generate_html_table(evaluation_report, diff_report, capture_manifests):
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Test Execution Report</title>
        <style>
            table {
                width: 100%;
                border-collapse: collapse;
            }
            th, td {
                border: 1px solid #ddd;
                padding: 8px;
            }
            th {
                background-color: #f2f2f2;
            }
            .pass {
                background-color: #d4edda;
            }
            .fail {
                background-color: #f8d7da;
            }
            .review {
                background-color: #fff3cd;
            }
        </style>
    </head>
    <body>
    """

    summary = get_summary(evaluation_report, diff_report)
    html_content += f"<h1>{summary}</h1>"
    
    if 'FAIL' in summary or any(entry.get("status") in ["only-in-pre", "only-in-post"] for entry in diff_report):
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
        device = entry["device"]
        test_id = entry["test_id"]
        section = entry["section"]
        description = entry["description"]
        verdict = entry["verdict"].upper()
        evidence_notes = entry.get("evidence", "") + " | " + entry.get("manual_notes", "")
        caveats = ", ".join(entry.get("caveats", []))

        row_class = {
            "PASS": "pass",
            "FAIL": "fail",
            "REVIEW": "review"
        }.get(verdict, "")

        html_content += f"""
        <tr class="{row_class}">
            <td>{test_id}</td>
            <td>{section}</td>
            <td>{device}</td>
            <td>{description}</td>
            <td>{verdict}</td>
            <td>{evidence_notes}</td>
            <td>{caveats}</td>
        </tr>
        """

    html_content += "</table></body></html>"
    
    return html_content

def generate_markdown_table(evaluation_report, diff_report, capture_manifests):
    md_content = """
# Test Execution Report
"""

    summary = get_summary(evaluation_report, diff_report)
    md_content += f"## {summary}\n"
    
    if 'FAIL' in summary or any(entry.get("status") in ["only-in-pre", "only-in-post"] for entry in diff_report):
        md_content += "## Review is required before closing the change!\n"

    md_content += """
| Test ID | Section | Device | Description | Verdict | Evidence/Notes | Caveats |
|---------|---------|--------|-------------|---------|----------------|---------|\n"""

    for entry in evaluation_report:
        device = entry["device"]
        test_id = entry["test_id"]
        section = entry["section"]
        description = entry["description"]
        verdict = entry["verdict"].upper()
        evidence_notes = entry.get("evidence", "") + " | " + entry.get("manual_notes", "")
        caveats = ", ".join(entry.get("caveats", []))

        md_content += f"| {test_id} | {section} | {device} | {description} | {verdict} | {evidence_notes} | {caveats} |\n"

    return md_content

def get_summary(evaluation_report, diff_report):
    counts = {"PASS": 0, "FAIL": 0, "REVIEW": 0}
    
    for entry in evaluation_report:
        counts[entry["verdict"].upper()] += 1
    
    summary_parts = []
    
    if counts['PASS'] > 0:
        summary_parts.append(f"{counts['PASS']} PASS")
    if counts['FAIL'] > 0:
        summary_parts.append(f"{counts['FAIL']} FAIL")
    if counts['REVIEW'] > 0:
        summary_parts.append(f"{counts['REVIEW']} REVIEW")
    
    return ", ".join(summary_parts)

def create_pir_package(ticket, evaluation_report, diff_report, capture_manifests):
    package_dir = f"pir_package_{ticket}"
    os.makedirs(package_dir, exist_ok=True)
    
    # Save HTML and Markdown reports
    with open(os.path.join(package_dir, f"report_{ticket}.html"), 'w') as file:
        file.write(generate_html_table(evaluation_report, diff_report, capture_manifests))
        
    with open(os.path.join(package_dir, f"report_{ticket}.md"), 'w') as file:
        file.write(generate_markdown_table(evaluation_report, diff_report, capture_manifests))
    
    # Copy JSON files
    json_files = ["evaluation_report.json", "diff_report.json"]
    for pre_post in ["pre", "post"]:
        manifest_path = os.path.join("captures", ticket, pre_post, "*", "capture_manifest.json")
        manifest_paths = glob.glob(manifest_path)
        
        if manifest_paths:
            src_path = manifest_paths[0]
            dst_path = os.path.join(package_dir, f"capture_manifest_{pre_post}.json")
            shutil.copy(src_path, dst_path)

    # Copy consolidated baseline text files
    for pre_post in ["baseline", "post"]:
        base_dir = os.path.join("captures", ticket, pre_post)
        for root, _, files in os.walk(base_dir):
            for file in files:
                if file.endswith("_consolidated.txt"):
                    src_path = os.path.join(root, file)
                    dst_path = os.path.join(package_dir, file)
                    shutil.copy(src_path, dst_path)

def main():
    parser = ArgumentParser(description="Generate reports from evaluation and diff data.")
    parser.add_argument("--ticket", required=True, help="Ticket number (e.g., CHG-12345)")
    
    args = parser.parse_args()

    ticket = args.ticket
    json_paths = [
        "evaluation_report.json",
        "diff_report.json",
        os.path.join("captures", ticket, "baseline", "*", "capture_manifest.json"),
        os.path.join("captures", ticket, "post", "*", "capture_manifest.json")
    ]

    evaluation_report, diff_report, pre_capture_manifest, post_capture_manifest = load_json_files(json_paths)

    # Assuming we have only one baseline and one post-capture manifest for simplicity
    if not all([evaluation_report, diff_report, pre_capture_manifest, post_capture_manifest]):
        raise ValueError("Missing required JSON files")

    html_content = generate_html_table(evaluation_report, diff_report, {"pre": pre_capture_manifest, "post": post_capture_manifest})
    md_content = generate_markdown_table(evaluation_report, diff_report, {"pre": pre_capture_manifest, "post": post_capture_manifest})

    # Save HTML and Markdown reports
    with open(f"report_{ticket}.html", 'w') as file:
        file.write(html_content)
        
    with open(f"report_{ticket}.md", 'w') as file:
        file.write(md_content)

    # Create PIR package
    create_pir_package(ticket, evaluation_report, diff_report, {"pre": pre_capture_manifest, "post": post_capture_manifest})

if __name__ == "__main__":
    main()
