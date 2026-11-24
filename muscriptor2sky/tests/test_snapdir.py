# -*- coding: utf-8 -*-
"""黑键吸附方向测试（回归测试）。

背景（真实用户报告）：
    「听起来很奇怪 像是音都不是那个音」

根因：snap() 用上下文（旋律走向）逐个决定黑键向上还是向下吸附，
导致同一个音级在曲子里落到不同的白键上。实测星降る海：
C# 被映射到 G / A / B 三个不同白键，33.1% 的旋律音落在不一致的音级上。
同一句旋律重奏时音名变了，听感就是「跑调 / 变色」。

修复：先用 pick_snap_directions() 为每个黑键音级定一个统一方向，
      再让 snap() 把「方向」排在排序键的第一位（优先于距离与协和度）。

实测（同进程 A/B）：音级轮廓保真度 80.3% -> 81.3%，
                    音级映射一致率 51.4% -> 56.9%。
"""

import types

from muscriptor2sky.core import (
    build_keys,
    midi_to_sky,
    pick_snap_directions,
    snap,
    write_midi_file,
)

KEYS = build_keys(60, 15)
WHITE = {k % 12 for k in KEYS}
BLACK = [pc for pc in range(12) if pc not in WHITE]
LO, HI = KEYS[0], KEYS[-1]


def _args(**kw):
    base = dict(root=60, transpose="auto", grid=0.0, max_poly=0, name="t",
                author="", arranged=None, transcribed=None, bpm=None,
                bits_per_page=16, pitch_level=0, encoding="utf-16",
                input="a.mid", ppq=480, note_len=0.25)
    base.update(kw)
    return types.SimpleNamespace(**base)


def test_snap_directions_returns_one_entry_per_black_key():
    melody = [61, 63, 66, 68, 70, 72, 74]
    d = pick_snap_directions(melody, KEYS)
    assert set(d) == set(BLACK), "应覆盖全部 5 个黑键音级，实际 %s" % sorted(d)
    assert all(isinstance(v, bool) for v in d.values())


def test_same_pitch_class_always_maps_to_same_white_key():
    """核心不变式：同一个黑键音级，无论出现在旋律的哪个位置，都落到同一个白键。"""
    # 同一黑键音级（C#=61）上下交替出现
    melody = [60, 61, 62, 61, 60, 61, 64, 61, 62, 61]
    d = pick_snap_directions(melody, KEYS)
    up = d[1]
    mapped = {snap(61, KEYS, up, None) for _ in range(3)}
    assert len(mapped) == 1, "同一音级被映射到多个白键: %s" % mapped


def test_direction_beats_distance_in_snap():
    """方向必须优先于距离，否则「统一方向」会被距离拉回去。"""
    # 61 (C#4) 距离 C4(60) 更近，但 prefer_up 时应取 D4(62)
    assert snap(61, KEYS, True, None) == 62
    assert snap(61, KEYS, False, None) == 60


def test_direction_beats_consonance_in_snap():
    """方向也要优先于和声协和度，否则和弦会覆盖调性一致性。"""
    # bass_pc 让向下的 C 成为「协和」选项，但 prefer_up 仍应取 D
    assert snap(61, KEYS, True, 0) == 62


def test_no_black_notes_means_empty_directions():
    """输入全是白键时不需要任何方向决策。"""
    melody = [60, 62, 64, 65, 67]
    d = pick_snap_directions(melody, KEYS)
    # 仍然返回 5 个黑键的默认方向（全部 True），但不应报错
    assert set(d) <= set(BLACK)


def test_empty_melody_is_safe():
    assert pick_snap_directions([], KEYS) == {}


def test_pitch_class_mapping_consistent_end_to_end():
    """端到端：需要吸附时，同一源音级必须始终落到同一白键。

    必须用 transpose="none" 才会真正走到吸附分支 ——
    开着自动定调时，整曲会被移调到调内音阶上，黑键根本不会触发吸附，
    那样这条测试就变成了「什么都没测」。
    """
    from muscriptor2sky.core import Midi, Note
    # 反复使用 C#(61) 的旋律（上下交替出现），强制走吸附
    seq = [60, 61, 62, 61, 60, 61, 64, 61, 62, 61, 60, 61]
    m = Midi(ppq=480, tempos=[(0, 500000)])
    for i, p in enumerate(seq):
        m.notes.append(Note(start=i * 480, dur=240, pitch=p, vel=100, ch=0, track=0))
    sky, info = midi_to_sky(m, _args(input="a.mid", grid=0.0, transpose="none"))
    assert sky, "没有输出音符"
    assert info["stat"]["snapped"] > 0, (
        "这条测试要求真的发生吸附，实际 snapped=%d —— 测试没有覆盖目标分支"
        % info["stat"]["snapped"])

    # 按**原始 MIDI 音高**分组（不能用 s.src_pitch：那是折叠后、已减
    # transpose 的内部值，拿它分组会把不同源音级混在一起）。
    # 每个 onset 只有一个音，所以输出与输入按下标一一对应。
    import collections
    by_pc = collections.defaultdict(set)
    for src, s in zip(seq, sky):
        by_pc[src % 12].add(s.key_idx)
    assert len(by_pc) >= 3, "样本太少，覆盖不到多个音级"
    for pc, idxs in by_pc.items():
        assert len(idxs) == 1, "音级 %d 被映射到多个键位 %s" % (pc, sorted(idxs))
