#!/usr/bin/env python3
"""
Edu-V RFC Documentation Generator
Haalt RFC's op uit Jira en genereert een overzichtspagina + losse pagina per RFC.
Gebruik: python3 tools/generate_rfc_docs.py [output-map]
Vereist: token.secret in de project-root | rfc_config.yaml in de project-root
"""

import json
import os
import sys
import urllib.request
import base64
import yaml
from pathlib import Path
from datetime import date, datetime

# ── Configuratie ───────────────────────────────────────────────────────────────
JIRA_BASE    = "https://edu-v.atlassian.net"
JIRA_EMAIL   = "e.vanrijn@edu-v.org"
JIRA_PROJECT = "EDUVRFC"
MAX_RESULTS  = 200

STATUS_COLORS = {
    "Ingediend":       "#888",
    "Impactanalyse":   "#e07020",
    "In behandeling":  "#2176c7",
    "Goedgekeurd":     "#1a7a4a",
    "Afgewezen":       "#c0392b",
    "Geïmplementeerd": "#555",
    "Gesloten":        "#555",
}

def status_color(name):
    for key, col in STATUS_COLORS.items():
        if key.lower() in name.lower():
            return col
    return "#888"

def fmt_date(iso):
    try:
        return datetime.fromisoformat(iso[:10]).strftime("%-d %b %Y")
    except Exception:
        return iso[:10] if iso else ""

# ── Jira ───────────────────────────────────────────────────────────────────────
def jira_request(path, token, body=None):
    creds = base64.b64encode(f"{JIRA_EMAIL}:{token}".encode()).decode()
    method = "POST" if body else "GET"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        f"{JIRA_BASE}{path}",
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

def fetch_issues(token, visible_fields):
    # Haal altijd de basisvelden op voor de overzichtspagina
    base = ["summary", "status", "created", "updated"]
    fields = list(set(base + list(visible_fields.keys())))
    data = jira_request("/rest/api/3/search/jql", token, {
        "jql": f"project={JIRA_PROJECT} ORDER BY key DESC",
        "maxResults": MAX_RESULTS,
        "fields": fields,
    })
    return data.get("issues", [])

