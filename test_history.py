import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from history import Bridge, create_app, UpstreamError
from fastapi.testclient import TestClient


class BridgeTests(unittest.TestCase):
    options = {"bucket": "window/test", "start": "2026-11-12T00:00:00-08:00",
               "end": "2026-11-13T00:00:00-08:00"}

    def test_preserves_payload_and_exports_without_overwrite(self):
        event = {"id": 7, "timestamp": "2026-11-12T12:00:00Z", "duration": 1.25,
                 "data": {"app": "Notion", "nested": {"future": [1, None, "é"]}}}
        with tempfile.TemporaryDirectory() as directory:
            bridge = Bridge("http://localhost:5600/api/0", directory)
            with patch("history.request_json", side_effect=[{"id": "window/test"}, [event]] * 2) as mock:
                first = bridge.export(self.options)
                second = bridge.export(self.options)
            self.assertNotEqual(first["output_file"], second["output_file"])
            saved = json.loads(Path(first["output_file"]).read_text())
            self.assertEqual(saved["events"], [event])
            self.assertIn("window%2Ftest/events?", mock.call_args_list[1].args[0])
            self.assertIn("limit=-1", mock.call_args_list[1].args[0])

    def test_invalid_ranges_do_not_contact_activitywatch(self):
        bridge = Bridge("http://localhost:5600/api/0", "unused")
        with patch("history.request_json") as mock:
            for changes in ({"start": "2026-11-12"}, {"end": self.options["start"]},
                            {"bucket": ""}, {"limit": 0}):
                with self.assertRaises(ValueError):
                    bridge.events({**self.options, **changes})
            mock.assert_not_called()

    def test_limit_marks_possible_truncation(self):
        with patch("history.request_json", side_effect=[{}, [{"id": 1}]]):
            result = Bridge("http://localhost", "unused").events({**self.options, "limit": 1})
        self.assertTrue(result["possibly_truncated"])


