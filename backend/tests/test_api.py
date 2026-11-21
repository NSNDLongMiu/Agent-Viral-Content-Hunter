import json
from datetime import timedelta
from pathlib import Path
from unittest import TestCase

from fastapi.testclient import TestClient

from hunter.api.app import create_app
from hunter.api.auth import hash_password
from hunter.config import AuthSettings, QueueSettings, Settings
from hunter.models import JobInput, JobStatus, WorkerKind
from hunter.models.common import utcnow
from hunter.queue import PersistentQueue

from .support import DatabaseTestCase, pending_brief

_FIXTURE_PASSWORD = "Test fixture admin password"
_FIXTURE_SERVICE_TOKEN = "test-fixture-claude-token-must-not-be-used-as-a-secret"


class APITests(DatabaseTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.auth = AuthSettings(
            admin_password_hash=hash_password(_FIXTURE_PASSWORD),
            claude_service_token=_FIXTURE_SERVICE_TOKEN,
        )

    def client(self, *, auth: AuthSettings | None = None) -> TestClient:
        return TestClient(create_app(Settings(database_path=self.database.path, auth=auth or self.auth)))

    @staticmethod
    def admin(client: TestClient) -> dict[str, str]:
        response = client.post("/auth/login", json={"password": _FIXTURE_PASSWORD})
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    def test_protected_routes_login_logout_and_separate_review_token(self) -> None:
        with self.client() as client:
            schema = client.app.openapi()
            for path, methods in schema["paths"].items():
                if path in ("/health", "/auth/login"):
                    continue
                url = path
                for segment in path.split("/"):
                    if segment.startswith("{"):
                        url = url.replace(segment, "fixture")
                for method in methods:
                    with self.subTest(method=method, path=path):
                        self.assertEqual(client.request(method, url).status_code, 401)
            self.assertEqual(client.get("/health").json(), {"status": "ok"})
            self.assertEqual(client.post("/auth/login", json={"password": "wrong fixture"}).status_code, 401)
            admin = self.admin(client)
            claude = {"Authorization": f"Bearer {_FIXTURE_SERVICE_TOKEN}"}
            self.assertEqual(client.get("/briefs/inbox", headers=admin).status_code, 200)
            self.assertEqual(client.get("/review/pending", headers=admin).status_code, 401)
            self.assertEqual(client.get("/briefs/inbox", headers=claude).status_code, 401)
            self.assertEqual(client.get("/review/pending", headers=claude).status_code, 200)
            self.assertEqual(client.post("/auth/logout", headers=admin).status_code, 204)
            self.assertEqual(client.get("/briefs/inbox", headers=admin).status_code, 401)
            self.assertEqual(client.get("/docs").status_code, 404)
            self.assertEqual(client.get("/openapi.json").status_code, 404)

    def test_api_review_inbox_handoff_and_feedback_workflow(self) -> None:
        with self.client() as client:
            backend = client.app.state.services
            brief = pending_brief(backend.briefs, self.clock)
            admin = self.admin(client)
            claude = {"Authorization": f"Bearer {_FIXTURE_SERVICE_TOKEN}"}
            self.assertEqual(client.get("/briefs/inbox", headers=admin).json(), [])
            self.assertEqual(client.get(f"/briefs/{brief.id}", headers=admin).status_code, 404)
            self.assertEqual(client.get(f"/briefs/{brief.id}/export/md", headers=admin).status_code, 404)
            self.assertEqual(client.get(f"/monitor/briefs/{brief.id}", headers=admin).status_code, 200)
            route = f"/review/{brief.id}/decision"
            data = {"action": "APPROVE", "expected_revision": 0, "reason": "  "}
            self.assertEqual(client.post(route, json=data, headers=claude).status_code, 422)
            data["reason"] = "Test fixture approval"
            self.assertEqual(client.post(route, json=data, headers=admin).status_code, 401)
            self.assertEqual(client.post(route, json=data, headers=claude).status_code, 200)
            self.assertEqual([item["id"] for item in client.get("/briefs/inbox", headers=admin).json()], [brief.id])
            detail = client.get(f"/briefs/{brief.id}", headers=admin).json()
            self.assertEqual(detail["review_history"][0]["reason"], data["reason"])
            markdown = client.get(f"/briefs/{brief.id}/export/md", headers=admin)
            self.assertEqual(markdown.status_code, 200)
            self.assertEqual(markdown.headers["content-type"], "text/markdown; charset=utf-8")
            self.assertIn(brief.title_vi, markdown.text)
            exported = client.get(f"/briefs/{brief.id}/export/json", headers=admin)
            self.assertEqual(exported.headers["content-type"], "application/json")
            self.assertEqual(exported.json(), detail["brief"])
            handoff = client.post("/handoffs", headers=admin, json={"brief_id": brief.id}).json()
            self.assertEqual(handoff["status"], "SELECTED")
            self.assertEqual(
                client.post(f"/handoffs/{handoff['id']}/send", headers=admin, json={"message": "Fixture"}).status_code,
                501,
            )
            for action in ("good", "irrelevant", "duplicate", "bad-source"):
                self.assertEqual(client.post(
                    "/feedback", headers=admin, json={"brief_id": brief.id, "action": action}
                ).status_code, 201)
            self.assertEqual(len(client.get("/feedback", headers=admin).json()), 4)

    def test_startup_reclaims_expired_leases(self) -> None:
        instant = utcnow() - timedelta(minutes=2)
        queue = PersistentQueue(self.database, QueueSettings(lease_seconds=10), clock=lambda: instant)
        job = queue.enqueue(JobInput(idempotency_key="test-fixture-lease", kind="test-fixture", worker=WorkerKind.LOCAL))
        self.assertIsNotNone(queue.claim(WorkerKind.LOCAL, "test-fixture-worker"))
        with self.client() as client:
            self.assertEqual(client.get("/health").status_code, 200)
            recovered = queue.get(job.id)
            self.assertEqual((recovered.status, recovered.attempt_count), (JobStatus.QUEUED, 1))

    def test_unconfigured_auth_and_validation_hide_credentials(self) -> None:
        with self.client(auth=AuthSettings()) as client:
            self.assertEqual(client.post("/auth/login", json={"password": _FIXTURE_PASSWORD}).status_code, 401)
            invalid = client.post("/auth/login", json={"password": [_FIXTURE_PASSWORD], _FIXTURE_SERVICE_TOKEN: True})
            self.assertEqual(invalid.status_code, 422)
            self.assertNotIn(_FIXTURE_PASSWORD, invalid.text)
            self.assertNotIn(_FIXTURE_SERVICE_TOKEN, invalid.text)


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
