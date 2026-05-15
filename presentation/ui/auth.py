"""Streamlit authentication — Rule 32 (auth obbligatoria in produzione).

Configurazione via .env:
  STREAMLIT_AUTH_ENABLED=true            # Default false (disabilitato in dev)
  STREAMLIT_AUTH_PASSWORD_HASH=...        # bcrypt hash (NON la password!)

Generazione hash:
  python -c "import bcrypt; print(bcrypt.hashpw(b'mypass', bcrypt.gensalt()).decode())"

Utilizzo all'inizio di ogni pagina dashboard:
  from presentation.ui.auth import require_auth
  require_auth()  # Blocca la pagina se non autenticato
"""
from __future__ import annotations

import hashlib
import hmac
import os

from presentation.ui.session_keys import SK
from shared.exceptions import AuthenticationError
from shared.logger import get_logger

__version__ = "6.0.0"

__all__ = [
    "AUTH_ENABLED_ENV",
    "PASSWORD_HASH_ENV",
    "is_auth_enabled",
    "require_auth",
    "verify_password",
]

log = get_logger(__name__)

AUTH_ENABLED_ENV = "STREAMLIT_AUTH_ENABLED"
PASSWORD_HASH_ENV = "STREAMLIT_AUTH_PASSWORD_HASH"


# ═══════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════
def is_auth_enabled() -> bool:
    """Check if authentication is enabled via env var."""
    return os.getenv(AUTH_ENABLED_ENV, "false").lower() == "true"


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Verify a plain password against a stored hash.

    Tries bcrypt first; falls back to SHA-256 hex when bcrypt is not
    available (per evitare hard-dependency su bcrypt in dev).

    NOTE: SHA-256 fallback is for development convenience only.
    In production STREAMLIT_AUTH_PASSWORD_HASH MUST be a bcrypt hash.
    """
    if not password_hash:
        return False

    # Tentativo 1: bcrypt
    try:
        import bcrypt

        if password_hash.startswith(("$2a$", "$2b$", "$2y$")):
            return bool(
                bcrypt.checkpw(plain_password.encode(), password_hash.encode())
            )
    except ImportError:
        log.debug("auth.bcrypt_unavailable_using_sha256")

    # Tentativo 2: SHA-256 (fallback dev)
    expected = hashlib.sha256(plain_password.encode()).hexdigest()
    # hmac.compare_digest per timing-safe comparison
    return hmac.compare_digest(expected, password_hash)


def require_auth() -> None:
    """Block the current Streamlit page until authenticated.

    Call this as the FIRST instruction of every dashboard page when
    STREAMLIT_AUTH_ENABLED=true. No-op when auth is disabled.

    Raises:
        AuthenticationError: When auth is enabled but no password hash
            is configured (mis-deployment).
    """
    if not is_auth_enabled():
        return  # Disabilitato in dev locale

    password_hash = os.getenv(PASSWORD_HASH_ENV, "")
    if not password_hash:
        raise AuthenticationError(
            f"Auth abilitata ma {PASSWORD_HASH_ENV} non configurato in .env. "
            f"Generare hash con: python -c \"import bcrypt; "
            f"print(bcrypt.hashpw(b'pwd', bcrypt.gensalt()).decode())\""
        )

    # Streamlit è opzionale — quando non importabile (test, CLI),
    # questa funzione è no-op (la chiamata avverrà solo in dashboard live)
    try:  # pragma: no cover
        import streamlit as st
    except ImportError:
        log.warning("auth.streamlit_unavailable")
        return

    # Già autenticato in questa session?
    if st.session_state.get(SK.AUTHENTICATED, False):
        return

    # Form di login
    st.markdown("## 🔐 Accesso Richiesto")
    with st.form("login_form"):
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Accedi")

    if submitted:
        if verify_password(password, password_hash):
            st.session_state[SK.AUTHENTICATED] = True
            log.info("auth.login_success")
            st.rerun()
        else:
            log.warning("auth.login_failed")
            st.error("Password errata.")

    # Blocca il resto della pagina
    st.stop()
