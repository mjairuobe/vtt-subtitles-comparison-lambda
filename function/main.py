import base64
import io
import json
import re
import zipfile
from dataclasses import dataclass
from email.parser import BytesParser
from email.policy import default
from typing import Dict, Iterable, List, Optional, Set, Tuple


TIMING_LINE_RE = re.compile(
    r"^(?P<start>(?:\d{2}:)?\d{2}:\d{2}[.,]\d{3})\s*-->\s*"
    r"(?P<end>(?:\d{2}:)?\d{2}:\d{2}[.,]\d{3})(?P<settings>.*)$"
)
WORD_RE = re.compile(r"\b[\w'-]+\b", flags=re.UNICODE)
SUPPORTED_TEXT_SUFFIXES = (".vtt", ".txt")

OLDER_GROUP_FIELD_NAMES = {
    "older_files",
    "older",
    "old_files",
    "old",
}
NEWER_GROUP_FIELD_NAMES = {
    "newer_files",
    "newer",
    "new_files",
    "new",
}

HOME_PAGE_HTML = """<!doctype html>
<html lang="de">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>VTT Vergleich</title>
    <style>
      :root {
        color-scheme: light dark;
        --bg: #0b1220;
        --panel: #131c2f;
        --panel-soft: #1a2740;
        --border: #334155;
        --text: #f8fafc;
        --muted: #cbd5e1;
        --accent: #2563eb;
        --ok: #16a34a;
        --warn: #f59e0b;
      }
      * {
        box-sizing: border-box;
      }
      body {
        margin: 0;
        font-family: Arial, sans-serif;
        background: radial-gradient(circle at top, #16213a, var(--bg) 40%);
        color: var(--text);
      }
      main {
        max-width: 1080px;
        margin: 0 auto;
        padding: 1.5rem 1rem 3rem;
      }
      .card {
        border: 1px solid var(--border);
        border-radius: 12px;
        padding: 1rem;
        background: var(--panel);
      }
      .stack {
        display: grid;
        gap: 1rem;
      }
      h1,
      h2,
      h3 {
        margin-top: 0;
      }
      p,
      li,
      label {
        line-height: 1.45;
      }
      .hint {
        color: var(--muted);
      }
      .grid-2 {
        display: grid;
        gap: 1rem;
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
      .upload-grid {
        display: grid;
        gap: 1rem;
        margin-top: 0.5rem;
      }
      .upload-field {
        border: 1px solid var(--border);
        border-radius: 10px;
        padding: 0.8rem;
        background: var(--panel-soft);
      }
      input[type="file"] {
        width: 100%;
        margin-top: 0.35rem;
        border: 1px solid #475569;
        border-radius: 8px;
        padding: 0.6rem;
        background: #0f172a;
        color: var(--text);
      }
      .actions {
        display: flex;
        gap: 0.6rem;
        flex-wrap: wrap;
      }
      button {
        border: 0;
        border-radius: 8px;
        padding: 0.7rem 0.95rem;
        background: var(--accent);
        color: #fff;
        font-weight: 700;
        cursor: pointer;
      }
      button.secondary {
        background: #334155;
      }
      button[disabled] {
        opacity: 0.6;
        cursor: not-allowed;
      }
      .status {
        min-height: 1.35rem;
        color: var(--muted);
      }
      .status.error {
        color: #fda4af;
      }
      .status.ok {
        color: #86efac;
      }
      .metric-table {
        width: 100%;
        border-collapse: collapse;
        font-size: 0.95rem;
      }
      .metric-table th,
      .metric-table td {
        border-bottom: 1px solid var(--border);
        text-align: left;
        padding: 0.45rem 0.3rem;
      }
      .tag {
        display: inline-block;
        border-radius: 999px;
        padding: 0.14rem 0.5rem;
        font-size: 0.8rem;
      }
      .tag.pos {
        background: rgba(22, 163, 74, 0.22);
        color: #86efac;
      }
      .tag.neg {
        background: rgba(239, 68, 68, 0.22);
        color: #fda4af;
      }
      .tag.neu {
        background: rgba(148, 163, 184, 0.2);
        color: #cbd5e1;
      }
      .list-box {
        border: 1px solid var(--border);
        background: #0f172a;
        border-radius: 8px;
        padding: 0.65rem;
        max-height: 220px;
        overflow: auto;
      }
      .mono {
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      }
      @media (max-width: 820px) {
        .grid-2 {
          grid-template-columns: 1fr;
        }
      }
      @media (max-width: 640px) {
        main {
          padding: 1rem 0.75rem 2rem;
        }
        .card {
          padding: 0.8rem;
        }
        .actions {
          flex-direction: column;
        }
        .actions button {
          width: 100%;
        }
        .metric-table {
          display: block;
          overflow-x: auto;
          white-space: nowrap;
        }
      }
    </style>
  </head>
  <body>
    <main class="stack">
      <section class="card stack">
        <h1>VTT-Vergleichsfrontend</h1>
        <p class="hint">
          Standardansicht ist die UI. Du kannst hier zwei Versionen direkt vergleichen
          und das JSON jederzeit herunterladen.
        </p>
        <ul>
          <li>Felder: <code>older_files</code> und <code>newer_files</code></li>
          <li>Formate: <code>.vtt</code>, <code>.txt</code>, <code>.zip</code></li>
          <li>Zeitstempel werden über Start/Ende verglichen</li>
          <li>Gruppenvergleich für <code>sum/min/max/avg</code> ist enthalten</li>
          <li>Leere Dateien werden explizit gelistet</li>
        </ul>
      </section>

      <section class="card stack">
        <h2>Dateien hochladen</h2>
        <form id="compare-form" method="post" enctype="multipart/form-data">
          <div class="upload-grid">
            <label class="upload-field">
              Ältere Version (older_files)
              <input name="older_files" type="file" accept=".vtt,.txt,.zip" multiple required />
            </label>
            <label class="upload-field">
              Neuere Version (newer_files)
              <input name="newer_files" type="file" accept=".vtt,.txt,.zip" multiple required />
            </label>
          </div>
          <div class="actions">
            <button id="submit-button" type="submit">Vergleich anzeigen</button>
            <button id="download-template-json" class="secondary" type="button">
              Beispiel-JSON herunterladen
            </button>
            <button id="download-result-json" class="secondary" type="button" disabled>
              Ergebnis-JSON herunterladen
            </button>
          </div>
        </form>
        <p id="status" class="status"></p>
        <noscript>
          <p class="hint">
            Ohne JavaScript wird das Formular normal abgeschickt und die JSON-Antwort
            direkt im Browser angezeigt.
          </p>
        </noscript>
      </section>

      <section class="card stack" id="comparison-panel">
        <h2>Vergleich</h2>
        <div id="comparison-content" class="hint">
          Noch kein Vergleich durchgeführt.
        </div>
      </section>
    </main>

    <script>
      (() => {
        const form = document.getElementById("compare-form");
        const submitButton = document.getElementById("submit-button");
        const statusNode = document.getElementById("status");
        const resultDownloadButton = document.getElementById("download-result-json");
        const templateDownloadButton = document.getElementById("download-template-json");
        const comparisonContent = document.getElementById("comparison-content");
        let lastResult = null;

        const downloadJson = (filename, value) => {
          const blob = new Blob([JSON.stringify(value, null, 2)], {
            type: "application/json;charset=utf-8",
          });
          const url = URL.createObjectURL(blob);
          const link = document.createElement("a");
          link.href = url;
          link.download = filename;
          document.body.appendChild(link);
          link.click();
          link.remove();
          URL.revokeObjectURL(url);
        };

        const escapeHtml = (value) =>
          String(value)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");

        const formatValue = (value) => {
          if (typeof value === "number") {
            return Number.isInteger(value) ? String(value) : value.toFixed(3);
          }
          return String(value);
        };

        const deltaTag = (delta) => {
          if (delta > 0) {
            return `<span class="tag pos">+${formatValue(delta)}</span>`;
          }
          if (delta < 0) {
            return `<span class="tag neg">${formatValue(delta)}</span>`;
          }
          return `<span class="tag neu">${formatValue(delta)}</span>`;
        };

        const listItems = (items, emptyText) => {
          if (!items || items.length === 0) {
            return `<p class="hint">${escapeHtml(emptyText)}</p>`;
          }
          return `<ul class="mono">${items
            .map((item) => `<li>${escapeHtml(item)}</li>`)
            .join("")}</ul>`;
        };

        const renderGroupDetails = (title, group) => {
          const safeGroup = {
            uploaded_file_count: group?.uploaded_file_count ?? 0,
            expanded_vtt_file_count: group?.expanded_vtt_file_count ?? 0,
            empty_files: group?.empty_files ?? [],
            logical_file_names: group?.logical_file_names ?? [],
          };
          return `
          <section class="card stack">
            <h3>${title}</h3>
            <table class="metric-table">
              <tbody>
                <tr><th>Hochgeladene Dateien</th><td>${safeGroup.uploaded_file_count}</td></tr>
                <tr><th>Erkannte Untertiteldateien (VTT/TXT)</th><td>${safeGroup.expanded_vtt_file_count}</td></tr>
                <tr><th>Leere Dateien</th><td>${safeGroup.empty_files.length}</td></tr>
              </tbody>
            </table>
            <div>
              <h4>Dateinamen</h4>
              <div class="list-box">${listItems(safeGroup.logical_file_names, "Keine Dateien")}</div>
            </div>
            <div>
              <h4>Leere Dateien</h4>
              <div class="list-box">${listItems(safeGroup.empty_files, "Keine leeren Dateien")}</div>
            </div>
          </section>
        `;
        };

        const renderComparison = (payload) => {
          const agg = payload.word_aggregate_comparison || {};
          const ts = payload.summary || {};
          const aggregateRows = [
            { key: "sum", label: "Summe aller Wörter über alle Zeitstempel" },
            { key: "min", label: "Minimale Wörteranzahl pro Zeitstempel" },
            { key: "max", label: "Maximale Wörteranzahl pro Zeitstempel" },
            { key: "avg", label: "Durchschnittliche Wörteranzahl pro Zeitstempel" },
          ];

          comparisonContent.innerHTML = `
            <section class="stack">
              <h3>Übersicht</h3>
              <table class="metric-table">
                <thead>
                  <tr><th>Metrik</th><th>Älter</th><th>Neuer</th><th>Delta</th></tr>
                </thead>
                <tbody>
                  <tr>
                    <th>Zeitstempel gesamt</th>
                    <td>${ts.timestamp_count?.older ?? 0}</td>
                    <td>${ts.timestamp_count?.newer ?? 0}</td>
                    <td>${deltaTag((ts.timestamp_count?.newer ?? 0) - (ts.timestamp_count?.older ?? 0))}</td>
                  </tr>
                  <tr>
                    <th>Eindeutige Zeitstempel</th>
                    <td>${ts.unique_timestamp_count?.older ?? 0}</td>
                    <td>${ts.unique_timestamp_count?.newer ?? 0}</td>
                    <td>${deltaTag((ts.unique_timestamp_count?.newer ?? 0) - (ts.unique_timestamp_count?.older ?? 0))}</td>
                  </tr>
                  <tr>
                    <th>Weggefallene Zeitstempel</th>
                    <td colspan="3">${ts.removed_timestamps_count ?? 0}</td>
                  </tr>
                  <tr>
                    <th>Hinzugefügte Zeitstempel</th>
                    <td colspan="3">${ts.added_timestamps_count ?? 0}</td>
                  </tr>
                </tbody>
              </table>
            </section>

            <section class="stack">
              <h3>Wortstatistik pro Zeitstempel (Gruppenvergleich)</h3>
              <table class="metric-table">
                <thead>
                  <tr><th>Kennzahl</th><th>Älter</th><th>Neuer</th><th>Delta</th></tr>
                </thead>
                <tbody>
                  ${aggregateRows.map((row) => `
                    <tr>
                      <th>${row.label}</th>
                      <td>${formatValue(agg[row.key]?.older ?? 0)}</td>
                      <td>${formatValue(agg[row.key]?.newer ?? 0)}</td>
                      <td>${deltaTag(agg[row.key]?.delta ?? 0)}</td>
                    </tr>
                  `).join("")}
                </tbody>
              </table>
            </section>

            <section class="grid-2">
              ${renderGroupDetails("Ältere Gruppe", payload.older_group || {})}
              ${renderGroupDetails("Neuere Gruppe", payload.newer_group || {})}
            </section>

            <section class="grid-2">
              <div class="card stack">
                <h3>Weggefallene Zeitstempel</h3>
                <div class="list-box">${listItems(payload.removed_timestamps, "Keine")}</div>
              </div>
              <div class="card stack">
                <h3>Hinzugefügte Zeitstempel</h3>
                <div class="list-box">${listItems(payload.added_timestamps, "Keine")}</div>
              </div>
            </section>
          `;
        };

        templateDownloadButton.addEventListener("click", () => {
          const example = {
            request_fields: ["older_files", "newer_files"],
            description: "Beispielhafte Struktur für Request/Response.",
            response_fields: [
              "summary.timestamp_count",
              "summary.unique_timestamp_count",
              "summary.removed_timestamps_count",
              "summary.added_timestamps_count",
              "word_aggregate_comparison",
              "older_group",
              "newer_group",
              "removed_timestamps",
              "added_timestamps",
            ],
          };
          downloadJson("vtt-compare-template.json", example);
        });

        resultDownloadButton.addEventListener("click", () => {
          if (!lastResult) {
            return;
          }
          downloadJson("vtt-compare-result.json", lastResult);
        });

        form.addEventListener("submit", async (event) => {
          event.preventDefault();
          statusNode.className = "status";
          statusNode.textContent = "Vergleich läuft...";
          submitButton.disabled = true;

          try {
            const response = await fetch(window.location.pathname, {
              method: "POST",
              body: new FormData(form),
            });
            const payload = await response.json();
            if (!response.ok) {
              throw new Error(payload.error || `Fehler (${response.status})`);
            }
            lastResult = payload;
            resultDownloadButton.disabled = false;
            renderComparison(payload);
            statusNode.className = "status ok";
            statusNode.textContent = "Vergleich erfolgreich aktualisiert.";
          } catch (error) {
            statusNode.className = "status error";
            statusNode.textContent = `Fehler: ${error.message}`;
          } finally {
            submitButton.disabled = false;
          }
        });
      })();
    </script>
  </body>
</html>
"""


