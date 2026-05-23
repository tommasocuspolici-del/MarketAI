"""Test per bridge/override_store_factory.py.

Verifica che la factory restituisca un oggetto con il metodo resolve()
compatibile con OverrideStoreProtocol.
"""
from __future__ import annotations

import pytest


class TestOverrideStoreFactory:
    def test_importable(self) -> None:
        from bridge.override_store_factory import get_default_override_store
        assert callable(get_default_override_store)

    def test_returns_object_with_resolve(self) -> None:
        from bridge.override_store_factory import get_default_override_store
        store = get_default_override_store()
        assert hasattr(store, "resolve"), "ManualOverrideStore deve avere il metodo resolve()"

    def test_resolve_signature(self, tmp_path) -> None:
        from personal.data_entry.override_store import ManualOverrideStore
        store = ManualOverrideStore(db_path=tmp_path / "test.db")
        result = store.resolve("price", "S&P 500", api_value=4500.0)
        assert isinstance(result, tuple)
        assert len(result) == 2
        value, is_override = result
        assert value == 4500.0
        assert is_override is False

    def test_no_engine_import_from_personal_in_live_market_service(self) -> None:
        """Regressione: live_market_service.py non deve importare da personal.*"""
        import ast
        import pathlib
        src = pathlib.Path("engine/market_data/live_market_service.py")
        if not src.exists():
            pytest.skip("file non trovato")
        tree = ast.parse(src.read_text(encoding="utf-8"))
        personal_imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module == "personal" or node.module.startswith("personal."):
                    personal_imports.append(node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "personal" or alias.name.startswith("personal."):
                        personal_imports.append(alias.name)
        assert personal_imports == [], (
            f"live_market_service.py importa da personal/: {personal_imports}"
        )
