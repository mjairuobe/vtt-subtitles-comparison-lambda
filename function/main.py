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
      }
      body {
        margin: 0;
        font-family: Arial, sans-serif;
        background: #111827;
        color: #f9fafb;
      }
      main {
        max-width: 900px;
        margin: 0 auto;
        padding: 2rem 1rem 3rem;
      }
      .card {
        border: 1px solid #334155;
        border-radius: 12px;
        padding: 1.25rem;
        background: #1f2937;
      }
      h1 {
        margin-top: 0;
        margin-bottom: 0.5rem;
        font-size: 1.75rem;
      }
      form {
        display: grid;
        gap: 1rem;
        margin-top: 1rem;
      }
      p,
      li,
      label {
        line-height: 1.5;
      }
      input[type="file"] {
        width: 100%;
        box-sizing: border-box;
        border: 1px solid #475569;
        border-radius: 8px;
        padding: 0.65rem 0.75rem;
        background: #0f172a;
        color: #f8fafc;
      }
      button {
        border: 0;
        border-radius: 8px;
        padding: 0.75rem 1rem;
        background: #2563eb;
        color: #fff;
        font-weight: 700;
        cursor: pointer;
      }
      .hint {
        color: #cbd5e1;
      }
      .box {
        border: 1px solid #334155;
        border-radius: 8px;
        background: #0f172a;
        padding: 1rem;
      }
      code {
        background: #111827;
        border-radius: 4px;
        padding: 0.1rem 0.35rem;
      }
    </style>
  </head>
  <body>
    <main>
      <section class="card">
        <h1>VTT Versionsvergleich</h1>
        <p>
          Diese statische Seite beschreibt das Tool und bietet ein Uploadformular fuer
          den Vergleich von Untertitelversionen.
        </p>
        <div class="box">
          <p>
            Lade zwei Gruppen hoch: <strong>aeltere Version</strong> und
            <strong>aktuellere Version</strong>.
          </p>
          <ul>
            <li>Akzeptierte Formate: <code>.vtt</code>, <code>.txt</code>, <code>.zip</code></li>
            <li>
              ZIP-Dateien duerfen mehrere VTT/TXT enthalten und werden jeweils als
              eine logische Datei innerhalb der Gruppe ausgewertet.
            </li>
            <li>Verglichen werden nur Start-/Endzeiten der Timestamps.</li>
            <li>
              Woerter werden pro logischer Datei ausgewertet und als
              <code>sum</code>, <code>min</code>, <code>max</code>, <code>avg</code>
              zusammengefasst.
            </li>
          </ul>
        </div>
        <form id="compare-form" method="post" enctype="multipart/form-data">
          <label>
            Aeltere Version (older_files):
            <input name="older_files" type="file" accept=".vtt,.txt,.zip" multiple required />
          </label>
          <label>
            Neuere Version (newer_files):
            <input name="newer_files" type="file" accept=".vtt,.txt,.zip" multiple required />
          </label>
          <button type="submit">Vergleich ausfuehren</button>
        </form>
        <p class="hint">
          Das Formular sendet per <code>POST</code> an denselben Endpoint.
          Die Antwort erfolgt als JSON.
        </p>
      </section>
    </main>
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


def summarize_words_per_file(word_counts: List[int]) -> Dict[str, float]:
    if not word_counts:
        return {"sum": 0, "min": 0, "max": 0, "avg": 0.0}

    total_words = sum(word_counts)
    return {
        "sum": total_words,
        "min": min(word_counts),
        "max": max(word_counts),
        "avg": round(total_words / len(word_counts), 3),
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

    older_words = summarize_words_per_file(older_group.file_word_counts)
    newer_words = summarize_words_per_file(newer_group.file_word_counts)

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
            "word_stats": older_words,
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
            "word_stats": newer_words,
            "empty_files": newer_group.empty_file_names,
            "empty_logical_file_names": newer_group.empty_logical_file_names,
        },
        "removed_timestamps": format_timestamps(removed),
        "added_timestamps": format_timestamps(added),
        "word_sum_delta": {
            "sum": newer_words["sum"] - older_words["sum"],
            "min": newer_words["min"] - older_words["min"],
            "max": newer_words["max"] - older_words["max"],
            "avg": round(newer_words["avg"] - older_words["avg"], 3),
        },
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
