"""Tests for shared.resilience.error_policy."""
from __future__ import annotations

import logging
import pytest

from shared.resilience.error_policy import (
    ErrorLevel,
    ErrorPolicy,
    apply_error_policy,
    error_policy,
)


# ─────────────────────────────────────────────── ErrorLevel

def test_error_level_values():
    assert ErrorLevel.RECOVER == "RECOVER"
    assert ErrorLevel.DEGRADE == "DEGRADE"
    assert ErrorLevel.FATAL == "FATAL"


# ─────────────────────────────────────────────── ErrorPolicy.handle — RECOVER

def test_recover_returns_fallback_and_does_not_raise():
    policy = ErrorPolicy()
    exc = ValueError("boom")
    result = policy.handle(exc, level=ErrorLevel.RECOVER, context="test", fallback=42.0)
    assert result == 42.0


def test_recover_logs_warning(caplog):
    policy = ErrorPolicy()
    exc = ValueError("boom")
    with caplog.at_level(logging.WARNING, logger="shared.resilience.error_policy"):
        policy.handle(exc, level=ErrorLevel.RECOVER, context="ctx.test", fallback=None)
    assert any("RECOVER" in r.message and "ctx.test" in r.message for r in caplog.records)
    assert all(r.levelno == logging.WARNING for r in caplog.records if "RECOVER" in r.message)


def test_recover_fallback_none_by_default():
    policy = ErrorPolicy()
    result = policy.handle(ValueError("x"), level=ErrorLevel.RECOVER, context="c")
    assert result is None


# ─────────────────────────────────────────────── ErrorPolicy.handle — DEGRADE

def test_degrade_returns_fallback_and_does_not_raise():
    policy = ErrorPolicy()
    result = policy.handle(RuntimeError("db down"), level=ErrorLevel.DEGRADE, context="db", fallback=[])
    assert result == []


def test_degrade_logs_error(caplog):
    policy = ErrorPolicy()
    exc = RuntimeError("db down")
    with caplog.at_level(logging.ERROR, logger="shared.resilience.error_policy"):
        policy.handle(exc, level=ErrorLevel.DEGRADE, context="db.ctx", fallback=None)
    assert any("DEGRADE" in r.message and "db.ctx" in r.message for r in caplog.records)
    assert any(r.levelno == logging.ERROR for r in caplog.records if "DEGRADE" in r.message)


# ─────────────────────────────────────────────── ErrorPolicy.handle — FATAL

def test_fatal_reraises_original_exception():
    policy = ErrorPolicy()
    original = KeyError("missing_key")
    with pytest.raises(KeyError) as exc_info:
        policy.handle(original, level=ErrorLevel.FATAL, context="fatal_ctx")
    assert exc_info.value is original


def test_fatal_logs_critical(caplog):
    policy = ErrorPolicy()
    exc = KeyError("k")
    with caplog.at_level(logging.CRITICAL, logger="shared.resilience.error_policy"):
        with pytest.raises(KeyError):
            policy.handle(exc, level=ErrorLevel.FATAL, context="fatal.test")
    assert any("FATAL" in r.message for r in caplog.records)
    assert any(r.levelno == logging.CRITICAL for r in caplog.records if "FATAL" in r.message)


# ─────────────────────────────────────────────── apply_error_policy decorator

def test_apply_error_policy_decorator_recover():
    @apply_error_policy(level="RECOVER", fallback=-1.0, context="test.fn")
    def always_fails(x: int) -> float:
        raise ValueError(f"fail {x}")

    assert always_fails(5) == -1.0


def test_apply_error_policy_decorator_recover_success():
    @apply_error_policy(level="RECOVER", fallback=0.0)
    def works(x: int) -> int:
        return x * 2

    assert works(3) == 6


def test_apply_error_policy_decorator_fatal_reraises():
    @apply_error_policy(level="FATAL")
    def always_fails() -> None:
        raise RuntimeError("fatal!")

    with pytest.raises(RuntimeError, match="fatal!"):
        always_fails()


def test_apply_error_policy_uses_qualname_as_context(caplog):
    @apply_error_policy(level="RECOVER", fallback=None)
    def my_function() -> None:
        raise ValueError("no context provided")

    with caplog.at_level(logging.WARNING, logger="shared.resilience.error_policy"):
        my_function()

    assert any("my_function" in r.message for r in caplog.records)


def test_apply_error_policy_custom_context_overrides_qualname(caplog):
    @apply_error_policy(level="RECOVER", fallback=None, context="custom.ctx")
    def some_fn() -> None:
        raise ValueError("x")

    with caplog.at_level(logging.WARNING, logger="shared.resilience.error_policy"):
        some_fn()

    assert any("custom.ctx" in r.message for r in caplog.records)


def test_apply_error_policy_preserves_function_name():
    @apply_error_policy(level="RECOVER", fallback=None)
    def my_named_fn() -> None:
        pass

    assert my_named_fn.__name__ == "my_named_fn"


# ─────────────────────────────────────────────── module-level singleton

def test_module_level_singleton_is_error_policy_instance():
    assert isinstance(error_policy, ErrorPolicy)


def test_module_level_singleton_recover():
    result = error_policy.handle(
        ValueError("x"), level=ErrorLevel.RECOVER, context="singleton_test", fallback="default"
    )
    assert result == "default"
