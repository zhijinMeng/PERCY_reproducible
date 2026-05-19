# -*- coding: utf-8 -*-
"""轻量稳态噪声抑制：高通 + 谱减（无需 scipy）。

在 LISTEN/冷却期用 VAD 判为非语音的帧更新噪声谱；
送 Whisper 前对整段 utterance 做谱减。
"""
from __future__ import division, print_function

import struct

import numpy as np


def _pcm16_to_float(pcm_bytes):
    if not pcm_bytes:
        return np.array([], dtype=np.float32)
    x = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
    return x / 32768.0


def _float_to_pcm16(x):
    x = np.clip(x, -1.0, 1.0)
    return (x * 32767.0).astype(np.int16).tobytes()


class HighpassFilter(object):
    """一阶高通，去掉低频稳态嗡声。"""

    def __init__(self, sample_rate, cutoff_hz=80.0):
        rc = 1.0 / (2.0 * np.pi * float(cutoff_hz))
        dt = 1.0 / float(sample_rate)
        self._alpha = rc / (rc + dt)
        self._y_prev = 0.0
        self._x_prev = 0.0

    def process_bytes(self, pcm_bytes):
        if not pcm_bytes:
            return pcm_bytes
        x = _pcm16_to_float(pcm_bytes)
        y = np.empty_like(x)
        a = self._alpha
        yp, xp = self._y_prev, self._x_prev
        for i in range(len(x)):
            yp = a * (yp + x[i] - xp)
            y[i] = yp
            xp = x[i]
        self._y_prev, self._x_prev = float(y[-1]), float(x[-1])
        return _float_to_pcm16(y)


class StationaryNoiseReducer(object):
    def __init__(
        self,
        sample_rate=16000,
        n_fft=512,
        noise_ema=0.92,
        prop_decrease=0.85,
        highpass_hz=80.0,
        min_noise_frames=8,
    ):
        self.sample_rate = int(sample_rate)
        self.n_fft = int(n_fft)
        self.hop = self.n_fft // 2
        self.noise_ema = float(noise_ema)
        self.prop_decrease = float(prop_decrease)
        self.min_noise_frames = int(min_noise_frames)
        self._hp = HighpassFilter(self.sample_rate, cutoff_hz=highpass_hz)
        self._noise_mag = None
        self._noise_frame_count = 0
        self._window = np.hanning(self.n_fft).astype(np.float32)

    @property
    def has_noise_profile(self):
        return self._noise_mag is not None and self._noise_frame_count >= self.min_noise_frames

    def highpass(self, pcm_bytes):
        return self._hp.process_bytes(pcm_bytes)

    def learn_noise_frame(self, pcm_bytes):
        """非语音帧：更新稳态噪声谱（调用方应已高通）。"""
        mag = self._frame_magnitude(pcm_bytes)
        if mag is None:
            return
        if self._noise_mag is None:
            self._noise_mag = mag.copy()
        else:
            a = self.noise_ema
            self._noise_mag = a * self._noise_mag + (1.0 - a) * mag
        self._noise_frame_count += 1

    def reduce_utterance(self, pcm_bytes):
        """整段语音：高通 +（若有噪声谱）谱减。"""
        pcm_bytes = self.highpass(pcm_bytes)
        if not self.has_noise_profile:
            return pcm_bytes
        x = _pcm16_to_float(pcm_bytes)
        if len(x) < self.n_fft:
            return pcm_bytes
        out = np.zeros_like(x)
        w = self._window
        noise = self._noise_mag
        prop = self.prop_decrease
        n = len(x)
        win_sum = np.zeros(n, dtype=np.float32)
        for start in range(0, n - self.n_fft + 1, self.hop):
            seg = x[start : start + self.n_fft] * w
            spec = np.fft.rfft(seg)
            mag = np.abs(spec)
            phase = np.angle(spec)
            clean_mag = np.maximum(mag - prop * noise[: len(mag)], 0.05 * mag)
            clean = clean_mag * np.exp(1j * phase)
            chunk = np.fft.irfft(clean).astype(np.float32) * w
            out[start : start + self.n_fft] += chunk
            win_sum[start : start + self.n_fft] += w * w
        mask = win_sum > 1e-8
        out[mask] /= win_sum[mask]
        return _float_to_pcm16(out)

    def _frame_magnitude(self, pcm_bytes):
        x = _pcm16_to_float(pcm_bytes)
        if len(x) < self.n_fft:
            return None
        seg = x[: self.n_fft] * self._window
        return np.abs(np.fft.rfft(seg)).astype(np.float32)

    def set_noise_magnitude(self, noise_mag):
        """从离线标定的噪声谱加载（见 percy/extract_noise_profile.py）。"""
        if noise_mag is None:
            self._noise_mag = None
            self._noise_frame_count = 0
            return
        mag = np.asarray(noise_mag, dtype=np.float32).ravel()
        self._noise_mag = mag
        self._noise_frame_count = max(self.min_noise_frames, 1)

    @staticmethod
    def load_profile_json(path):
        import json

        with open(path, "r") as f:
            data = json.load(f)
        return np.asarray(data["noise_mag"], dtype=np.float32), data


def estimate_noise_magnitude(samples, sample_rate=16000, n_fft=512, highpass_hz=80.0):
    """从 float32 [-1,1] 或 int16 样本估计平均噪声幅度谱。"""
    if samples is None or len(samples) < n_fft:
        return None
    if samples.dtype == np.int16:
        x = samples.astype(np.float32) / 32768.0
    else:
        x = np.asarray(samples, dtype=np.float32)
    hp = HighpassFilter(sample_rate, cutoff_hz=highpass_hz)
    pcm = _float_to_pcm16(x)
    pcm = hp.process_bytes(pcm)
    x = _pcm16_to_float(pcm)
    w = np.hanning(n_fft).astype(np.float32)
    hop = n_fft // 2
    acc = None
    count = 0
    for start in range(0, len(x) - n_fft + 1, hop):
        seg = x[start : start + n_fft] * w
        mag = np.abs(np.fft.rfft(seg)).astype(np.float32)
        if acc is None:
            acc = mag.copy()
        else:
            acc += mag
        count += 1
    if count == 0:
        return None
    return acc / float(count)


def save_noise_profile(path, noise_mag, meta=None):
    import json

    payload = {
        "noise_mag": np.asarray(noise_mag, dtype=np.float32).ravel().tolist(),
        "meta": meta or {},
    }
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)