@dataclass
class Cue:
    start_ms: int
    end_ms: int
    text_lines: List[str]


@dataclass
class UploadedFile:
    field_name: str
    file_name: str
    payload: bytes
    content_type: str


@dataclass
class GroupAnalysis:
    cues: List[Cue]
    file_word_counts: List[int]
    file_timestamp_counts: List[int]
    logical_file_names: List[str]
    empty_file_names: List[str]
    empty_logical_file_names: List[str]
    source_file_count: int
    expanded_vtt_file_count: int
    uploaded_file_names: List[str]


def parse_timestamp_to_ms(value: str) -> int:
    normalized = value.strip().replace(",", ".")
    parts = normalized.split(":")
    if len(parts) == 2:
        hours = 0
        minutes = int(parts[0])
        seconds_part = parts[1]
    elif len(parts) == 3:
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds_part = parts[2]
    else:
        raise ValueError(f"Invalid timestamp format: {value}")

    if "." not in seconds_part:
        raise ValueError(f"Invalid timestamp milliseconds: {value}")

    seconds_raw, milliseconds_raw = seconds_part.split(".", 1)
    seconds = int(seconds_raw)
    milliseconds = int(milliseconds_raw.ljust(3, "0")[:3])

    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + milliseconds


def format_timestamp(ms: int) -> str:
    hours, remainder = divmod(ms, 3600 * 1000)
    minutes, remainder = divmod(remainder, 60 * 1000)
    seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02}.{milliseconds:03}"


