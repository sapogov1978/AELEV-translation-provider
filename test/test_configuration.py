"""Service-owned Compose checks for translator-service."""

from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path


COMPONENT_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PATH = COMPONENT_ROOT / "compose.yml"
ENV_PATH = COMPONENT_ROOT / ".env.example"
ROLES = {
    "translator-migrator",
    "translator-model",
    "translator-consumer",
    "translator-worker",
    "translator-outbox",
}


def _resolved_compose() -> dict[str, object]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("AELEV_", "COMPOSE_", "VITE_"))
    }
    environment["AELEV_INFRASTRUCTURE_TRANSLATOR_DATABASE_URL"] = (
        "postgresql+psycopg://translator_service:test@database.invalid/"
        "translator_service"
    )
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            str(ENV_PATH),
            "-f",
            str(COMPOSE_PATH),
            "config",
            "--no-env-resolution",
            "--format",
            "json",
        ],
        cwd=COMPONENT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


class TranslatorConfigurationTest(unittest.TestCase):
    def test_operator_entrypoints_are_owned_by_the_component(self) -> None:
        for name in ("compose.yml", ".env.example", "README.md", "Dockerfile"):
            self.assertTrue((COMPONENT_ROOT / name).is_file(), name)

    def test_configuration_is_component_owned(self) -> None:
        compose = COMPOSE_PATH.read_text(encoding="utf-8")
        variables = [
            line.split("=", 1)[0]
            for line in ENV_PATH.read_text(encoding="utf-8").splitlines()
            if line and not line.startswith("#")
        ]
        self.assertTrue(variables)
        for variable in variables:
            self.assertTrue(
                variable.startswith("AELEV_INFRASTRUCTURE_TRANSLATOR_"), variable
            )
            self.assertIn(variable, compose, variable)

    def test_component_resolves_independently(self) -> None:
        resolved = _resolved_compose()
        self.assertEqual(resolved["name"], "aelev-infrastructure-translator")
        self.assertEqual(set(resolved["services"]), ROLES)
        self.assertEqual(
            resolved["services"]["translator-model"]["build"]["target"],
            "translator-runtime",
        )

    def test_private_socket_and_network_boundaries(self) -> None:
        services = _resolved_compose()["services"]
        socket_users = {
            name
            for name, service in services.items()
            if any(
                volume.get("source") == "translator-model-socket"
                for volume in service.get("volumes", [])
            )
        }
        self.assertEqual(socket_users, {"translator-model", "translator-worker"})
        self.assertEqual(services["translator-model"]["network_mode"], "none")
        self.assertEqual(
            set(services["translator-worker"]["networks"]), {"translator-data"}
        )
        self.assertTrue(services["translator-worker"]["volumes"][0]["read_only"])
        for role in ("translator-consumer", "translator-outbox"):
            self.assertEqual(
                set(services[role]["networks"]), {"events", "translator-data"}
            )
        for role in (
            "translator-migrator",
            "translator-consumer",
            "translator-worker",
            "translator-outbox",
        ):
            self.assertRegex(
                services[role]["environment"]["AELEV_TRANSLATOR_DATABASE_URL"],
                r"^postgresql\+psycopg://translator_service:[^@]+@"
                r"database\.invalid/translator_service$",
            )

    def test_restart_policy_distinguishes_migration(self) -> None:
        services = _resolved_compose()["services"]
        for name, service in services.items():
            expected = "no" if name == "translator-migrator" else "unless-stopped"
            self.assertEqual(service.get("restart"), expected, name)


if __name__ == "__main__":
    unittest.main()
