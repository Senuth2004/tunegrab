"""Use the host's trusted certificate store in frozen Linux builds."""
from __future__ import annotations

import os
import sys
from pathlib import Path

SYSTEM_CA_BUNDLES = (
    Path("/etc/pki/tls/certs/ca-bundle.crt"),
    Path("/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem"),
    Path("/etc/ssl/certs/ca-certificates.crt"),
)


def configure_system_ca_bundle() -> None:
    if not sys.platform.startswith("linux") or os.environ.get("SSL_CERT_FILE"):
        return
    for bundle in SYSTEM_CA_BUNDLES:
        if bundle.is_file():
            os.environ["SSL_CERT_FILE"] = str(bundle)
            return