def parse_vtt(vtt_text: str) -> List[Cue]:
    text = vtt_text.replace("\r\n", "\n").replace("\r", "\n")
    if text.startswith("\ufeff"):
        text = text[1:]

    lines = text.split("\n")
    cues: List[Cue] = []
    index = 0

    while index < len(lines):
        current = lines[index].strip()

        if not current:
            index += 1
            continue

        if current.startswith("WEBVTT"):
            index += 1
            continue

        if current.startswith("NOTE"):
            index += 1
            while index < len(lines) and lines[index].strip():
                index += 1
            continue

        if current in {"STYLE", "REGION"}:
            index += 1
            while index < len(lines) and lines[index].strip():
                index += 1
            continue

        timing_match = TIMING_LINE_RE.match(current)
        if not timing_match and index + 1 < len(lines):
            timing_match = TIMING_LINE_RE.match(lines[index + 1].strip())
            if timing_match:
                index += 1

        if not timing_match:
            index += 1
            continue

        index += 1
        text_lines: List[str] = []
        while index < len(lines) and lines[index].strip():
            text_lines.append(lines[index])
            index += 1

        start_ms = parse_timestamp_to_ms(timing_match.group("start"))
        end_ms = parse_timestamp_to_ms(timing_match.group("end"))
        if end_ms <= start_ms:
            continue

        cues.append(Cue(start_ms=start_ms, end_ms=end_ms, text_lines=text_lines))

    return cues


