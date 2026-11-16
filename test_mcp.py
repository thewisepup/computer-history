"""Protocol-level checks using the official MCP client."""
import unittest
from unittest.mock import patch

from mcp import Client
from fastapi.testclient import TestClient

from history import Bridge, UpstreamError, create_app
from history_mcp import create_mcp


class MCPTests(unittest.IsolatedAsyncioTestCase):
    params = {"start": "2026-11-12T10:00:00Z", "end": "2026-11-12T11:00:00Z"}
    raw = [{"id": 1, "timestamp": "2026-11-12T10:00:00Z", "duration": 600,
            "data": {"app": "Notion", "title": "Original title", "custom": [1, None]}}]

    async def test_discovery_queries_and_original_evidence(self):
        server = create_mcp(Bridge("http://localhost:5600/api/0", "unused"))
        async with Client(server) as client:
            discovered = await client.list_tools()
            self.assertEqual({tool.name for tool in discovered.tools}, {
                "get_recording_status", "list_apps", "get_app_usage",
                "get_usage_breakdown", "get_activity_events"})
            self.assertTrue(all(tool.annotations.read_only_hint for tool in discovered.tools))
            results = {}
            for name in ("list_apps", "get_app_usage", "get_usage_breakdown", "get_activity_events"):
                args = {**self.params, **({"app": "notion"} if name == "get_app_usage" else {})}
                with patch("history.request_json", side_effect=[{"hostname": "mac"},
                           {"window": {"type": "currentwindow", "hostname": "mac"}}, self.raw]):
                    result = await client.call_tool(name, args)
                self.assertFalse(result.is_error)
                results[name] = result.structured_content
            self.assertEqual(results["list_apps"]["apps"], ["Notion"])
            self.assertEqual(results["get_app_usage"]["total_seconds"], 600)
            self.assertEqual(results["get_app_usage"]["events"], [])
            self.assertFalse(results["get_app_usage"]["idle_filtered"])
            self.assertEqual(results["get_usage_breakdown"]["apps"][0]["total_seconds"], 600)
            self.assertEqual(results["get_activity_events"]["events"], self.raw)

    async def test_invalid_arguments_and_upstream_failure_are_tool_errors(self):
        async with Client(create_mcp(Bridge("http://localhost", "unused"))) as client:
            with patch("history.request_json") as upstream:
                for extra in ({"limit": 1001}, {"offset": -1}, {"start": "no timezone"}):
                    result = await client.call_tool("get_activity_events", {**self.params, **extra})
                    self.assertTrue(result.is_error)
                upstream.assert_not_called()
            with patch("history.request_json", side_effect=UpstreamError("ActivityWatch unavailable")):
                result = await client.call_tool("get_recording_status")
                self.assertTrue(result.is_error)

    def test_http_mount_lifespan_and_rest_coexist(self):
        with TestClient(create_app(), base_url="http://127.0.0.1:8765") as client:
            response = client.post("/mcp", headers={"Accept": "application/json, text/event-stream"},
                                   json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                                       "protocolVersion": "2025-03-26", "capabilities": {},
                                       "clientInfo": {"name": "test", "version": "1"}}})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["result"]["serverInfo"]["name"], "Computer History")
            self.assertEqual(client.get("/openapi.json").status_code, 200)


if __name__ == "__main__":
    unittest.main()
