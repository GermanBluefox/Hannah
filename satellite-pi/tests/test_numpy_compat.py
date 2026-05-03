"""
Numpy compatibility tests for satellite-pi.

Tests the numpy patterns used in satellite.py without importing the full
module (which requires PyAudio, OpenWakeWord and other hardware deps).
Run with: pytest satellite-pi/tests/ -v
"""
import numpy as np
import pytest


def _resample(data: np.ndarray, src_rate: int, dst_rate: int = 16000) -> np.ndarray:
    """Linear resampling — copy of satellite.py _resample for isolated testing."""
    if src_rate == dst_rate:
        return data
    target_len = int(len(data) * dst_rate / src_rate)
    return np.interp(
        np.linspace(0, len(data), target_len),
        np.arange(len(data)),
        data,
    ).astype(np.int16)


class TestResample:
    def test_same_rate_returns_unchanged(self):
        data = np.array([100, 200, 300], dtype=np.int16)
        result = _resample(data, src_rate=16000, dst_rate=16000)
        np.testing.assert_array_equal(result, data)

    def test_downsample_24k_to_16k(self):
        # Main use case: TTS audio from Hannah arrives at 24kHz, satellite plays at 16kHz
        src = np.zeros(24000, dtype=np.int16)
        result = _resample(src, src_rate=24000, dst_rate=16000)
        assert len(result) == 16000
        assert result.dtype == np.int16

    def test_upsample_16k_to_24k(self):
        src = np.zeros(16000, dtype=np.int16)
        result = _resample(src, src_rate=16000, dst_rate=24000)
        assert len(result) == 24000
        assert result.dtype == np.int16

    def test_output_dtype_is_int16(self):
        src = np.array([0, 1000, -1000, 32767, -32768], dtype=np.int16)
        result = _resample(src, src_rate=48000, dst_rate=16000)
        assert result.dtype == np.int16

    def test_output_length_correct(self):
        for src_rate, dst_rate in [(44100, 16000), (48000, 16000), (22050, 16000)]:
            src = np.zeros(src_rate, dtype=np.int16)  # 1 second of audio
            result = _resample(src, src_rate=src_rate, dst_rate=dst_rate)
            expected_len = int(src_rate * dst_rate / src_rate)
            assert len(result) == expected_len, f"{src_rate}→{dst_rate}: expected {expected_len}, got {len(result)}"


class TestFrombuffer:
    def test_frombuffer_int16(self):
        # Pattern used in satellite.py to convert received PCM bytes to numpy array
        raw = bytes([0x00, 0x01, 0xFF, 0x7F])
        result = np.frombuffer(raw, dtype=np.int16)
        assert result.dtype == np.int16
        assert len(result) == 2

    def test_frombuffer_roundtrip(self):
        original = np.array([100, -200, 30000, -32768], dtype=np.int16)
        raw = original.tobytes()
        restored = np.frombuffer(raw, dtype=np.int16)
        np.testing.assert_array_equal(original, restored)
