# -*- coding: utf-8 -*-
"""转换主流程与 SkyStudio 格式兼容性测试。"""

import json
import types

import pytest

from muscriptor2sky.core import (
    build_keys,
    midi_to_sky,
    read_midi,
    skyr_parse,
    write_sky,
    write_midi_file,
)


def _args(**kw):
    """构造一个和 CLI 参数同形的对象。"""
    base = dict(
        root=60,
        transpose="auto",
        grid=0.25,
        max_poly=0,
        name="test",
        author="",
        arranged=None,
        transcribed=None,
        bpm=None,
        bits_per_page=16,
        pitch_level=0,
        encoding="utf-16",
        input="a.mid",
    )
    base.update(kw)
    return types.SimpleNamespace(**base)


def _write(path, notes, ppq=480):
    events = []
    for tick, pitch, dur in notes:
        events.append((tick, 0x90, pitch, 100))
        events.append((tick + dur, 0x80, pitch, 64))
    write_midi_file(str(path), events, ppq)


def test_all_output_keys_within_15(tmp_path):
    """任何输入音符都必须落进 0..14，不能越界。"""
    mid = tmp_path / "in.mid"
    # 故意给超低音、超高音、黑键
    _write(mid, [(0, 24, 480), (480, 108, 480), (960, 61, 480),
                 (1440, 66, 480), (1920, 70, 480)])
    m = read_midi(str(mid))
    notes, info = midi_to_sky(m, _args())
    assert notes
    for n in notes:
        assert 0 <= n.key_idx <= 14


def test_chromatic_notes_get_snapped(tmp_path):
    """黑键应该被吸附到一个合法键位，而不是丢弃。

    必须用 transpose="none"：开着自动移调时，整首歌会被移到 C 大调，
    黑键根本不会走到吸附分支（那反而是更好的结果）。
    """
    mid = tmp_path / "c.mid"
    _write(mid, [(0, 61, 480), (480, 63, 480)])   # C#, D#
    m = read_midi(str(mid))
    notes, info = midi_to_sky(m, _args(transpose="none"))
    assert len(notes) == 2
    assert info["stat"]["snapped"] >= 1
    for n in notes:
        assert build_keys()[n.key_idx] % 12 in {0, 2, 4, 5, 7, 9, 11}


def test_auto_transpose_avoids_snapping(tmp_path):
    """开着自动移调时，黑键应被整体移调成白键，吸附次数越少越好。"""
    mid = tmp_path / "ct.mid"
    # 全曲 #F 大调音阶片段，自动移调后应尽量落白键
    _write(mid, [(i * 480, p, 480) for i, p in enumerate([66, 68, 70, 71, 73, 75, 78])])
    m = read_midi(str(mid))
    _, info = midi_to_sky(m, _args())
    # 移调后落白键（精确+八度折叠）应占多数
    exact = info["stat"]["exact"] + info["stat"]["octave"]
    assert exact >= info["stat"]["snapped"]


def test_max_poly_limits_simultaneous_notes(tmp_path):
    """--max-poly 必须真的限制同一时间戳的音数。"""
    mid = tmp_path / "p.mid"
    _write(mid, [(0, p, 480) for p in (60, 62, 64, 65, 67, 69)])
    m = read_midi(str(mid))
    notes, info = midi_to_sky(m, _args(max_poly=3))
    by_time = {}
    for n in notes:
        by_time.setdefault(n.time_ms, []).append(n)
    assert max(len(v) for v in by_time.values()) <= 3


def test_same_key_same_time_is_merged(tmp_path):
    """两个不同音高映射到同一个键且时刻相同时，只保留一个。

    确定性构造：B3(59) 低于音域下限，被八度折叠成 B4(71)；
    而 B4(71) 本来就在音域内。两者都落到键位 6（7 的索引），同刻 → 必须合并。
    """
    mid = tmp_path / "m.mid"
    _write(mid, [(0, 59, 480), (0, 71, 480)])
    m = read_midi(str(mid))
    notes, info = midi_to_sky(m, _args(transpose="none"))
    assert len(notes) == 1
    assert notes[0].key_idx == 6
    assert build_keys()[6] == 71
    assert info["stat"]["merged"] >= 1


def test_write_and_parse_sky_roundtrip(tmp_path):
    """写出的 txt 必须能被按 SkyStudio 规范实现的解析器原样读回。"""
    mid = tmp_path / "rt.mid"
    _write(mid, [(0, 60, 480), (480, 64, 480), (960, 67, 480)])
    m = read_midi(str(mid))
    notes, info = midi_to_sky(m, _args())
    out = tmp_path / "rt.txt"
    write_sky(str(out), notes, _args(), info)

    v = skyr_parse(str(out))
    assert v["encoding"] == "UTF-16LE(BOM)"
    assert v["noteCount"] == len(notes)
    assert all(0 <= k <= 14 for k in v["keysUsed"])


def test_output_is_utf16le_with_bom(tmp_path):
    """编码必须是 UTF-16LE + BOM，否则播放器读不了中文。"""
    mid = tmp_path / "e.mid"
    _write(mid, [(0, 60, 480)])
    m = read_midi(str(mid))
    notes, info = midi_to_sky(m, _args())
    out = tmp_path / "e.txt"
    write_sky(str(out), notes, _args(), info)
    raw = out.read_bytes()
    assert raw[:2] == b"\xff\xfe"
    payload = json.loads(raw[2:].decode("utf-16-le"))
    assert isinstance(payload, list)
    assert "songNotes" in payload[0]