def parse_text_file_to_cues(file_bytes: bytes, source_name: str) -> Tuple[List[Cue], bool]:
    try:
        text = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError(f"{source_name}: only UTF-8 encoded files are supported")

    if not text.strip():
        return [], True

    cues = parse_vtt(text)
    if not cues:
        raise ValueError(f"{source_name}: no valid VTT timestamps found")
    return cues, False


def count_words_in_cues(cues: List[Cue]) -> int:
    return sum(len(WORD_RE.findall(" ".join(cue.text_lines))) for cue in cues)


def read_cues_from_zip(zip_bytes: bytes, source_name: str) -> Tuple[List[Cue], int, List[str]]:
    cues: List[Cue] = []
    expanded_files = 0
    empty_file_names: List[str] = []

    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as archive:
            for info in sorted(archive.infolist(), key=lambda item: item.filename):
                if info.is_dir():
                    continue
                lowered_name = info.filename.lower()
                if not lowered_name.endswith(SUPPORTED_TEXT_SUFFIXES):
                    continue
                file_bytes = archive.read(info)
                parsed_cues, is_empty = parse_text_file_to_cues(
                    file_bytes, f"{source_name}:{info.filename}"
                )
                cues.extend(parsed_cues)
                if is_empty:
                    empty_file_names.append(f"{source_name}:{info.filename}")
                expanded_files += 1
    except zipfile.BadZipFile as exc:
        raise ValueError(f"{source_name}: invalid ZIP archive") from exc

    if expanded_files == 0:
        raise ValueError(
            f"{source_name}: ZIP must contain at least one .vtt or .txt subtitle file"
        )

    return cues, expanded_files, empty_file_names