class EndpointTests(unittest.TestCase):
    def test_ai_endpoints_share_totals_and_paginate_after_filtering(self):
        raw = [
            {"id": 1, "timestamp": "2026-11-12T10:00:00Z", "duration": 600, "data": {"app": "Notion"}},
            {"id": 2, "timestamp": "2026-11-12T10:05:00Z", "duration": 600, "data": {"app": "notion"}},
            {"id": 3, "timestamp": "2026-11-12T10:20:00Z", "duration": 60, "data": {"app": "Chrome"}},
        ]
        params = {"start": "2026-11-12T10:00:00Z", "end": "2026-11-12T11:00:00Z"}
        client = TestClient(create_app())
        def call(path, extra=None):
            with patch("history.request_json", side_effect=[{"hostname": "mac"},
                       {"window": {"type": "currentwindow", "hostname": "mac"}}, raw]):
                response = client.get(path, params={**params, **(extra or {})})
                self.assertEqual(response.status_code, 200)
                return response.json()
        self.assertEqual(call("/apps")["apps"], ["Chrome", "Notion", "notion"])
        breakdown = call("/usage/breakdown")
        self.assertEqual(breakdown["apps"][0]["total_seconds"], 900)
        self.assertEqual(breakdown["observed_seconds"], 960)
        self.assertEqual(breakdown["unobserved_seconds"], 2640)
        compact = call("/usage", {"app": "Notion", "include_events": "false"})
        self.assertEqual(compact["total_seconds"], 900)
        self.assertEqual(compact["events"], [])
        page = call("/activity/events", {"app": "Notion", "limit": 1})
        self.assertEqual(page["events"], [raw[1]])
        self.assertEqual(page["next_offset"], 1)
        page2 = call("/activity/events", {"app": "Notion", "limit": 1, "offset": 1})
        self.assertEqual(page2["events"], [raw[0]])
        self.assertFalse(page2["has_more"])

    def test_ai_validation_missing_source_and_freshness(self):
        client = TestClient(create_app())
        params = {"start": "2026-11-12T10:00:00Z", "end": "2026-11-12T11:00:00Z"}
        with patch("history.request_json") as mock:
            self.assertEqual(client.get("/activity/events", params={**params, "limit": 1001}).status_code, 422)
            self.assertEqual(client.get("/apps", params={**params, "end": "2027-01-01T00:00:00Z"}).status_code, 400)
            mock.assert_not_called()
        with patch("history.request_json", side_effect=[{"hostname": "mac"}, {}]):
            self.assertEqual(client.get("/apps", params=params).status_code, 502)
        with patch("history.request_json", side_effect=[{"hostname": "mac"},
                   {"window": {"type": "currentwindow", "hostname": "mac"}}, []]):
            status = client.get("/recording-status")
            self.assertEqual(status.status_code, 200)
            self.assertIsNone(status.json()["sources"][0]["latest_observation_end"])

    def test_usage_clips_boundaries_unions_overlaps_and_keeps_raw_events(self):
        def event(id, time, duration, app="Notion"):
            return {"id": id, "timestamp": f"2026-11-12T{time}Z", "duration": duration,
                    "data": {"app": app, "title": "Original title"}}
        raw = [event(1, "09:55:00", 600), event(2, "10:03:00", 420),
               event(3, "10:55:00", 600), event(4, "10:20:00", 60, "Chrome"),
               event(5, "11:00:00", 60), event(6, "09:00:00", 60)]
        client = TestClient(create_app())
        with patch("history.request_json", side_effect=[{"hostname": "mac"},
                   {"window": {"type": "currentwindow", "hostname": "mac"}}, raw]):
            response = client.get("/usage", params={"app": "notion", "start": "2026-11-12T10:00:00Z",
                                                       "end": "2026-11-12T11:00:00Z"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total_seconds"], 900)
        self.assertEqual(response.json()["events"], raw[:3])

    def test_usage_empty_and_invalid_requests(self):
        client = TestClient(create_app())
        params = {"app": "Notion", "start": "2026-11-12T10:00:00Z", "end": "2026-11-12T11:00:00Z"}
        with patch("history.request_json", side_effect=[{"hostname": "mac"},
                   {"window": {"type": "currentwindow", "hostname": "mac"}}, []]):
            response = client.get("/usage", params=params)
        self.assertEqual(response.json()["total_seconds"], 0)
        self.assertEqual(response.json()["events"], [])
        with patch("history.request_json") as mock:
            self.assertEqual(client.get("/usage", params={**params, "app": " "}).status_code, 400)
            self.assertEqual(client.get("/usage", params={**params, "end": params["start"]}).status_code, 400)
            mock.assert_not_called()

    def test_export_http_preserves_data_and_documents_request(self):
        with tempfile.TemporaryDirectory() as directory:
            client = TestClient(create_app(output_dir=directory))
            event = {"id": 3, "data": {"nested": ["text", 42]}, "duration": 3.5}
            with patch("history.request_json", side_effect=[{"id": "window/test"}, [event]]):
                response = client.post("/exports", json=BridgeTests.options)
            self.assertEqual(response.status_code, 200)
            result = response.json()
            self.assertEqual(json.loads(Path(result["output_file"]).read_text())["events"], [event])
            self.assertEqual(client.get("/docs").status_code, 200)
            self.assertIn("/exports", client.get("/openapi.json").json()["paths"])

    def test_validation_and_upstream_error(self):
        client = TestClient(create_app())
        with patch("history.request_json") as mock:
            self.assertEqual(client.post("/exports", json={}).status_code, 422)
            self.assertEqual(client.get("/events", params={**BridgeTests.options, "limit": "bad"}).status_code, 422)
            self.assertEqual(client.get("/events", params={**BridgeTests.options, "start": "bad"}).status_code, 400)
            mock.assert_not_called()
        with patch("history.request_json", side_effect=UpstreamError("offline")):
            response = client.get("/health")
            self.assertEqual(response.status_code, 502)
            self.assertEqual(response.json(), {"error": "offline"})


if __name__ == "__main__":
    unittest.main()
