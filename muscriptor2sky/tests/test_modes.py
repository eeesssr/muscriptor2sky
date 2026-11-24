# -*- coding: utf-8 -*-
"""输出模式测试：C 调默认 / 定调 / 虚音。"""

import types

from muscriptor2sky.core import (
    Midi,
    Note,
    VIRTUAL_NOTE_TABLE,
    build_keys,
    midi_to_sky,
    virtual_pair_for,
)


def _args(**kw):
    base = dict(root=60, transpose="auto", grid=0.25, max_poly=0, name="t",
                author="", arranged=None, transcribed=None, bpm=None,
                bits_per_page=16, pitch_level=0, encoding="utf-16",
                input="a.mid", ppq=480, note_len=0.25, virtual_notes=False)
    base.update(kw)
    return types.SimpleNamespace(**base)


def _midi(pitches):
    m = Midi(ppq=480, tempos=[(0, 500000)])
    for i, p in enumerate(pitches):
        m.notes.append(Note(start=i * 480, dur=240, pitch=p, vel=100, ch=0, track=0))
    return m


def test_virtual_table_covers_four_of_five_black_keys():
    """15 键缺 5 个黑键，虚音方案能覆盖 4 个；G# 无可用方案。"""
    assert virtual_pair_for(1) is not None, "C# 应有方案"
    assert virtual_pair_for(3) is not None, "D# 应有方案"
    assert virtual_pair_for(6) is not None, "F# 应有方案"
    assert virtual_pair_for(8) is None, "G# 不应有方案（最好 25.9 音分，超阈值）"
    assert virtual_pair_for(10) is not None, "A# 应有方案"


def test_virtual_table_errors_within_threshold():
    """所有可用方案的误差必须 < 20 音分（人耳辨别阈值）。"""
    for pc, entry in VIRTUAL_NOTE_TABLE.items():
        if entry is None:
            continue
        a, b, err, desc = entry
        assert err < 20.0, "音级 %d 误差 %.1f 分超过阈值" % (pc, err)
        assert 0 <= a <= 14 and 0 <= b <= 14, "键索引越界: %d/%d" % (a, b)
        assert a != b, "两个键不能相同"


def test_default_mode_writes_pitch_level_zero():
    m = _midi([60, 62, 64, 65, 67])
    sky, info = midi_to_sky(m, _args())
    assert info["pitch_level"] == 0


def test_pitch_level_is_reported():
    m = _midi([60, 62, 64, 65, 67])
    sky, info = midi_to_sky(m, _args(pitch_level=2))
    assert info["pitch_level"] == 2


def test_pitch_level_does_not_change_notes():
    """定调只写进头部字段，不应改变谱面内容。"""
    m = _midi([60, 62, 64, 65, 67, 69, 71])
    a, _ = midi_to_sky(m, _args(pitch_level=0))
    b, _ = midi_to_sky(m, _args(pitch_level=5))
    assert [(s.time_ms, s.key_idx) for s in a] == [(s.time_ms, s.key_idx) for s in b]


def test_virtual_mode_adds_notes():
    """虚音模式应为黑键音补上额外的键。"""
    # 含黑键的旋律
    m = _midi([61, 63, 66, 68, 70, 61, 63])
    a, info_a = midi_to_sky(m, _args(virtual_notes=False))
    b, info_b = midi_to_sky(m, _args(virtual_notes=True))
    assert len(b) >= len(a), "虚音模式不应减少音符"


def test_virtual_mode_keeps_all_keys_in_range():
    m = _midi([61, 63, 66, 68, 70] * 3)
    sky, info = midi_to_sky(m, _args(virtual_notes=True))
    assert all(0 <= s.key_idx <= 14 for s in sky), "虚音模式产生了越界键"


def test_playability_metric_present():
    m = _midi([60, 62, 64, 65, 67])
    sky, info = midi_to_sky(m, _args())
    assert "playability" in info
    assert 0.0 <= info["playability"] <= 100.0


def test_playability_full_for_all_white_notes():
    """全是白键时应 100% 可弹。"""
    m = _midi([60, 62, 64, 65, 67, 69, 71])
    sky, info = midi_to_sky(m, _args(transpose="none"))
    assert info["playability"] == 100.0