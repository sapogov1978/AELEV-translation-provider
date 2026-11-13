"""Explicit generic listener configuration, independent of model implementation."""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .tls_identity import IdentityError, object_value, read_file


@dataclass(frozen=True)
class Transport:
    mode: Literal["uds", "mtls"]
    root: Path
    host: str = "0.0.0.0"
    port: int = 18487

    @classmethod
    def environment(cls) -> Transport:
        root = Path(
            os.environ.get(
                "AELEV_TRANSLATION_PROVIDER_TLS_ROOT", "/run/secrets/compute-provider"
            )
        )
        path = root / "transport.json"
        if not os.path.lexists(path):
            # Existing signed UDS installations remain compatible. A partial
            # network installation must never silently choose that transport.
            if os.path.lexists(root / "identity.json"):
                raise RuntimeError("PROVIDER_TRANSPORT_CONFIG_INVALID")
            return cls("uds", root)
        try:
            value = object_value(read_file(path, 4096))
            if (
                set(value)
                != {"schema_version", "transport", "listen_host", "listen_port"}
                or type(value["schema_version"]) is not int
                or value["schema_version"] != 1
                or value["transport"] != "mtls"
                or not isinstance(value["listen_host"], str)
                or type(value["listen_port"]) is not int
                or not 1024 <= value["listen_port"] <= 65535
            ):
                raise ValueError
            ipaddress.ip_address(value["listen_host"])
            return cls("mtls", root, value["listen_host"], value["listen_port"])
        except (OSError, ValueError, TypeError, IdentityError):
            raise RuntimeError("PROVIDER_TRANSPORT_CONFIG_INVALID") from None