def parse_multipart_form(body: bytes, content_type: str) -> Tuple[Dict[str, str], List[UploadedFile]]:
    if "multipart/form-data" not in (content_type or "").lower():
        raise ValueError("Content-Type must be multipart/form-data")

    mime_message = (
        f"Content-Type: {content_type}\r\n"
        "MIME-Version: 1.0\r\n"
        "\r\n"
    ).encode("utf-8") + body
    message = BytesParser(policy=default).parsebytes(mime_message)

    if not message.is_multipart():
        raise ValueError("Request body is not multipart")

    fields: Dict[str, str] = {}
    files: List[UploadedFile] = []

    for part in message.iter_parts():
        disposition = part.get("Content-Disposition", "")
        if "form-data" not in disposition:
            continue

        field_name = part.get_param("name", header="content-disposition")
        payload = part.get_payload(decode=True) or b""
        filename = part.get_filename()

        if filename is not None and field_name:
            files.append(
                UploadedFile(
                    field_name=field_name,
                    file_name=filename,
                    payload=payload,
                    content_type=(part.get_content_type() or "").lower(),
                )
            )
            continue

        if field_name:
            charset = part.get_content_charset() or "utf-8"
            fields[field_name] = payload.decode(charset, errors="replace").strip()

    return fields, files


def get_header(headers: Dict[str, str], key: str) -> Optional[str]:
    for header_key, header_value in (headers or {}).items():
        if header_key.lower() == key.lower():
            return header_value
    return None


def json_response(status_code: int, body: Dict[str, object]) -> Dict[str, object]:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Cache-Control": "no-store",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body),
    }


def html_response(status_code: int, html: str) -> Dict[str, object]:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "text/html; charset=utf-8",
            "Cache-Control": "no-store",
            "Access-Control-Allow-Origin": "*",
        },
        "body": html,
    }


def cors_preflight_response() -> Dict[str, object]:
    return {
        "statusCode": 204,
        "headers": {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Max-Age": "600",
        },
        "body": "",
    }


def detect_http_method(event: Dict[str, object]) -> str:
    request_context = event.get("requestContext") or {}
    if isinstance(request_context, dict):
        http_info = request_context.get("http") or {}
        if isinstance(http_info, dict) and http_info.get("method"):
            return str(http_info["method"]).upper()

    http_method = event.get("httpMethod")
    if http_method:
        return str(http_method).upper()

    if event.get("body") is not None:
        return "POST"
    return "GET"


