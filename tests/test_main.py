import base64
import io
import json
import unittest
import zipfile

from function.main import handler


def multipart_form_body(boundary: str, parts):
    data = []
    for part in parts:
        data.append(f"--{boundary}\r\n".encode("utf-8"))
        content_disposition = (
            f'Content-Disposition: form-data; name="{part["name"]}"'
        )
        if "filename" in part:
            content_disposition += f'; filename="{part["filename"]}"'
        data.append(f"{content_disposition}\r\n".encode("utf-8"))
        if "content_type" in part:
            data.append(f'Content-Type: {part["content_type"]}\r\n'.encode("utf-8"))
        data.append(b"\r\n")
        payload = part["payload"]
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        data.append(payload)
        data.append(b"\r\n")
    data.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(data)


def build_zip(file_map):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for filename, content in file_map.items():
            archive.writestr(filename, content.encode("utf-8"))
    return buffer.getvalue()


class VttComparisonTests(unittest.TestCase):
    def test_get_returns_upload_frontend(self):
        result = handler(
            {"requestContext": {"http": {"method": "GET"}}, "headers": {}},
            None,
        )
        self.assertEqual(200, result["statusCode"])
        self.assertIn("text/html", result["headers"]["Content-Type"])
        self.assertIn("older_files", result["body"])
        self.assertIn("newer_files", result["body"])

    def test_compare_two_single_vtt_files(self):
        older_vtt = (
            "WEBVTT\n\n"
            "00:00:00.000 --> 00:00:01.000\n"
            "Hallo Welt\n\n"
            "00:00:01.000 --> 00:00:02.000\n"
            "Alt bleibt\n"
        )
        newer_vtt = (
            "WEBVTT\n\n"
            "00:00:01.000 --> 00:00:02.000\n"
            "Alt bleibt\n\n"
            "00:00:02.000 --> 00:00:03.000\n"
            "Neu hinzu\n"
        )
        boundary = "----BoundarySingleFiles"
        body = multipart_form_body(
            boundary,
            [
                {
                    "name": "older_files",
                    "filename": "older.vtt",
                    "content_type": "text/vtt",
                    "payload": older_vtt,
                },
                {
                    "name": "newer_files",
                    "filename": "newer.vtt",
                    "content_type": "text/vtt",
                    "payload": newer_vtt,
                },
            ],
        )
        event = {
            "headers": {"Content-Type": f"multipart/form-data; boundary={boundary}"},
            "isBase64Encoded": True,
            "body": base64.b64encode(body).decode("ascii"),
        }

        result = handler(event, None)
        self.assertEqual(200, result["statusCode"])
        payload = json.loads(result["body"])

        self.assertEqual(2, payload["summary"]["timestamp_count"]["older"])
        self.assertEqual(2, payload["summary"]["timestamp_count"]["newer"])
        self.assertEqual(1, payload["summary"]["removed_timestamps_count"])
        self.assertEqual(1, payload["summary"]["added_timestamps_count"])
        self.assertEqual(
            ["00:00:00.000 --> 00:00:01.000"], payload["removed_timestamps"]
        )
        self.assertEqual(["00:00:02.000 --> 00:00:03.000"], payload["added_timestamps"])
        self.assertEqual(4, payload["older_group"]["word_stats"]["sum"])
        self.assertEqual(4, payload["newer_group"]["word_stats"]["sum"])
        self.assertEqual([4], payload["older_group"]["file_word_counts"])
        self.assertEqual([4], payload["newer_group"]["file_word_counts"])

    def test_zip_group_with_multiple_vtt_is_treated_as_combined_input(self):
        older_zip = build_zip(
            {
                "part1.vtt": (
                    "WEBVTT\n\n"
                    "00:00:00.000 --> 00:00:01.000\n"
                    "A eins\n"
                ),
                "part2.vtt": (
                    "WEBVTT\n\n"
                    "00:00:01.000 --> 00:00:02.000\n"
                    "A zwei\n"
                ),
            }
        )
        newer_zip = build_zip(
            {
                "segment-1.vtt": (
                    "WEBVTT\n\n"
                    "00:00:00.000 --> 00:00:01.000\n"
                    "A eins\n"
                ),
                "segment-2.vtt": (
                    "WEBVTT\n\n"
                    "00:00:02.000 --> 00:00:03.000\n"
                    "Neu drei\n"
                ),
            }
        )
        boundary = "----BoundaryZip"
        body = multipart_form_body(
            boundary,
            [
                {
                    "name": "older_files",
                    "filename": "older.zip",
                    "content_type": "application/zip",
                    "payload": older_zip,
                },
                {
                    "name": "newer_files",
                    "filename": "newer.zip",
                    "content_type": "application/zip",
                    "payload": newer_zip,
                },
            ],
        )
        event = {
            "headers": {"Content-Type": f"multipart/form-data; boundary={boundary}"},
            "isBase64Encoded": True,
            "body": base64.b64encode(body).decode("ascii"),
        }

        result = handler(event, None)
        self.assertEqual(200, result["statusCode"])
        payload = json.loads(result["body"])
        self.assertEqual(1, payload["older_group"]["uploaded_file_count"])
        self.assertEqual(2, payload["older_group"]["expanded_vtt_file_count"])
        self.assertEqual(1, payload["newer_group"]["uploaded_file_count"])
        self.assertEqual(2, payload["newer_group"]["expanded_vtt_file_count"])
        self.assertEqual(1, payload["summary"]["removed_timestamps_count"])
        self.assertEqual(1, payload["summary"]["added_timestamps_count"])
        self.assertEqual([4], payload["older_group"]["file_word_counts"])
        self.assertEqual([4], payload["newer_group"]["file_word_counts"])
        self.assertEqual([2], payload["older_group"]["file_timestamp_counts"])
        self.assertEqual([2], payload["newer_group"]["file_timestamp_counts"])

    def test_missing_webvtt_header_is_accepted_when_timestamps_exist(self):
        older_without_header = (
            "00:00:00.000 --> 00:00:01.000\n"
            "Hallo\n"
        )
        newer_without_header = (
            "00:00:00.000 --> 00:00:01.000\n"
            "Hallo nochmal\n"
        )
        boundary = "----BoundaryNoHeader"
        body = multipart_form_body(
            boundary,
            [
                {
                    "name": "older_files",
                    "filename": "old.txt",
                    "content_type": "text/plain",
                    "payload": older_without_header,
                },
                {
                    "name": "newer_files",
                    "filename": "new.txt",
                    "content_type": "text/plain",
                    "payload": newer_without_header,
                },
            ],
        )
        event = {
            "headers": {"Content-Type": f"multipart/form-data; boundary={boundary}"},
            "isBase64Encoded": True,
            "body": base64.b64encode(body).decode("ascii"),
        }
        result = handler(event, None)
        self.assertEqual(200, result["statusCode"])
        payload = json.loads(result["body"])
        self.assertEqual(0, payload["summary"]["removed_timestamps_count"])
        self.assertEqual(0, payload["summary"]["added_timestamps_count"])
        self.assertEqual(1, payload["older_group"]["word_stats"]["sum"])
        self.assertEqual(2, payload["newer_group"]["word_stats"]["sum"])

    def test_word_stats_are_calculated_per_logical_file(self):
        older_zip = build_zip(
            {
                "one.vtt": (
                    "WEBVTT\n\n"
                    "00:00:00.000 --> 00:00:01.000\n"
                    "eins zwei\n"
                ),
                "two.vtt": (
                    "WEBVTT\n\n"
                    "00:00:01.000 --> 00:00:02.000\n"
                    "drei vier\n"
                ),
            }
        )
        newer_zip = build_zip(
            {
                "one.vtt": (
                    "WEBVTT\n\n"
                    "00:00:00.000 --> 00:00:01.000\n"
                    "eins zwei drei\n"
                ),
                "two.vtt": (
                    "WEBVTT\n\n"
                    "00:00:01.000 --> 00:00:02.000\n"
                    "vier fuenf sechs\n"
                ),
            }
        )
        boundary = "----BoundaryWordPerFile"
        body = multipart_form_body(
            boundary,
            [
                {
                    "name": "older_files",
                    "filename": "older.zip",
                    "content_type": "application/zip",
                    "payload": older_zip,
                },
                {
                    "name": "older_files",
                    "filename": "older-extra.vtt",
                    "content_type": "text/vtt",
                    "payload": (
                        "WEBVTT\n\n"
                        "00:00:02.000 --> 00:00:03.000\n"
                        "extra alt\n"
                    ),
                },
                {
                    "name": "newer_files",
                    "filename": "newer.zip",
                    "content_type": "application/zip",
                    "payload": newer_zip,
                },
                {
                    "name": "newer_files",
                    "filename": "newer-extra.vtt",
                    "content_type": "text/vtt",
                    "payload": (
                        "WEBVTT\n\n"
                        "00:00:02.000 --> 00:00:03.000\n"
                        "extra neu neu\n"
                    ),
                },
            ],
        )
        event = {
            "headers": {"Content-Type": f"multipart/form-data; boundary={boundary}"},
            "isBase64Encoded": True,
            "body": base64.b64encode(body).decode("ascii"),
        }
        result = handler(event, None)
        self.assertEqual(200, result["statusCode"])
        payload = json.loads(result["body"])

        self.assertEqual([4, 2], payload["older_group"]["file_word_counts"])
        self.assertEqual([6, 3], payload["newer_group"]["file_word_counts"])
        self.assertEqual(2, payload["older_group"]["word_stats"]["min"])
        self.assertEqual(4, payload["older_group"]["word_stats"]["max"])
        self.assertEqual(3.0, payload["older_group"]["word_stats"]["avg"])
        self.assertEqual(3, payload["newer_group"]["word_stats"]["min"])
        self.assertEqual(6, payload["newer_group"]["word_stats"]["max"])
        self.assertEqual(4.5, payload["newer_group"]["word_stats"]["avg"])

    def test_missing_group_field_returns_validation_error(self):
        boundary = "----BoundaryMissingGroup"
        body = multipart_form_body(
            boundary,
            [
                {
                    "name": "older_files",
                    "filename": "old.vtt",
                    "content_type": "text/vtt",
                    "payload": "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHallo\n",
                }
            ],
        )
        event = {
            "headers": {"Content-Type": f"multipart/form-data; boundary={boundary}"},
            "isBase64Encoded": True,
            "body": base64.b64encode(body).decode("ascii"),
        }
        result = handler(event, None)
        self.assertEqual(400, result["statusCode"])
        payload = json.loads(result["body"])
        self.assertIn("Missing files for newer group", payload["error"])

    def test_method_not_allowed(self):
        result = handler(
            {"requestContext": {"http": {"method": "PATCH"}}, "headers": {}},
            None,
        )
        self.assertEqual(405, result["statusCode"])


if __name__ == "__main__":
    unittest.main()
