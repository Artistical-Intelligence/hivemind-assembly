import json
import os
import uuid
import pytest
from hivemind_assembly.integrations.credential_chunks import WindowsChunks
from hivemind_assembly.integrations.github import CredentialVault


def test_large_vault_values_atomic_failure_and_legacy_migration():
    class Backend:
        values = {}
        fail = False
        lost_ack = False

        def get_password(self, service, user):
            return self.values.get((service, user))

        def set_password(self, service, user, password):
            assert len(password.encode("utf-16-le")) <= 2560
            if self.fail and service.endswith(".1"):
                raise OSError("Fixture storage failure")
            self.values[service, user] = password
            if self.lost_ack and ".ha-root." in service:
                raise OSError("Fixture lost manifest acknowledgement")

        def delete_password(self, service, user):
            del self.values[service, user]

    backend = Backend()
    chunks = WindowsChunks(
        backend,
        lambda prefix: [
            name for name, user in backend.values if name.startswith(prefix)
        ],
    )
    backend.values["service", "owner"] = "legacy"
    assert chunks.get_password("service", "owner") == "legacy"
    old = json.dumps({"tokens": "A" * 15000, "unicode": "\U0001f41d" * 1000})
    chunks.set_password("service", "owner", old)
    assert chunks.get_password("service", "owner") == old
    assert ("service", "owner") not in backend.values
    backend.fail = True
    with pytest.raises(OSError):
        chunks.set_password("service", "owner", "new" * 5000)
    assert chunks.get_password("service", "owner") == old
    backend.fail = False
    backend.lost_ack = True
    with pytest.raises(OSError, match="acknowledgement"):
        chunks.set_password("service", "owner", "committed")
    assert chunks.get_password("service", "owner") == "committed"
    backend.lost_ack = False
    chunks.set_password("service", "other-owner", "other")
    chunks.set_password("service", "owner", "replacement")
    root, prefix = chunks.names("service", "owner")
    assert len([name for name, _ in backend.values if name.startswith(prefix)]) == 1
    # Forget must work even if a crash/corruption left one generation incomplete.
    part = next(key for key in backend.values if key[0].startswith(prefix))
    del backend.values[part]
    with pytest.raises(ValueError, match="Incomplete"):
        chunks.get_password("service", "owner")
    chunks.delete_password("service", "owner")
    assert chunks.get_password("service", "owner") is None
    assert chunks.get_password("service", "other-owner") == "other"


@pytest.mark.skipif(os.name != "nt", reason="Real Windows Credential Manager")
def test_real_windows_vault_large_oauth_records(tmp_path):
    vault = CredentialVault(tmp_path, "Test." + uuid.uuid4().hex)
    value = {
        "access_token": "fixture-" + "a" * 12000,
        "refresh_token": "b" * 6000,
        "metadata": {"issuer": "https://fixture.invalid"},
    }
    try:
        vault.write(value)
        assert vault.read() == value
        vault.write({"replacement": "fixture"})
        assert vault.read() == {"replacement": "fixture"}
    finally:
        vault.clear()
    assert vault.read() is None
    assert not list(tmp_path.rglob("*"))  # No plaintext or encrypted file fallback.