def analyze_group(group_label: str, files: Iterable[UploadedFile]) -> GroupAnalysis:
    cues: List[Cue] = []
    file_word_counts: List[int] = []
    file_timestamp_counts: List[int] = []
    logical_file_names: List[str] = []
    empty_file_names: List[str] = []
    empty_logical_file_names: List[str] = []
    source_file_count = 0
    expanded_vtt_file_count = 0
    uploaded_file_names: List[str] = []

    for item in files:
        source_file_count += 1
        uploaded_file_names.append(item.file_name)

        lowered_name = item.file_name.lower()
        is_zip = lowered_name.endswith(".zip") or "zip" in item.content_type

        if is_zip:
            zip_cues, expanded_count, zip_empty_files = read_cues_from_zip(
                item.payload, item.file_name
            )
            cues.extend(zip_cues)
            file_word_counts.append(count_words_in_cues(zip_cues))
            file_timestamp_counts.append(len(zip_cues))
            logical_file_names.append(item.file_name)
            empty_file_names.extend(zip_empty_files)
            if not zip_cues:
                empty_logical_file_names.append(item.file_name)
            expanded_vtt_file_count += expanded_count
            continue

        if not lowered_name.endswith(SUPPORTED_TEXT_SUFFIXES):
            raise ValueError(
                f"{group_label}: unsupported file type '{item.file_name}'. "
                "Use .vtt, .txt or .zip."
            )

        parsed_cues, is_empty_file = parse_text_file_to_cues(item.payload, item.file_name)
        cues.extend(parsed_cues)
        file_word_counts.append(count_words_in_cues(parsed_cues))
        file_timestamp_counts.append(len(parsed_cues))
        logical_file_names.append(item.file_name)
        if is_empty_file:
            empty_file_names.append(item.file_name)
            empty_logical_file_names.append(item.file_name)
        expanded_vtt_file_count += 1

    return GroupAnalysis(
        cues=cues,
        file_word_counts=file_word_counts,
        file_timestamp_counts=file_timestamp_counts,
        logical_file_names=logical_file_names,
        empty_file_names=empty_file_names,
        empty_logical_file_names=empty_logical_file_names,
        source_file_count=source_file_count,
        expanded_vtt_file_count=expanded_vtt_file_count,
        uploaded_file_names=uploaded_file_names,
    )


def timestamp_key(cue: Cue) -> Tuple[int, int]:
    return cue.start_ms, cue.end_ms


def cue_word_count(cue: Cue) -> int:
    return len(WORD_RE.findall(" ".join(cue.text_lines)))


def summarize_words_per_timestamp(cues: List[Cue]) -> Dict[str, float]:
    if not cues:
        return {"sum": 0, "min": 0, "max": 0, "avg": 0.0}

    word_counts = [cue_word_count(cue) for cue in cues]
    total_words = sum(word_counts)
    return {
        "sum": total_words,
        "min": min(word_counts),
        "max": max(word_counts),
        "avg": round(total_words / len(word_counts), 3),
    }


def compare_aggregate_value(older_value: float, newer_value: float) -> Dict[str, float]:
    delta = newer_value - older_value
    if isinstance(older_value, float) or isinstance(newer_value, float):
        delta = round(delta, 3)
    return {
        "older": older_value,
        "newer": newer_value,
        "delta": delta,
    }


def list_group_files(files: List[UploadedFile], accepted_field_names: Set[str]) -> List[UploadedFile]:
    return [item for item in files if item.field_name in accepted_field_names]


def format_timestamps(values: Iterable[Tuple[int, int]]) -> List[str]:
    return [f"{format_timestamp(start)} --> {format_timestamp(end)}" for start, end in values]


