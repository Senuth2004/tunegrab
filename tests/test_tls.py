import os

from tunegrab import tls


def test_linux_uses_system_ca_bundle_when_no_override(monkeypatch, tmp_path):
    bundle = tmp_path / "ca-bundle.pem"
    bundle.write_text("test certificates")
    monkeypatch.setattr(tls.sys, "platform", "linux")
    monkeypatch.setattr(tls, "SYSTEM_CA_BUNDLES", (bundle,))
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)

    tls.configure_system_ca_bundle()

    assert os.environ["SSL_CERT_FILE"] == str(bundle)


def test_custom_ca_bundle_is_preserved(monkeypatch, tmp_path):
    custom_bundle = str(tmp_path / "custom.pem")
    monkeypatch.setattr(tls.sys, "platform", "linux")
    monkeypatch.setenv("SSL_CERT_FILE", custom_bundle)
    monkeypatch.setattr(tls, "SYSTEM_CA_BUNDLES", ())

    tls.configure_system_ca_bundle()

    assert os.environ["SSL_CERT_FILE"] == custom_bundle


def test_non_linux_keeps_native_certificate_store(monkeypatch):
    monkeypatch.setattr(tls.sys, "platform", "win32")
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.setattr(tls, "SYSTEM_CA_BUNDLES", ())

    tls.configure_system_ca_bundle()

    assert "SSL_CERT_FILE" not in os.environ
