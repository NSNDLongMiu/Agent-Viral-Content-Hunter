from concurrent.futures import ThreadPoolExecutor
from importlib.util import find_spec
from threading import Barrier
from unittest import TestCase, skipUnless

from pydantic import ValidationError

from hunter.config import BudgetSettings, PaidAPIForbidden, SettingsError, load_settings
from hunter.db import Database
from hunter.interfaces import AIResult, AITask

from .support import DatabaseTestCase


class ConfigurationTests(DatabaseTestCase):
    def test_paid_api_flag_fails_closed_in_config_and_at_call_time(self) -> None:
        budget = BudgetSettings()
        self.assertIs(budget.allow_paid_api, False)
        budget.require_allowed(incurs_cost=False)
        for cost in (True, None):
            with self.assertRaises(PaidAPIForbidden):
                budget.require_allowed(incurs_cost=cost)
        for value in (True, 0, "false"):
            with self.assertRaises(ValidationError):
                BudgetSettings(allow_paid_api=value)
        local = self.database.path.with_suffix(".toml")
        local.write_text("[budget]\nallow_paid_api = true\n", encoding="utf-8")
        with self.assertRaises(SettingsError):
            load_settings(local, environ={})
        local.write_text("[budget]\nallow_paid_api = false\n", encoding="utf-8")
        with self.assertRaises(SettingsError):
            load_settings(local, environ={"HUNTER_BUDGET__ALLOW_PAID_API": "true"})
        settings = load_settings(local, environ={
            "HUNTER_BUDGET__ALLOW_PAID_API": "false", "HUNTER_QUEUE__CLAUDE": "0",
        })
        self.assertIs(settings.budget.allow_paid_api, False)
        self.assertEqual(settings.queue.claude, 0)

    def test_sqlite_migration_wal_and_foreign_keys(self) -> None:
        self.database.migrate()
        with self.database.connection() as connection:
            self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT count(*) FROM schema_migrations").fetchone()[0], 1)
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_concurrent_startup_migrates_a_fresh_database_once(self) -> None:
        new_database = Database(self.database.path.with_name("test-fixture-fresh.sqlite3"))
        ready = Barrier(6)

        def migrate(_: int) -> None:
            ready.wait(timeout=5)
            new_database.migrate()

        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(migrate, range(6)))
        with new_database.connection() as connection:
            self.assertEqual(connection.execute("SELECT version FROM schema_migrations").fetchall()[0][0], 1)
            self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "wal")


@skipUnless(find_spec("jsonschema"), "Install project dependencies to run JSON Schema validation")
class JSONSchemaTests(TestCase):
    def test_success_must_match_the_task_schema_and_remote_refs_do_not_resolve(self) -> None:
        task = AITask(
            id="test-fixture", instructions="Return fixture data", input={},
            output_schema={
                "type": "object", "required": ["count"], "properties": {"count": {"type": "integer"}},
            },
        )
        self.assertEqual(AIResult.success(task, {"count": 3}).output, {"count": 3})
        with self.assertRaises(ValueError):
            AIResult.success(task, {"count": "fixture"})
        remote = AITask(
            id="test-fixture-remote", instructions="Return fixture data", input={},
            output_schema={"$ref": "https://example.invalid/test-fixture.schema.json"},
        )
        with self.assertRaisesRegex(ValueError, "AI output failed task schema validation"):
            AIResult.success(remote, {})
