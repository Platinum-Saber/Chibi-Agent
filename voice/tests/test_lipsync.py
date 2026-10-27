import numpy as np

from chibi_voice.lipsync import FLOOR, block_size, levels

SR = 24000


def test_block_size_is_one_sixtieth():
    assert block_size(24000) == 400
    assert block_size(16000) == 267
    assert block_size(48000) == 800


def test_one_value_per_block():
    assert len(levels(np.zeros(400 * 5, np.float32), SR)) == 5
    assert len(levels(np.zeros(400 * 5 + 1, np.float32), SR)) == 6
    assert len(levels(np.zeros(0, np.float32), SR)) == 0


def test_silence_is_zero():
    assert np.all(levels(np.zeros(SR, np.float32), SR) == 0)


def test_loudest_block_is_one_and_range_is_0_1():
    t = np.arange(SR) / SR
    env = np.linspace(0, 1, SR)
    lv = levels(0.5 * env * np.sin(2 * np.pi * 220 * t), SR)
    assert lv.max() == 1.0
    assert lv.min() >= 0.0
    assert np.all(np.diff(lv[5:]) >= -0.05)  # follows the rising envelope


def test_scale_invariant_above_floor():
    t = np.arange(SR) / SR
    x = np.sin(2 * np.pi * 220 * t).astype(np.float32)
    np.testing.assert_allclose(levels(x * 0.8, SR), levels(x * 0.2, SR), atol=1e-5)


def test_quiet_noise_stays_small():
    rng = np.random.default_rng(0)
    noise = (rng.standard_normal(SR) * FLOOR / 10).astype(np.float32)
    assert levels(noise, SR).max() < 0.2
