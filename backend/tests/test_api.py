import json
from datetime import timedelta
from pathlib import Path
from unittest import TestCase

from fastapi.testclient import TestClient

from hunter.api.app import create_app
from hunter.config import AuthSettings, QueueSettings, Settings
from hunter.models import JobInput, JobStatus, WorkerKind
from hunter.models.briefs import AIFeasibility, AIProduction, BriefStatus, ContentBrief, FocusTag
from hunter.models.common import utcnow
from hunter.queue import PersistentQueue

from .support import DatabaseTestCase, approve, fixture_draft, pending_brief

_FIXTURE_SERVICE_TOKEN = "test-fixture-claude-token-must-not-be-used-as-a-secret"


class APITests(DatabaseTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.auth = AuthSettings(claude_service_token=_FIXTURE_SERVICE_TOKEN)

    def client(self, *, auth: AuthSettings | None = None) -> TestClient:
        return TestClient(create_app(Settings(database_path=self.database.path, auth=auth or self.auth)))

    def test_dashboard_routes_need_no_login_and_only_the_claude_token_reaches_review(self) -> None:
        with self.client() as client:
            claude = {"Authorization": f"Bearer {_FIXTURE_SERVICE_TOKEN}"}
            for path, methods in client.app.openapi()["paths"].items():
                url = path
                for segment in path.split("/"):
                    if segment.startswith("{"):
                        url = url.replace(segment, "fixture")
                for method in methods:
                    with self.subTest(method=method, path=path):
                        status = client.request(method, url).status_code
                        # Review routes keep their own credential; nothing else may ask for one.
                        self.assertEqual(status == 401, path.startswith("/review"))
            self.assertEqual(client.get("/briefs/inbox").status_code, 200)
            self.assertEqual(client.get("/review/pending").status_code, 401)
            self.assertEqual(client.get("/review/pending", headers={"Authorization": "Bearer wrong"}).status_code, 401)
            self.assertEqual(client.get("/review/pending", headers=claude).status_code, 200)
            self.assertEqual(client.post("/auth/login", json={"password": "anything"}).status_code, 404)
            self.assertEqual(client.get("/docs").status_code, 404)
            self.assertEqual(client.get("/openapi.json").status_code, 404)

    def test_api_review_inbox_handoff_and_feedback_workflow(self) -> None:
        with self.client() as client:
            backend = client.app.state.services
            brief = pending_brief(backend.briefs, self.clock)
            claude = {"Authorization": f"Bearer {_FIXTURE_SERVICE_TOKEN}"}
            self.assertEqual(client.get("/briefs/inbox").json(), [])
            self.assertEqual(client.get(f"/briefs/{brief.id}").status_code, 404)
            self.assertEqual(client.get(f"/briefs/{brief.id}/export/md").status_code, 404)
            self.assertEqual(client.get(f"/monitor/briefs/{brief.id}").status_code, 200)
            route = f"/review/{brief.id}/decision"
            data = {"action": "APPROVE", "expected_revision": 0, "reason": "  "}
            self.assertEqual(client.post(route, json=data, headers=claude).status_code, 422)
            data["reason"] = "Test fixture approval"
            self.assertEqual(client.post(route, json=data).status_code, 401)
            self.assertEqual(client.post(route, json=data, headers=claude).status_code, 200)
            self.assertEqual([item["id"] for item in client.get("/briefs/inbox").json()], [brief.id])
            detail = client.get(f"/briefs/{brief.id}").json()
            self.assertEqual(detail["review_history"][0]["reason"], data["reason"])
            markdown = client.get(f"/briefs/{brief.id}/export/md")
            self.assertEqual(markdown.status_code, 200)
            self.assertEqual(markdown.headers["content-type"], "text/markdown; charset=utf-8")
            self.assertIn(brief.title_vi, markdown.text)
            exported = client.get(f"/briefs/{brief.id}/export/json")
            self.assertEqual(exported.headers["content-type"], "application/json")
            self.assertEqual(exported.json(), detail["brief"])
            handoff = client.post("/handoffs", json={"brief_id": brief.id}).json()
            self.assertEqual(handoff["status"], "SELECTED")
            self.assertEqual(
                client.post(f"/handoffs/{handoff['id']}/send", json={"message": "Fixture"}).status_code,
                501,
            )
            for action in ("good", "irrelevant", "duplicate", "bad-source"):
                self.assertEqual(client.post(
                    "/feedback", json={"brief_id": brief.id, "action": action}
                ).status_code, 201)
            self.assertEqual(len(client.get("/feedback").json()), 4)

    def test_inbox_filters_by_ai_feasibility_and_focus_tag(self) -> None:
        with self.client() as client:
            backend = client.app.state.services

            def submit(
                feasibility: AIFeasibility, tags: list[FocusTag], *, priority: str = "P2",
            ) -> ContentBrief:
                progress = backend.briefs.create()
                backend.briefs.advance(progress.id, BriefStatus.PREPROCESSED)
                backend.briefs.advance(progress.id, BriefStatus.PROCESSING)
                draft = fixture_draft(self.clock, priority=priority)
                draft.focus_tags = tags
                draft.ai_production = AIProduction(
                    feasibility=feasibility,
                    approach_vi="Dùng hình minh họa, giọng đọc AI và kiểm tra dữ liệu nguồn trước khi dựng video.",
                    constraints_vi=["Kiểm tra dữ liệu nguồn."],
                )
                return backend.briefs.submit_draft(progress.id, draft, expected_revision=0)

            both = submit(AIFeasibility.HIGH, ["giai_tri", "micro_drama"])
            feasibility_only = submit(AIFeasibility.HIGH, ["ai_san_xuat"], priority="P1")
            focus_only = submit(AIFeasibility.LOW, ["micro_drama"], priority="P1")
            submit(AIFeasibility.HIGH, ["micro_drama"])  # Matching draft, still pending.
            legacy = pending_brief(backend.briefs, self.clock)
            for brief in (both, feasibility_only, focus_only, legacy):
                approve(backend.review, brief)

            with self.database.transaction() as connection:
                connection.execute(
                    "UPDATE briefs SET content_json = json_remove(content_json, '$.ai_production', '$.focus_tags') "
                    "WHERE id = ?",
                    (legacy.id,),
                )
            cases = (
                ({}, {both.id, feasibility_only.id, focus_only.id, legacy.id}),
                ({"ai_feasibility": "CAO"}, {both.id, feasibility_only.id}),
                ({"focus_tag": "micro_drama"}, {both.id, focus_only.id}),
                ({"ai_feasibility": "CAO", "focus_tag": "micro_drama"}, {both.id}),
                ({"ai_feasibility": "CAO", "focus_tag": "micro_drama", "priority": "P1"}, set()),
                ({"ai_feasibility": "CAO", "focus_tag": "micro_drama", "priority": "P2"}, {both.id}),
            )
            for params, expected in cases:
                with self.subTest(params=params):
                    response = client.get("/briefs/inbox", params=params)
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual({item["id"] for item in response.json()}, expected)

    def test_inbox_filter_validation_redacts_invalid_values(self) -> None:
        with self.client() as client:
            for name in ("ai_feasibility", "focus_tag"):
                with self.subTest(name=name):
                    response = client.get("/briefs/inbox", params={name: _FIXTURE_SERVICE_TOKEN})
                    self.assertEqual(response.status_code, 422)
                    error, = response.json()["detail"]
                    self.assertEqual(error["loc"], ["query"])
                    self.assertEqual(error["msg"], "Invalid request value")
                    self.assertNotIn(_FIXTURE_SERVICE_TOKEN, response.text)

    def test_startup_reclaims_expired_leases(self) -> None:
        instant = utcnow() - timedelta(minutes=2)
        queue = PersistentQueue(self.database, QueueSettings(lease_seconds=10), clock=lambda: instant)
        job = queue.enqueue(JobInput(idempotency_key="test-fixture-lease", kind="test-fixture", worker=WorkerKind.LOCAL))
        self.assertIsNotNone(queue.claim(WorkerKind.LOCAL, "test-fixture-worker"))
        with self.client() as client:
            self.assertEqual(client.get("/health").status_code, 200)
            recovered = queue.get(job.id)
            self.assertEqual((recovered.status, recovered.attempt_count), (JobStatus.QUEUED, 1))

    def test_unconfigured_token_closes_review_and_validation_hides_credentials(self) -> None:
        with self.client(auth=AuthSettings()) as client:
            bearer = {"Authorization": f"Bearer {_FIXTURE_SERVICE_TOKEN}"}
            self.assertEqual(client.get("/review/pending", headers=bearer).status_code, 401)
        with self.client() as client:
            claude = {"Authorization": f"Bearer {_FIXTURE_SERVICE_TOKEN}"}
            invalid = client.post(
                "/review/fixture/decision", headers=claude, json={"action": [_FIXTURE_SERVICE_TOKEN], "secret-key": True},
            )
            self.assertEqual(invalid.status_code, 422)
            self.assertNotIn(_FIXTURE_SERVICE_TOKEN, invalid.text)
            self.assertNotIn("secret-key", invalid.text)

    def test_local_guard_refuses_foreign_hosts_and_foreign_origins(self) -> None:
        with self.client() as client:
            self.assertEqual(client.get("/health", headers={"Host": "evil.example"}).status_code, 403)
            self.assertEqual(client.get("/health", headers={"Host": "192.168.1.20:8000"}).status_code, 403)
            for host in ("127.0.0.1:8000", "localhost:8000", "[::1]:8000"):
                self.assertEqual(client.get("/health", headers={"Host": host}).status_code, 200, host)
            local = {"Host": "127.0.0.1:8000"}
            post = "/handoffs"
            for origin in ("https://evil.example", "null", "http://127.0.0.1.evil.example"):
                with self.subTest(origin=origin):
                    response = client.post(post, headers={**local, "Origin": origin}, json={})
                    self.assertEqual(response.status_code, 403)
            for origin in ("http://127.0.0.1:8000", "http://localhost:3000"):
                with self.subTest(origin=origin):
                    # Past the guard: the empty body then fails validation instead.
                    self.assertEqual(client.post(post, headers={**local, "Origin": origin}, json={}).status_code, 422)
            # Reading with a foreign Origin is left to the browser's CORS rules; no CORS headers are ever sent.
            read = client.get("/briefs/inbox", headers={**local, "Origin": "https://evil.example"})
            self.assertEqual(read.status_code, 200)
            self.assertNotIn("access-control-allow-origin", read.headers)


class OpenAPITests(TestCase):
    def test_exported_routes_and_credentials_match_live_api(self) -> None:
        path = Path(__file__).resolve().parents[2] / "docs" / "openapi.json"
        exported = json.loads(path.read_text(encoding="utf-8"))
        actual = create_app().openapi()
        self.assertEqual(exported["servers"], [{"url": "/api"}])
        self.assertEqual(exported["paths"].keys(), actual["paths"].keys())
        for path, methods in actual["paths"].items():
            self.assertEqual(exported["paths"][path].keys(), methods.keys())
            for method, operation in methods.items():
                self.assertEqual(
                    exported["paths"][path][method].get("security"), operation.get("security")
                )
