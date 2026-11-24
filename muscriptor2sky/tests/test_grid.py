# -*- coding: utf-8 -*-
"""SkyStudio 时间网格兼容性测试（核心回归测试）。

背景（真实踩过的坑，两个症状）：
  A. SkyStudio 报「格式不受支持」——SkyR 却能正常播放
  B. 能导入但「音不对、速度也不对」

根因都在 SkyStudio 的时间模型上。它打开谱面后这样算播放延时：

    unit      = gcd(所有相邻 time 的间隔)          # buildTimingModel()
    sleepUnit = duration / unit
    实际延时   = sleepUnit * (60000 / bpm)

想让实际延时等于 duration（速度正确），必须：

    gcd(times) == 60000 / bpm            ← 铁律

由此推出：
  * gcd 退化成 1ms（bpm 除不尽时量化抖动）→ SkyStudio 无法建网格 → 报错
  * gcd != 60000/bpm（差 2 倍、4 倍…）→ 播放速度整体快慢若干倍 → 速度不对

skyR 之类按毫秒差直接计时的播放器不关心这个关系，所以「skyR 正常」。
"""

import json
import math
import types
from functools import reduce

import pytest

from muscriptor2sky.core import (
    beat_unit_ms,
    grid_compatible,
    grid_safe_bpm,
    midi_to_sky,
    read_midi,
    write_midi_file,
    write_sky,
)


def _args(**kw):
    base = dict(
        root=60, transpose="auto", grid=0.25, max_poly=0, name="t", author="",
        arranged=None, transcribed=None, bpm=None, bits_per_page=16,
        pitch_level=0, encoding="utf-16", input="a.mid", ppq=480, note_len=0.25,
    )
    base.update(kw)
    return types.SimpleNamespace(**base)


def _write(path, notes, ppq=480, tempo_us=500000):
    events = []
    for tick, pitch, dur in notes:
        events.append((tick, 0x90, pitch, 100))
        events.append((tick + dur, 0x80, pitch, 64))
    write_midi_file(str(path), events, ppq, tempo_us=tempo_us)


def _gcd_gaps(times):
    ts = sorted(set(times))
    if len(ts) < 2:
        return 0
    return reduce(math.gcd, [b - a for a, b in zip(ts, ts[1:])])


def _playback_ratio(times, bpm):
    """按 SkyStudio 公式算「实际延时 / 原始时长」，1.0 表示速度正确。"""
    ts = sorted(set(times))
    raw = ts[-1] - ts[0] if len(ts) > 1 else 0
    if raw <= 0:
        return 1.0
    g = _gcd_gaps(times)
    if g <= 0:
        return 0.0
    # 逐段模拟更长，这里只用总跨度近似
    unit = g
    return (raw / unit) * (60000.0 / bpm) / raw


def test_grid_safe_bpm_prefers_60000_divisors():
    """grid_safe_bpm 应把 bpm 归一到能整除 60000 的值。"""
    for bpm in (117, 137, 233, 301):
        out = grid_safe_bpm(bpm)
        cell = 60000.0 / out
        assert abs(cell - round(cell)) < 1e-6, "bpm=%s -> %s, cell=%s 非整数" % (
            bpm, out, cell)


def test_grid_safe_bpm_keeps_good_values():
    """本来就是因数的 bpm 不应被改动。"""
    for bpm in (120, 200, 300, 400):
        assert grid_safe_bpm(bpm) == float(bpm)


def test_beat_unit_ms_is_integer():
    assert beat_unit_ms(120) == 500
    assert beat_unit_ms(300) == 200


def test_gcd_equals_cell_at_awkward_bpm(tmp_path):
    """核心回归：bpm=117（一拍 512.82ms）时不能让 gcd 退化。"""
    mid = tmp_path / "a.mid"
    tempo_us = int(round(60000000.0 / 117))
    notes = [(i * 240, 60 + (i % 7), 200) for i in range(16)]
    _write(mid, notes, ppq=480, tempo_us=tempo_us)

    m = read_midi(str(mid))
    out, info = midi_to_sky(m, _args())
    assert out

    times = [n.time_ms for n in out]
    g = _gcd_gaps(times)
    cell = 60000.0 / info["bpm"]
    assert g > 1, "gcd 退化成 1ms，SkyStudio 会报错"
    assert abs(cell - g) < 1.0, "gcd=%d != cell=%.1f，SkyStudio 速度会歪" % (g, cell)


def test_playback_speed_matches_original(tmp_path):
    """回归：速度必须与原曲一致（不能快慢若干倍）。"""
    mid = tmp_path / "b.mid"
    # bpm=137 一拍 437.96ms，最容易被处理坏
    tempo_us = int(round(60000000.0 / 137))
    notes = [(i * 219, 60 + (i % 5), 180) for i in range(20)]
    _write(mid, notes, ppq=480, tempo_us=tempo_us)

    m = read_midi(str(mid))
    out, info = midi_to_sky(m, _args())
    times = sorted(set(n.time_ms for n in out))
    bpm = info["bpm"]
    g = _gcd_gaps(times)
    cell = 60000.0 / bpm
    assert abs(cell - g) < 1.0, "gcd=%d != cell=%.1f -> 速度会歪" % (g, cell)
    ratio = _playback_ratio(times, bpm)
    assert abs(ratio - 1.0) < 0.02, "播放速度偏差 %.1f%%" % ((ratio - 1) * 100)


def test_written_file_passes_grid_check(tmp_path):
    """写出的文件本身要能通过 SkyStudio 网格判定。"""
    mid = tmp_path / "c.mid"
    tempo_us = int(round(60000000.0 / 233))
    notes = [(i * 120, 62 + (i % 6), 100) for i in range(24)]
    _write(mid, notes, ppq=480, tempo_us=tempo_us)

    m = read_midi(str(mid))
    out, info = midi_to_sky(m, _args())
    txt = tmp_path / "c.txt"
    write_sky(str(txt), out, _args(), info)

    song = json.loads(txt.read_bytes()[2:].decode("utf-16-le"))[0]
    times = [n["time"] for n in song["songNotes"]]
    assert grid_compatible(times, song["bpm"]), "写出的文件未通过网格检查"


def test_info_reports_grid_status(tmp_path):
    mid = tmp_path / "d.mid"
    _write(mid, [(0, 60, 480), (480, 64, 480)], tempo_us=500000)
    m = read_midi(str(mid))
    _, info = midi_to_sky(m, _args())
    assert "grid_ok" in info
    assert "unit_ms" in info
    assert "bpm" in info
