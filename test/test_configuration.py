"""Service-owned Compose checks for translator-service."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path
from typing import Any, cast

COMPONENT_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PATH = COMPONENT_ROOT / "compose.yml"
REMOTE_COMPOSE_PATH = COMPONENT_ROOT / "compose.remote.yml"
KAFKA_ENV_PATH = COMPONENT_ROOT.parent / "kafka/.env.example"
ENV_PATH = COMPONENT_ROOT / ".env.example"
ROLES = {
    "translator-api",
    "translator-database",
    "translator-migrator",
    "translator-model",
    "translator-normal-consumer",
    "translator-worker",
    "translator-outbox",
    "translator-priority-consumer",
    "translator-topic-provisioner",
}


def _clean_environment() -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("AELEV_", "COMPOSE_", "VITE_"))
    }
    environment["AELEV_INFRASTRUCTURE_TRANSLATOR_KAFKA_ENV_FILE"] = str(KAFKA_ENV_PATH)
    return environment


def _resolved_compose(path: Path = COMPOSE_PATH) -> dict[str, Any]:
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            str(ENV_PATH),
            "-f",
            str(path),
            "config",
            "--no-env-resolution",
            "--format",
            "json",
        ],
        cwd=COMPONENT_ROOT,
        env=_clean_environment(),
        capture_output=True,
        text=True,
        check=True,
    )
    return cast(dict[str, Any], json.loads(result.stdout))


@unittest.skipUnless(shutil.which("docker"), "Docker CLI is required")
class TranslatorConfigurationTest(unittest.TestCase):
    def test_operator_entrypoints_are_owned_by_the_component(self) -> None:
        self.assertEqual(
            {path.name for path in COMPONENT_ROOT.glob("compose*.yml")},
            {"compose.yml", "compose.remote.yml", "compose.local.yml"},
        )
        for name in (
            "compose.yml",
            "compose.remote.yml",
            "compose.local.yml",
            ".env.example",
            "README.md",
            "Dockerfile",
        ):
            self.assertTrue((COMPONENT_ROOT / name).is_file(), name)

    def test_configuration_is_component_owned(self) -> None:
        compose = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                COMPOSE_PATH,
                REMOTE_COMPOSE_PATH,
                COMPONENT_ROOT / "compose.local.yml",
            )
        )
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
        self.assertEqual(set(resolved["services"]), ROLES | {"kafka"})
        self.assertEqual(
            resolved["services"]["translator-model"]["build"]["target"],
            "translator-runtime",
        )
        self.assertEqual(
            resolved["volumes"]["translator-database-data"]["name"],
            "aelev-infrastructure-translator-database",
        )

    def test_remote_mode_uses_the_configured_kafka_without_starting_it(self) -> None:
        resolved = _resolved_compose(REMOTE_COMPOSE_PATH)
        self.assertEqual(set(resolved["services"]), ROLES - {"translator-database"})
        self.assertFalse(
            resolved["services"]["translator-migrator"]["depends_on"][
                "translator-database"
            ]["required"]
        )
        self.assertEqual(
            resolved["services"]["translator-topic-provisioner"]["restart"],
            "on-failure",
        )

    def test_bundled_mode_starts_kafka_before_topic_provisioning(self) -> None:
        services = _resolved_compose()["services"]
        self.assertEqual(
            services["translator-topic-provisioner"]["environment"][
                "AELEV_ENVIRONMENT"
            ],
            "local",
        )
        self.assertEqual(
            services["translator-migrator"]["depends_on"]["translator-database"],
            {"condition": "service_healthy", "required": True},
        )
        self.assertEqual(
            services["translator-topic-provisioner"]["depends_on"]["kafka"],
            {"condition": "service_healthy", "required": True},
        )
        for role in (
            "translator-priority-consumer",
            "translator-normal-consumer",
            "translator-outbox",
            "translator-api",
        ):
            self.assertEqual(
                services[role]["depends_on"]["translator-topic-provisioner"],
                {"condition": "service_completed_successfully", "required": True},
            )

    def test_missing_required_setting_fails_before_start(self) -> None:
        environment = _clean_environment()
        variable = "AELEV_INFRASTRUCTURE_TRANSLATOR_HIGH_PRIORITY_BURST"
        environment[variable] = ""
        result = subprocess.run(
            [
                "docker",
                "compose",
                "--env-file",
                str(ENV_PATH),
                "-f",
                str(COMPOSE_PATH),
                "config",
                "--quiet",
            ],
            cwd=COMPONENT_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(variable, result.stderr)

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
        for role in (
            "translator-priority-consumer",
            "translator-normal-consumer",
            "translator-outbox",
        ):
            self.assertEqual(
                set(services[role]["networks"]), {"kafka", "translator-data"}
            )
        self.assertEqual(
            set(services["translator-api"]["networks"]),
            {"kafka", "translator-data", "translator-ingress"},
        )
        for role in (
            "translator-migrator",
            "translator-priority-consumer",
            "translator-normal-consumer",
            "translator-worker",
            "translator-outbox",
            "translator-api",
        ):
            self.assertEqual(
                services[role]["environment"]["AELEV_TRANSLATOR_DATABASE_HOST"],
                "translator-database",
            )

    def test_priority_is_owned_by_topics_not_request_payload(self) -> None:
        services = _resolved_compose()["services"]
        self.assertEqual(
            services["translator-priority-consumer"]["environment"][
                "AELEV_TRANSLATOR_REQUEST_TOPIC"
            ],
            "translation.requests.priority.v1",
        )
        self.assertEqual(
            services["translator-normal-consumer"]["environment"][
                "AELEV_TRANSLATOR_REQUEST_TOPIC"
            ],
            "translation.requests.v1",
        )
        self.assertEqual(
            services["translator-worker"]["environment"][
                "AELEV_TRANSLATOR_HIGH_PRIORITY_BURST"
            ],
            "4",
        )

    def test_operational_api_is_read_only(self) -> None:
        source = (COMPONENT_ROOT / "src/translator_service/api.py").read_text()
        self.assertNotIn("@app.post", source)
        self.assertNotIn("@app.put", source)
        self.assertNotIn("@app.delete", source)

    def test_operator_https_is_owned_without_an_extra_service(self) -> None:
        api = _resolved_compose()["services"]["translator-api"]
        self.assertEqual(
            api["command"], ["python", "-m", "translator_service.api_server"]
        )
        self.assertEqual(len(api["ports"]), 2)
        self.assertEqual(api["ports"][0]["host_ip"], "127.0.0.1")
        self.assertEqual(
            api["environment"]["AELEV_INFRASTRUCTURE_TRANSLATOR_API_PUBLIC_URL"],
            "https://localhost:18496",
        )
        mounts = {mount["target"]: mount for mount in api["volumes"]}
        for name in ("server.crt", "server.key", "clients-ca.crt"):
            mount = mounts["/run/secrets/translator-api/" + name]
            self.assertTrue(mount["read_only"])
            self.assertFalse(mount["bind"].get("create_host_path", False))
        self.assertFalse(any("operator" in key or "ca.key" in key for key in mounts))

    def test_restart_policy_distinguishes_migration(self) -> None:
        services = _resolved_compose()["services"]
        for name, service in services.items():
            if name == "translator-migrator":
                expected = "no"
            elif name == "translator-topic-provisioner":
                expected = "on-failure"
            else:
                expected = "unless-stopped"
            self.assertEqual(service.get("restart"), expected, name)


if __name__ == "__main__":
    unittest.main()
