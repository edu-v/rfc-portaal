#!/usr/bin/env python3
"""
Edu-V RFC → Confluence publisher
Publiceert RFC-overzicht en losse RFC-pagina's naar Confluence.
Gebruik: python3 tools/publish_confluence.py
Vereist: token.secret in de project-root | rfc_config.yaml in de project-root
"""

import argparse
import json, os, base64, yaml, urllib.request
import sys
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).parent))
from generate_rfc_docs import fetch_issues, render_value, fmt_date

CONFLUENCE_BASE = "https://edu-v.atlassian.net/wiki"
JIRA_EMAIL      = "e.vanrijn@edu-v.org"
INDEX_PAGE_ID   = "1467482114"
SPACE_KEY       = "AFSPRAKENS"

STATUS_COLORS = {
    "Ingediend":       "#888",
    "Impactanalyse":   "#e07020",
    "In behandeling":  "#2176c7",
    "Goedgekeurd":     "#1a7a4a",
    "Afgewezen":       "#c0392b",
    "Geimplementeerd": "#555",
    "Gesloten":        "#555",
}

_STATUS_TABLE_FIELDS = {"summary", "status", "customfield_10059", "customfield_10371", "created"}


def badge(status):
    color = next((v for k, v in STATUS_COLORS.items() if k.lower() in status.lower()), "#888")
    return (
        f'<strong><span style="color:{color};">{status}</span></strong>'
    )


