"""Tests for shared.feature_flags."""
from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from shared.exceptions import FeatureDisabledError

if TYPE_CHECKING:
    from pathlib import Path


def _write_flags(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


@pytest.fixture
def flags_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point FEATURE_FLAGS_PATH to a temp file and reset the cache."""
    path = tmp_path / "feature_flags.yaml"
    # Monkey-patch the module-level path + clear cache
    monkeypatch.setattr("shared.feature_flags.FEATURE_FLAGS_PATH", path)

    from shared.feature_flags import reload_flags

    reload_flags()
    yield path
    reload_flags()


class TestIsEnabled:
    def test_returns_true_for_enabled_flag(self, flags_file: Path) -> None:
        _write_flags(flags_file, "my_feature: true\n")
        from shared.feature_flags import is_enabled, reload_flags

        reload_flags()
        assert is_enabled("my_feature") is True

    def test_returns_false_for_disabled_flag(self, flags_file: Path) -> None:
        _write_flags(flags_file, "my_feature: false\n")
        from shared.feature_flags import is_enabled, reload_flags

        reload_flags()
        assert is_enabled("my_feature") is False

    def test_returns_false_for_unknown_flag(self, flags_file: Path) -> None:
        _write_flags(flags_file, "my_feature: true\n")
        from shared.feature_flags import is_enabled, reload_flags

        reload_flags()
        assert is_enabled("never_defined") is False

    def test_returns_false_when_file_missing(self, tmp_path: Path,
                                              monkeypatch: pytest.MonkeyPatch) -> None:
        missing = tmp_path / "does_not_exist.yaml"
        monkeypatch.setattr("shared.feature_flags.FEATURE_FLAGS_PATH", missing)

        from shared.feature_flags import is_enabled, reload_flags

        reload_flags()
        assert is_enabled("anything") is False

    def test_ignores_non_bool_values(self, flags_file: Path) -> None:
        _write_flags(flags_file, 'my_feature: "yes"\nother: true\n')
        from shared.feature_flags import is_enabled, reload_flags

        reload_flags()
        # "yes" non è un bool → scartato
        assert is_enabled("my_feature") is False
        # other rimane boolean valido
        assert is_enabled("other") is True


class TestRequireEnabled:
    def test_passes_when_flag_enabled(self, flags_file: Path) -> None:
        _write_flags(flags_file, "go: true\n")
        from shared.feature_flags import reload_flags, require_enabled

        reload_flags()
        # Non deve sollevare
        require_enabled("go")

    def test_raises_when_flag_disabled(self, flags_file: Path) -> None:
        _write_flags(flags_file, "go: false\n")
        from shared.feature_flags import reload_flags, require_enabled

        reload_flags()
        with pytest.raises(FeatureDisabledError, match="'go'"):
            require_enabled("go")


class TestAllFlags:
    def test_returns_copy_of_all_flags(self, flags_file: Path) -> None:
        _write_flags(flags_file, "a: true\nb: false\n")
        from shared.feature_flags import all_flags, reload_flags

        reload_flags()
        flags = all_flags()
        assert flags == {"a": True, "b": False}

        # Mutazione del risultato non deve impattare la cache interna
        flags["a"] = False
        assert all_flags()["a"] is True
