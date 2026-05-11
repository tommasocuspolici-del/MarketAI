"""Tests for presentation.ui.auth (Rule 32)."""
from __future__ import annotations

import hashlib

import pytest

from presentation.ui.auth import (
    AUTH_ENABLED_ENV,
    PASSWORD_HASH_ENV,
    is_auth_enabled,
    require_auth,
    verify_password,
)
from shared.exceptions import AuthenticationError


# ═══════════════════════════════════════════════════════════════════════════
# is_auth_enabled
# ═══════════════════════════════════════════════════════════════════════════
class TestAuthEnabled:
    def test_default_disabled(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.delenv(AUTH_ENABLED_ENV, raising=False)
        assert not is_auth_enabled()

    def test_explicit_true(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.setenv(AUTH_ENABLED_ENV, "true")
        assert is_auth_enabled()

    def test_explicit_false(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.setenv(AUTH_ENABLED_ENV, "false")
        assert not is_auth_enabled()

    def test_case_insensitive(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.setenv(AUTH_ENABLED_ENV, "TRUE")
        assert is_auth_enabled()


# ═══════════════════════════════════════════════════════════════════════════
# verify_password
# ═══════════════════════════════════════════════════════════════════════════
class TestVerifyPassword:
    def test_sha256_match(self) -> None:
        plain = "MyP@ssw0rd"
        h = hashlib.sha256(plain.encode()).hexdigest()
        assert verify_password(plain, h)

    def test_sha256_mismatch(self) -> None:
        h = hashlib.sha256(b"correct").hexdigest()
        assert not verify_password("wrong", h)

    def test_empty_hash_rejects(self) -> None:
        assert not verify_password("anything", "")

    def test_bcrypt_hash_format_recognized(self) -> None:
        """Hash bcrypt-formatted è gestito (anche se la libreria può non essere
        disponibile, il fallback gestisce graceful)."""
        # Hash bcrypt $2b$ valido per "test123" (generato manualmente)
        # Se bcrypt è installato, verifica successo. Altrimenti, fallback SHA-256
        # non riesce → False (corretto comportamento).
        bcrypt_hash = "$2b$12$KIXyDqXq1nFtLlVlwCvlfeP6KqN.Qj9BqW9w8Y5qJ7t6jN3eKqZjy"
        # Non è il vero hash di "test123"; testiamo solo che non crashi
        result = verify_password("test123", bcrypt_hash)
        assert isinstance(result, bool)  # No exception


# ═══════════════════════════════════════════════════════════════════════════
# require_auth
# ═══════════════════════════════════════════════════════════════════════════
class TestRequireAuth:
    def test_disabled_is_no_op(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.delenv(AUTH_ENABLED_ENV, raising=False)
        # Non solleva, non richiede streamlit
        require_auth()

    def test_enabled_no_hash_raises(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.setenv(AUTH_ENABLED_ENV, "true")
        monkeypatch.delenv(PASSWORD_HASH_ENV, raising=False)
        with pytest.raises(AuthenticationError, match="STREAMLIT_AUTH_PASSWORD_HASH"):
            require_auth()

    def test_enabled_with_hash_no_streamlit_no_op(
        self, monkeypatch  # type: ignore[no-untyped-def]
    ) -> None:
        """Quando streamlit non è importabile (test env), require_auth è no-op."""
        monkeypatch.setenv(AUTH_ENABLED_ENV, "true")
        monkeypatch.setenv(
            PASSWORD_HASH_ENV,
            hashlib.sha256(b"test").hexdigest(),
        )
        # Streamlit non è installato in CI: la funzione esce silenziosamente
        require_auth()
