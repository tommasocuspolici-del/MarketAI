"""Tests for HardwareDetector (Fase 9 DoD)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from engine.llm.hardware_detector import (
    HardwareDetector,
    HardwareReport,
    LLMErrorCode,
    LLM_ERROR_MESSAGES,
    MODEL_REQUIREMENTS,
    detect_hardware,
)


def _make_hw(ram_avail: float = 8.0, disk: float = 50.0) -> HardwareReport:
    with patch.object(HardwareDetector, "_get_ram", return_value=(16.0, ram_avail)), \
         patch.object(HardwareDetector, "_get_disk", return_value=disk), \
         patch.object(HardwareDetector, "_get_gpu_vram", return_value=None):
        return HardwareDetector().detect()


def test_detect_returns_hardware_report():
    hw = _make_hw()
    assert isinstance(hw, HardwareReport)


def test_can_run_llm_with_sufficient_ram():
    hw = _make_hw(ram_avail=8.0)
    assert hw.can_run_llm is True


def test_cannot_run_llm_with_insufficient_ram():
    hw = _make_hw(ram_avail=2.0)
    assert hw.can_run_llm is False
    assert hw.recommended_model is None


def test_recommends_mistral_with_5gb_ram():
    hw = _make_hw(ram_avail=6.0)
    assert hw.recommended_model == "mistral:7b-q4"


def test_recommends_phi3_with_4gb_ram():
    hw = _make_hw(ram_avail=4.5)
    assert hw.recommended_model == "phi3:mini"


def test_supported_models_subset_of_requirements():
    hw = _make_hw(ram_avail=5.5)
    for m in hw.supported_models:
        assert m in MODEL_REQUIREMENTS


def test_error_on_low_ram():
    hw = _make_hw(ram_avail=1.0)
    assert any("RAM" in e for e in hw.errors)


def test_error_on_low_disk():
    hw = _make_hw(disk=1.0)
    assert any("disco" in e.lower() or "disk" in e.lower() for e in hw.errors)


def test_error_messages_formatted():
    msg = LLM_ERROR_MESSAGES[LLMErrorCode.RAM_INSUFFICIENT].format(free_ram=3.5)
    assert "3.5" in msg


def test_detect_hardware_convenience_function():
    with patch.object(HardwareDetector, "_get_ram", return_value=(8.0, 8.0)), \
         patch.object(HardwareDetector, "_get_disk", return_value=20.0), \
         patch.object(HardwareDetector, "_get_gpu_vram", return_value=None):
        hw = detect_hardware()
    assert isinstance(hw, HardwareReport)