# ── ADF renderer ──────────────────────────────────────────────────────────────
def adf_to_html(node):
    if not node or not isinstance(node, dict):
        return ""
    t = node.get("type", "")
    content = node.get("content", [])

    if t == "doc":
        return "".join(adf_to_html(c) for c in content)
    if t == "paragraph":
        inner = "".join(adf_to_html(c) for c in content)
        return f"<p>{inner}</p>" if inner.strip() else ""
    if t == "text":
        txt = node.get("text", "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        for mark in node.get("marks", []):
            mt = mark.get("type", "")
            if mt == "strong":    txt = f"<strong>{txt}</strong>"
            elif mt == "em":      txt = f"<em>{txt}</em>"
            elif mt == "code":    txt = f"<code>{txt}</code>"
            elif mt == "underline": txt = f"<u>{txt}</u>"
            elif mt == "link":
                href = mark.get("attrs", {}).get("href", "#")
                txt = f'<a href="{href}" target="_blank">{txt}</a>'
        return txt
    if t == "hardBreak":
        return "<br>"
    if t in ("heading",):
        level = min(node.get("attrs", {}).get("level", 2) + 2, 6)
        inner = "".join(adf_to_html(c) for c in content)
        return f"<h{level}>{inner}</h{level}>"
    if t == "bulletList":
        items = "".join(adf_to_html(c) for c in content)
        return f"<ul>{items}</ul>"
    if t == "orderedList":
        items = "".join(adf_to_html(c) for c in content)
        return f"<ol>{items}</ol>"
    if t == "listItem":
        inner = "".join(adf_to_html(c) for c in content)
        return f"<li>{inner}</li>"
    if t == "blockquote":
        inner = "".join(adf_to_html(c) for c in content)
        return f"<blockquote>{inner}</blockquote>"
    if t == "codeBlock":
        inner = "".join(c.get("text", "") for c in content if c.get("type") == "text")
        return f"<pre><code>{inner}</code></pre>"
    if t == "rule":
        return "<hr>"
    if t == "mention":
        name = node.get("attrs", {}).get("text", "")
        return f"<em>{name}</em>"
    if t == "inlineCard":
        url = node.get("attrs", {}).get("url", "")
        return f'<a href="{url}" target="_blank">{url}</a>'
    # Onbekend node: probeer content te renderen
    return "".join(adf_to_html(c) for c in content)

# ── Veldwaarde renderen ────────────────────────────────────────────────────────
def render_value(field_id, value):
    if value is None:
        return ""
    # ADF beschrijvingsvelden
    if isinstance(value, dict) and value.get("type") == "doc":
        return adf_to_html(value)
    # Enkelvoudig object met name/value
    if isinstance(value, dict):
        for key in ("name", "value", "displayName", "accountName"):
            if key in value:
                v = str(value[key]).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                return v
        return str(value)
    # Lijst
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                for key in ("name", "value", "displayName"):
                    if key in item:
                        parts.append(str(item[key]))
                        break
            else:
                parts.append(str(item))
        return ", ".join(parts) if parts else ""
    # Datum
    if isinstance(value, str) and len(value) >= 10 and value[4] == "-" and value[7] == "-":
        return fmt_date(value)
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

# ── CSS ───────────────────────────────────────────────────────────────────────
BASE_CSS = """
    body { font-family: Arial, sans-serif; font-size: 13px; margin: 40px; color: #222; background: white; max-width: 1100px; }
    h1 { font-size: 20px; color: #2176c7; margin-bottom: 4px; }
    h2 { font-size: 15px; color: #2176c7; margin: 28px 0 6px; border-bottom: 1px solid #e0e8f0; padding-bottom: 4px; }
    .meta { color: #888; font-size: 11px; margin-bottom: 16px; }
    .badges { margin-bottom: 28px; display: flex; gap: 8px; flex-wrap: wrap; }
    table { width: 100%; border-collapse: collapse; font-size: 12px; }
    th { background: #2176c7; color: white; text-align: left; padding: 8px 12px; }
    td { padding: 7px 12px; border-bottom: 1px solid #eee; vertical-align: top; }
    tr:hover { background: #f9f9f9; }
    .badge { display: inline-block; padding: 2px 8px; border-radius: 3px; font-size: 10px; font-weight: bold; white-space: nowrap; color: white; }
    .field-label { font-size: 11px; color: #888; font-weight: bold; text-transform: uppercase; letter-spacing: 0.4px; margin-top: 16px; margin-bottom: 2px; }
    .field-value { font-size: 13px; color: #222; }
    .field-value p { margin: 4px 0; }
    .field-value ul, .field-value ol { margin: 4px 0; padding-left: 20px; }
    .field-value pre { background: #f5f5f5; padding: 8px; border-radius: 3px; overflow-x: auto; font-size: 11px; }
    .field-value blockquote { border-left: 3px solid #ccc; margin: 4px 0; padding-left: 10px; color: #555; }
    .field-value a { color: #2176c7; }
    .nav { margin-bottom: 24px; font-size: 12px; }
    .nav a { color: #2176c7; text-decoration: none; }
    .footer { margin-top: 40px; font-size: 11px; color: #aaa; border-top: 1px solid #eee; padding-top: 12px; }
    .rfc-key { font-size: 12px; color: #888; font-family: monospace; margin-bottom: 8px; }
    .rfc-title { font-size: 20px; font-weight: bold; color: #222; margin: 0 0 10px; line-height: 1.4; }
    .disclaimer { font-style: italic; color: #666; font-size: 12px; margin-bottom: 28px; }
    .status-tbl { width: auto; min-width: 400px; margin: 8px 0 32px; }
    .status-tbl th { background: transparent; color: #222; border-bottom: 2px solid #ddd; font-weight: bold; }
    .status-tbl td:first-child { color: #555; width: 180px; }
    .contact-note { margin-top: 32px; padding-top: 12px; border-top: 1px solid #eee; font-size: 12px; color: #555; }
"""

# ── Overzichtspagina ──────────────────────────────────────────────────────────
def generate_index(issues, output_path):
    by_status = {}
    for issue in issues:
        s = issue["fields"]["status"]["name"]
        by_status.setdefault(s, []).append(issue)

    status_counts = {s: len(v) for s, v in by_status.items()}
    total = len(issues)

    rows = []
    for issue in issues:
        f       = issue["fields"]
        key     = issue["key"]
        summary = f.get("summary", "")
        status  = f["status"]["name"]
        updated = fmt_date(f.get("updated", ""))
        created = fmt_date(f.get("created", ""))
        color   = status_color(status)

        rows.append(f"""    <tr>
      <td><a href="{key}.html" style="color:#2176c7;text-decoration:none;font-family:monospace;">{key}</a></td>
      <td>{summary}</td>
      <td><span class="badge" style="background:{color};">{status}</span></td>
      <td style="font-size:11px;color:#888;">{created}</td>
      <td style="font-size:11px;color:#888;">{updated}</td>
    </tr>""")

    badges = " ".join(
        f'<span style="background:{status_color(s)};color:white;padding:3px 10px;border-radius:3px;font-size:11px;">{s} <strong>{n}</strong></span>'
        for s, n in sorted(status_counts.items(), key=lambda x: -x[1])
    )

    html = f"""<!DOCTYPE html>
<html lang="nl">
<head>
  <meta charset="UTF-8">
  <title>Edu-V RFC Overzicht</title>
  <style>{BASE_CSS}</style>
</head>
<body>
<h1>Edu-V RFC Overzicht</h1>
<div class="meta">Gegenereerd op {date.today().strftime("%-d %B %Y")} &nbsp;|&nbsp; {total} RFC's &nbsp;|&nbsp; Bron: Jira project {JIRA_PROJECT}</div>
<div class="badges">{badges}</div>
<table>
  <thead>
    <tr>
      <th style="width:110px;">RFC</th>
      <th>Titel</th>
      <th style="width:140px;">Status</th>
      <th style="width:90px;">Ingediend</th>
      <th style="width:90px;">Gewijzigd</th>
    </tr>
  </thead>
  <tbody>
{"".join(rows)}
  </tbody>
</table>
<div class="footer">Edu-V Afsprakenstelsel &nbsp;|&nbsp; www.edu-v.org</div>
</body>
</html>"""

    with open(output_path, "w") as fh:
        fh.write(html)

# Velden die in de vaste statustabel staan — niet opnieuw renderen in de veldenlijst
_STATUS_TABLE_FIELDS = {"summary", "status", "customfield_10059", "customfield_10371", "created"}

# ── Individuele RFC-pagina ────────────────────────────────────────────────────
def generate_rfc_page(issue, visible_fields, output_path):
    f        = issue["fields"]
    key      = issue["key"]
    summary  = f.get("summary", "")
    status   = f["status"]["name"]
    color    = status_color(status)
    jira_url = f"{JIRA_BASE}/browse/{key}"

    # RFC-type: voorkeur voor platte-tekst variant, anders het selectieveld
    rfc_type = (
        render_value("customfield_10371", f.get("customfield_10371"))
        or render_value("customfield_10059", f.get("customfield_10059"))
    )
    datum_aangemaakt = fmt_date(f.get("created", ""))

    status_table = f"""<h2>Status</h2>
<table class="status-tbl">
  <thead><tr><th>Onderdeel</th><th></th></tr></thead>
  <tbody>
    <tr><td>Status</td><td><span class="badge" style="background:{color};">{status}</span></td></tr>
    <tr><td>RFC-type</td><td>{rfc_type}</td></tr>
    <tr><td>Datum aangemaakt</td><td>{datum_aangemaakt}</td></tr>
    <tr><td>Datum release</td><td></td></tr>
  </tbody>
</table>"""

    sections = []
    for field_id, cfg in visible_fields.items():
        if field_id in _STATUS_TABLE_FIELDS:
            continue
        value = f.get(field_id)
        rendered = render_value(field_id, value)
        if not rendered:
            continue
        sections.append(f"""
  <div class="field-label">{cfg["label"]}</div>
  <div class="field-value">{rendered}</div>""")

    fields_html = "".join(sections)

    html = f"""<!DOCTYPE html>
<html lang="nl">
<head>
  <meta charset="UTF-8">
  <title>{key} — {summary}</title>
  <style>{BASE_CSS}</style>
</head>
<body>
<div class="nav"><a href="index.html">← RFC Overzicht</a></div>
<div class="rfc-key">{key} &nbsp;|&nbsp; <a href="{jira_url}" target="_blank" style="color:#2176c7;">Bekijk in Jira</a></div>
<div class="rfc-title">{summary}</div>
<p class="disclaimer">Deze pagina is automatisch gegenereerd en wordt bijgewerkt op basis van de actuele status van de RFC in de Edu-V RFC-tooling (Jira).</p>
{status_table}
{fields_html}
<div class="contact-note">Bij vragen over deze RFC, neem contact op via <a href="mailto:rfc@edu-v.org" style="color:#2176c7;">rfc@edu-v.org</a> en vermeld daarbij het RFC-nummer in de titel.</div>
<div class="footer">Edu-V Afsprakenstelsel &nbsp;|&nbsp; www.edu-v.org</div>
</body>
</html>"""

    with open(output_path, "w") as fh:
        fh.write(html)

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    root = Path(__file__).parent.parent
    token = os.environ.get("JIRA_TOKEN") or (root / "token.secret").read_text().strip()

    config_path = root / "rfc_config.yaml"
    config = yaml.safe_load(config_path.read_text())
    visible_fields = {
        fid: cfg
        for fid, cfg in config["fields"].items()
        if cfg.get("visible", False)
    }

    output_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "docs" / "rfc"
    output_dir.mkdir(parents=True, exist_ok=True)

    print("RFC's ophalen uit Jira...")
    issues = fetch_issues(token, visible_fields)
    print(f"  {len(issues)} RFC's gevonden")

    print("Overzichtspagina genereren...")
    generate_index(issues, output_dir / "index.html")

    print("Individuele pagina's genereren...")
    for issue in issues:
        key = issue["key"]
        generate_rfc_page(issue, visible_fields, output_dir / f"{key}.html")

    print(f"Klaar. {len(issues) + 1} bestanden in {output_dir}/")


if __name__ == "__main__":
    main()