def compare_groups(older_group: GroupAnalysis, newer_group: GroupAnalysis) -> Dict[str, object]:
    older_keys = {timestamp_key(cue) for cue in older_group.cues}
    newer_keys = {timestamp_key(cue) for cue in newer_group.cues}

    removed = sorted(older_keys - newer_keys)
    added = sorted(newer_keys - older_keys)

    older_words_per_timestamp = summarize_words_per_timestamp(older_group.cues)
    newer_words_per_timestamp = summarize_words_per_timestamp(newer_group.cues)
    word_aggregate_comparison = {
        "sum": compare_aggregate_value(
            older_words_per_timestamp["sum"], newer_words_per_timestamp["sum"]
        ),
        "min": compare_aggregate_value(
            older_words_per_timestamp["min"], newer_words_per_timestamp["min"]
        ),
        "max": compare_aggregate_value(
            older_words_per_timestamp["max"], newer_words_per_timestamp["max"]
        ),
        "avg": compare_aggregate_value(
            older_words_per_timestamp["avg"], newer_words_per_timestamp["avg"]
        ),
    }

    return {
        "summary": {
            "timestamp_count": {
                "older": len(older_group.cues),
                "newer": len(newer_group.cues),
            },
            "unique_timestamp_count": {
                "older": len(older_keys),
                "newer": len(newer_keys),
            },
            "removed_timestamps_count": len(removed),
            "added_timestamps_count": len(added),
            "empty_files_count": {
                "older": len(older_group.empty_logical_file_names),
                "newer": len(newer_group.empty_logical_file_names),
            },
            "empty_subtitle_files_count": {
                "older": len(older_group.empty_file_names),
                "newer": len(newer_group.empty_file_names),
            },
        },
        "older_group": {
            "uploaded_file_count": older_group.source_file_count,
            "expanded_vtt_file_count": older_group.expanded_vtt_file_count,
            "uploaded_file_names": older_group.uploaded_file_names,
            "logical_file_names": older_group.logical_file_names,
            "file_timestamp_counts": older_group.file_timestamp_counts,
            "file_word_counts": older_group.file_word_counts,
            "word_stats": older_words_per_timestamp,
            "word_stats_per_timestamp": older_words_per_timestamp,
            "empty_files": older_group.empty_file_names,
            "empty_logical_file_names": older_group.empty_logical_file_names,
        },
        "newer_group": {
            "uploaded_file_count": newer_group.source_file_count,
            "expanded_vtt_file_count": newer_group.expanded_vtt_file_count,
            "uploaded_file_names": newer_group.uploaded_file_names,
            "logical_file_names": newer_group.logical_file_names,
            "file_timestamp_counts": newer_group.file_timestamp_counts,
            "file_word_counts": newer_group.file_word_counts,
            "word_stats": newer_words_per_timestamp,
            "word_stats_per_timestamp": newer_words_per_timestamp,
            "empty_files": newer_group.empty_file_names,
            "empty_logical_file_names": newer_group.empty_logical_file_names,
        },
        "removed_timestamps": format_timestamps(removed),
        "added_timestamps": format_timestamps(added),
        "word_aggregate_comparison": word_aggregate_comparison,
    }


def handle_compare_request(event: Dict[str, object]) -> Dict[str, object]:
    headers = event.get("headers") or {}
    content_type = get_header(headers, "Content-Type") or ""
    body = event.get("body")

    if body is None:
        return json_response(400, {"error": "Request body is required"})

    try:
        if event.get("isBase64Encoded"):
            body_bytes = base64.b64decode(body)
        else:
            body_bytes = body.encode("utf-8")
    except Exception as exc:
        return json_response(400, {"error": f"Invalid request body encoding: {str(exc)}"})

    try:
        _, files = parse_multipart_form(body=body_bytes, content_type=content_type)
    except ValueError as exc:
        return json_response(400, {"error": str(exc)})

    older_files = list_group_files(files, OLDER_GROUP_FIELD_NAMES)
    newer_files = list_group_files(files, NEWER_GROUP_FIELD_NAMES)

    if not older_files:
        return json_response(
            400,
            {
                "error": (
                    "Missing files for older group. Use form field 'older_files' "
                    "(or alias: older, old_files, old)."
                )
            },
        )
    if not newer_files:
        return json_response(
            400,
            {
                "error": (
                    "Missing files for newer group. Use form field 'newer_files' "
                    "(or alias: newer, new_files, new)."
                )
            },
        )

    try:
        older_group = analyze_group("older_group", older_files)
        newer_group = analyze_group("newer_group", newer_files)
        comparison = compare_groups(older_group=older_group, newer_group=newer_group)
        return json_response(200, comparison)
    except ValueError as exc:
        return json_response(400, {"error": str(exc)})
    except Exception as exc:  # pragma: no cover
        return json_response(500, {"error": f"Unexpected error: {str(exc)}"})


def handler(event, context):
    method = detect_http_method(event or {})

    if method == "GET":
        return html_response(200, HOME_PAGE_HTML)

    if method == "OPTIONS":
        return cors_preflight_response()

    if method == "POST":
        return handle_compare_request(event or {})

    return json_response(
        405,
        {
            "error": (
                f"Method {method} not allowed. Use GET for frontend "
                "or POST for VTT comparison."
            )
        },
    )
