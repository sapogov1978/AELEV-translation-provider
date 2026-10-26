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


def _resolved_compose(
    path: Path = COMPOSE_PATH, *, overrides: dict[str, str] | None = None
) -> dict[str, Any]:
    environment = _clean_environment()
    environment.update(overrides or {})
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
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    return cast(dict[str, Any], json.loads(result.stdout))


@unittest.skipUnless(shutil.which("docker"), "Docker CLI is required")
class TranslatorConfigurationTest(unittest.TestCase):
    def test_background_probes_and_sender_do_not_import_the_application(self) -> None:
        resolved = _resolved_compose(overrides={"COMPOSE_PROFILES": "*"})
        services = resolved["services"]
        for name, role in (
            ("translator-normal-consumer", "consumer"),
            ("translator-priority-consumer", "consumer"),
            ("translator-worker", "worker"),
            ("translator-outbox", "outbox"),
        ):
            selected = services[name]
            self.assertEqual(
                selected["environment"]["AELEV_TRANSLATOR_HEALTH_ROLE"], role
            )
            self.assertEqual(
                selected["healthcheck"]["test"],
                [
                    "CMD",
                    "python",
                    "-S",
                    "/opt/aelev/src/translator_service/local_health.py",
                ],
            )
            self.assertEqual(selected["healthcheck"]["retries"], 3)
        sender = services["translator-telemetry-sender"]
        self.assertEqual(
            sender["healthcheck"]["test"],
            ["CMD", "python", "-S", "/opt/aelev/delivery_health.py"],
        )
        self.assertEqual(sender["stop_grace_period"], "1m0s")
        self.assertEqual(
            sender["depends_on"]["translator-telemetry-data-init"]["condition"],
            "service_completed_successfully",
        )
        self.assertIn("@sha256:", sender["image"])
        subnet = resolved["networks"]["translator-telemetry-egress"]["ipam"]["config"][
            0
        ]["subnet"]
        self.assertEqual(subnet, "10.253.40.0/24")

    def test_background_image_override_does_not_switch_api_or_model(self) -> None:
        key = "AELEV_INFRASTRUCTURE_TRANSLATOR_BACKGROUND_IMAGE"
        services = _resolved_compose(overrides={key: "own-background:checked"})[
            "services"
        ]
        for name in (
            "translator-normal-consumer",
            "translator-priority-consumer",
            "translator-worker",
            "translator-outbox",
        ):
            self.assertEqual(services[name]["image"], "own-background:checked")
        for name in ("translator-api", "translator-model"):
            self.assertNotEqual(services[name]["image"], "own-background:checked")

    def test_model_override_is_isolated_and_has_a_startup_window(self) -> None:
        services = _resolved_compose(
            overrides={
                "AELEV_INFRASTRUCTURE_TRANSLATOR_MODEL_IMAGE": "own-model:checked",
                "AELEV_INFRASTRUCTURE_TRANSLATOR_MODEL_RESTART_POLICY": "on-failure:2",
                "AELEV_INFRASTRUCTURE_TRANSLATOR_MODEL_STARTUP_TIMEOUT_SECONDS": "700",
            }
        )["services"]
        model = services["translator-model"]
        self.assertEqual(model["image"], "own-model:checked")
        self.assertEqual(model["restart"], "on-failure:2")
        self.assertEqual(model["healthcheck"]["start_period"], "11m40s")
        self.assertEqual(
            model["environment"]["AELEV_TRANSLATOR_STARTUP_TIMEOUT_SECONDS"], "700"
        )
        for name, service in services.items():
            if name != "translator-model":
                self.assertNotEqual(service.get("image"), "own-model:checked")

    def test_model_and_api_use_local_minimal_probes(self) -> None:
        services = _resolved_compose()["services"]
        for role, name, retries in (
            ("model", "translator-model", 30),
            ("api", "translator-api", 12),
        ):
            selected = services[name]
            self.assertEqual(
                selected["healthcheck"]["test"],
                [
                    "CMD",
                    "python",
                    "-S",
                    "/opt/aelev/src/translator_service/local_health.py",
                ],
            )
            self.assertEqual(
                selected["environment"]["AELEV_TRANSLATOR_HEALTH_ROLE"], role
            )
            self.assertEqual(selected["healthcheck"]["timeout"], "5s")
            self.assertEqual(selected["healthcheck"]["retries"], retries)

    def test_light_status_image_contains_required_lock_metadata(self) -> None:
        stage = (
            (COMPONENT_ROOT / "Dockerfile")
            .read_text()
            .split("FROM python-bookworm AS status-runtime", 1)[1]
            .split("FROM python-bookworm AS index-runtime-builder", 1)[0]
        )
        self.assertIn(
            "AELEV_TRANSLATOR_LOCK_PATH=/opt/aelev/translator.lock.json", stage
        )
        self.assertIn("COPY translator.lock.json", stage)
        self.assertIn("read_translator_lock", stage)
        self.assertNotIn("index-model-assets", stage)
        self.assertNotIn("COPY --from=index-runtime-builder", stage)

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

    def test_role_secret_mounts_are_minimal(self) -> None:
        services = _resolved_compose()["services"]

        def targets(role: str) -> set[str]:
            return {
                volume["target"]
                for volume in services[role].get("volumes", [])
                if isinstance(volume, dict)
            }

        self.assertEqual(
            targets("translator-worker"),
            {
                "/run/aelev-translator",
                "/run/secrets/database",
                "/run/secrets/telemetry/client",
            },
        )
        self.assertEqual(
            targets("translator-topic-provisioner"), {"/run/secrets/kafka-admin"}
        )
        self.assertNotIn(
            "/run/secrets/kafka-admin", targets("translator-normal-consumer")
        )
        self.assertNotIn("/run/secrets/status-admin", targets("translator-api"))
        for role in (
            "translator-migrator",
            "translator-topic-provisioner",
            "translator-priority-consumer",
            "translator-normal-consumer",
            "translator-worker",
            "translator-outbox",
            "translator-api",
        ):
            self.assertEqual(services[role]["group_add"], ["20"])

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
            "on-failure:3",
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
        for suffix in (
            "HIGH_PRIORITY_BURST",
            "API_TRANSLATION_ENABLED",
            "API_TRANSLATION_TIMEOUT_SECONDS",
            "API_TRANSLATION_MAX_IN_FLIGHT",
        ):
            with self.subTest(setting=suffix):
                environment = _clean_environment()
                variable = "AELEV_INFRASTRUCTURE_TRANSLATOR_" + suffix
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
            set(services["translator-worker"]["networks"]),
            {"translator-data", "translator-telemetry"},
        )
        self.assertTrue(services["translator-worker"]["volumes"][0]["read_only"])
        for role in (
            "translator-priority-consumer",
            "translator-normal-consumer",
            "translator-outbox",
        ):
            self.assertEqual(
                set(services[role]["networks"]),
                {"kafka", "translator-data", "translator-telemetry"},
            )
        self.assertEqual(
            set(services["translator-api"]["networks"]),
            {
                "kafka",
                "translator-data",
                "translator-ingress",
                "translator-telemetry",
            },
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
        mount = mounts["/run/secrets/translator-api"]
        self.assertTrue(mount["read_only"])
        self.assertFalse(mount["bind"].get("create_host_path", False))
        self.assertTrue(mount["source"].endswith("runtime/api-pki/api-tls"))
        self.assertFalse(any("operator" in key or "ca.key" in key for key in mounts))

    def test_restart_policy_distinguishes_migration(self) -> None:
        services = _resolved_compose(overrides={"COMPOSE_PROFILES": "*"})["services"]
        for name, service in services.items():
            if not name.startswith("translator-"):
                continue  # Included providers own their recovery policy.
            if name in {
                "translator-migrator",
                "translator-telemetry-data-init",
                "translator-service-status-provision",
                "translator-api-provision",
            }:
                expected = "no"
            else:
                expected = "on-failure:3"
            self.assertEqual(service.get("restart"), expected, name)

    def test_restart_overrides_preserve_smaller_existing_budgets(self) -> None:
        prefix = "AELEV_INFRASTRUCTURE_TRANSLATOR_"
        services = _resolved_compose(
            overrides={
                "COMPOSE_PROFILES": "*",
                prefix + "RESTART_POLICY": "on-failure:2",
                prefix + "UI_RESTART_POLICY": "no",
                prefix + "TELEMETRY_RESTART_POLICY": "on-failure:1",
                prefix + "TOPIC_PROVISIONER_RESTART_POLICY": "no",
            }
        )["services"]
        for name in ROLES - {"translator-migrator", "translator-topic-provisioner"}:
            self.assertEqual(services[name]["restart"], "on-failure:2", name)
        for name in (
            "translator-service-status-publisher",
            "translator-topic-provisioner",
            "translator-migrator",
        ):
            self.assertEqual(services[name]["restart"], "no", name)
        self.assertEqual(
            services["translator-telemetry-sender"]["restart"], "on-failure:1"
        )


if __name__ == "__main__":
    unittest.main()