def conf_request(path, token, body=None, method="GET"):
    creds = base64.b64encode(f"{JIRA_EMAIL}:{token}".encode()).decode()
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        f"{CONFLUENCE_BASE}{path}",
        data=data,
        headers={
            "Authorization": f"Basic {creds}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method=method,
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def get_page(page_id, token):
    return conf_request(f"/rest/api/content/{page_id}?expand=version", token)


def list_children(parent_id, token):
    result = conf_request(
        f"/rest/api/content/{parent_id}/child/page?limit=500&expand=version",
        token,
    )
    return {p["title"]: p for p in result.get("results", [])}


def update_page(page_id, title, html, version, token):
    conf_request(
        f"/rest/api/content/{page_id}",
        token,
        body={
            "version": {"number": version},
            "title": title,
            "type": "page",
            "body": {"storage": {"representation": "storage", "value": html}},
        },
        method="PUT",
    )


def create_child_page(parent_id, title, html, token):
    return conf_request(
        "/rest/api/content",
        token,
        body={
            "type": "page",
            "title": title,
            "space": {"key": SPACE_KEY},
            "ancestors": [{"id": parent_id}],
            "body": {"storage": {"representation": "storage", "value": html}},
        },
        method="POST",
    )


def render_index_html(issues, links=None):
    rows = []
    for issue in issues:
        f         = issue["fields"]
        key       = issue["key"]
        summary   = f.get("summary", "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        status    = f["status"]["name"]
        updated   = fmt_date(f.get("updated", ""))
        created   = fmt_date(f.get("created", ""))
        werkgroep = render_value("customfield_10191", f.get("customfield_10191"))
        if links and key in links:
            key_cell = f'<td style="font-family:monospace;"><a href="{links[key]}">{key}</a></td>'
        else:
            key_cell = f'<td style="font-family:monospace;">{key}</td>'
        rows.append(
            f"<tr>"
            f"{key_cell}"
            f"<td>{summary}</td>"
            f"<td>{badge(status)}</td>"
            f'<td style="font-size:11px;color:#666;">{werkgroep}</td>'
            f'<td style="font-size:11px;color:#888;">{created}</td>'
            f'<td style="font-size:11px;color:#888;">{updated}</td>'
            f"</tr>"
        )

    return f"""<p>Welkom op het Edu-V RFC-portaal! Dit portaal is ingericht om inzicht te geven in wijzigingsverzoeken die we ontvangen voor het Edu-V afsprakenstelsel. Deze wijzigingsverzoeken noemen we een &#8220;request for change&#8221;, oftewel een RFC.</p>
<p>We vinden het belangrijk dat het RFC-proces transparant is voor alle geïnteresseerden. Enerzijds is het informatief voor deelnemers, anderzijds kunnen zo wijzigingen in het afsprakenstelsel gecontroleerd worden.</p>
<p>Een nieuwe RFC indienen? Dat kan via het <a href="https://edu-v.atlassian.net/servicedesk/customer/portal/67/create/104">RFC-formulier</a>.</p>
<p>Dit portaal is in ontwikkeling. Oude informatie wordt nog toegevoegd. Daarnaast is ook voor oudere RFC&#8217;s niet altijd alle informatie compleet. Bij vragen, neem contact op via <a href="mailto:rfc@edu-v.org">rfc@edu-v.org</a>.</p>
<p>Automatisch gesynchroniseerd vanuit Jira op {date.today().strftime("%-d %B %Y")}.
Totaal: <strong>{len(issues)}</strong> RFC's.</p>
<table style="width:100%;">
  <colgroup>
    <col style="width:10%;" />
    <col style="width:42%;" />
    <col style="width:13%;" />
    <col style="width:17%;" />
    <col style="width:9%;" />
    <col style="width:9%;" />
  </colgroup>
  <thead>
    <tr>
      <th>RFC</th><th>Titel</th><th>Status</th>
      <th>Werkgroep</th><th>Ingediend</th><th>Gewijzigd</th>
    </tr>
  </thead>
  <tbody>{"".join(rows)}</tbody>
</table>"""


def render_rfc_html(issue, visible_fields):
    f        = issue["fields"]
    key      = issue["key"]
    summary  = f.get("summary", "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    status   = f["status"]["name"]
    jira_url = f"https://edu-v.atlassian.net/browse/{key}"

    rfc_type = (
        render_value("customfield_10371", f.get("customfield_10371"))
        or render_value("customfield_10059", f.get("customfield_10059"))
    )
    datum = fmt_date(f.get("created", ""))

    sections = [
        f'<p><em>Automatisch gegenereerd vanuit <a href="{jira_url}">Jira {key}</a>.</em></p>'
        f"<h2>Status</h2>"
        f"<table><tbody>"
        f"<tr><td><strong>Status</strong></td><td>{badge(status)}</td></tr>"
        f"<tr><td><strong>RFC-type</strong></td><td>{rfc_type}</td></tr>"
        f"<tr><td><strong>Datum aangemaakt</strong></td><td>{datum}</td></tr>"
        f"</tbody></table>"
    ]

    for field_id, cfg in visible_fields.items():
        if field_id in _STATUS_TABLE_FIELDS:
            continue
        rendered = render_value(field_id, f.get(field_id))
        if not rendered:
            continue
        label = cfg["label"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        sections.append(f"<h2>{label}</h2>\n<div>{rendered}</div>")

    return "\n".join(sections)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Maximaal aantal RFC's verwerken (voor testdoeleinden)")
    args = parser.parse_args()

    root  = Path(__file__).parent.parent
    token_file = root / "token.secret"
    if not token_file.exists():
        token_file = root.parent / "token.secret"
    token = os.environ.get("JIRA_TOKEN") or token_file.read_text().strip()

    config      = yaml.safe_load((root / "rfc_config.yaml").read_text())
    visible_fields = {
        fid: cfg
        for fid, cfg in config["fields"].items()
        if cfg.get("visible", False)
    }

    print("RFC's ophalen uit Jira...")
    issues = fetch_issues(token, visible_fields)
    if args.limit:
        issues = issues[:args.limit]
        print(f"  {len(issues)} RFC's gevonden (beperkt tot {args.limit} voor test)")
    else:
        print(f"  {len(issues)} RFC's gevonden")

    print("RFC kindpagina's aanmaken/bijwerken...")
    children = list_children(INDEX_PAGE_ID, token)
    children_by_key = {}
    for title, page in children.items():
        parts = title.split(" — ", 1)
        if parts[0].strip().startswith("EDUVRFC-"):
            children_by_key[parts[0].strip()] = {
                "id": page["id"],
                "version": page["version"]["number"],
                "title": title,
            }

    links = {}
    for issue in issues:
        key     = issue["key"]
        summary = issue["fields"].get("summary", "")
        title   = f"{key} — {summary}"
        html    = render_rfc_html(issue, visible_fields)

        if key in children_by_key:
            child    = children_by_key[key]
            child_id = child["id"]
            update_page(child_id, title, html, child["version"] + 1, token)
            print(f"  Bijgewerkt: {key}")
        else:
            result   = create_child_page(INDEX_PAGE_ID, title, html, token)
            child_id = result["id"]
            print(f"  Aangemaakt: {key}")

        links[key] = f"{CONFLUENCE_BASE}/spaces/{SPACE_KEY}/pages/{child_id}"

    print("Confluence index-pagina bijwerken...")
    index_page    = get_page(INDEX_PAGE_ID, token)
    index_title   = index_page["title"]
    index_version = index_page["version"]["number"] + 1
    update_page(INDEX_PAGE_ID, index_title, render_index_html(issues, links), index_version, token)
    print(f"  '{index_title}' bijgewerkt (versie {index_version})")

    print("Klaar.")


if __name__ == "__main__":
    main()
