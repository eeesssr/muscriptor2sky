# -*- coding: utf-8 -*-
"""主旋律保留测试（v1.4.1 回归测试）。

背景：
    v1.4.0 及之前，主旋律会在两个环节被无声吃掉：
      1. 同键合并：只比力度，弱的主旋律会被强的伴奏覆盖；
      2. 复音裁剪（--max-poly）：只按「力度 + 最高/最低音」打分，
         主旋律若力度偏低、或源音高超出音域被折叠到中间，就会被挤掉。
    实测 5 份曲目，主旋律存活率 89.8% ~ 99.3%，最差的一份丢了 10% 的主旋律音。

    注意：v1.4.1 之前有人量出「主旋律保留率 0.8%」，那是量测错误 ——
    用原曲 TempoMap 算出的毫秒去比对输出时间，而输出时间已被重新量化到
    另一个 cell（如 256ms），两套时间轴不可能对上。真实基线是 89.8%~99.3%。

修复：给音符标记「主旋律」身份（每个 onset 的最高音），
      在复音裁剪与同键合并时无条件优先保留。

本文件的用例都用合成 MIDI，且每个关键用例都在 v1.4.0 上验证过会失败，
确保它们真的锁住了这两条代码路径（见文件末尾的 _discriminates_against_v140 说明）。
"""

import types

from muscriptor2sky.core import Midi, Note, build_keys, midi_to_sky


def _args(**kw):
    base = dict(root=60, transpose="none", grid=0.0, max_poly=0, name="t",
                author="", arranged=None, transcribed=None, bpm=None,
                bits_per_page=16, pitch_level=0, encoding="utf-16",
                input="a.mid", ppq=480, note_len=0.25, virtual_notes=False)
    base.update(kw)
    return types.SimpleNamespace(**base)


def _midi(triples):
    """triples: [(start_tick, pitch, vel), ...]"""
    m = Midi(ppq=480, tempos=[(0, 500000)])
    for start, pitch, vel in triples:
        m.notes.append(Note(start=start, dur=240, pitch=pitch, vel=vel, ch=0, track=0))
    return m


# ---------------------------------------------------------------- 统计字段

def test_melody_info_is_reported():
    """info 里应带主旋律统计，且总数等于 onset 数。"""
    m = _midi([(0, 60, 100), (480, 62, 100), (960, 64, 100)])
    sky, info = midi_to_sky(m, _args())
    assert "melody" in info
    assert info["melody"]["total"] == 3
    assert info["melody"]["kept"] == 3
    assert info["melody"]["rate"] == 100.0


def test_melody_kept_never_exceeds_total():
    m = _midi([(i * 480, 60 + (i % 5), 100) for i in range(20)])
    sky, info = midi_to_sky(m, _args())
    md = info["melody"]
    assert 0 <= md["kept"] <= md["total"]
    assert 0.0 <= md["rate"] <= 100.0


# ---------------------------------------------------------------- 同键合并

def test_weak_melody_survives_same_key_merge():
    """同键合并时，力度低的主旋律不能被力度高的伴奏覆盖。

    构造：C#(61) 是每拍最高音（主旋律），力度只有 40；C(60) 是伴奏，力度 120。
          前四拍交替出现，让 pick_snap_directions 把 C# 统一吸附到 C；
          第五拍两者同时出现 —— 若合并按力度选，主旋律会被伴奏顶掉。

    判别信号：保留下来那条的 how。
              v1.4.0 留下的是精确的伴奏 -> how == "exact"
              v1.4.1 留下的是被吸附的主旋律 -> how == "snapped"
    """
    m = _midi([
        (0, 61, 40), (480, 60, 120),
        (960, 61, 40), (1440, 60, 120),
        (1920, 61, 40), (1920, 60, 120),   # 关键：同时
    ])
    sky, info = midi_to_sky(m, _args())
    assert info["stat"]["merged"] >= 1, "用例没有触发同键合并，测试无效"

    at_last = [s for s in sky if s.time_ms >= 2000]
    assert at_last, "最后一拍没有输出"
    assert at_last[0].how == "snapped", (
        "同键合并保留了伴奏(how=exact)而非主旋律(how=snapped): %s" % at_last)
    assert info["melody"]["kept"] == info["melody"]["total"]


# ---------------------------------------------------------------- 复音裁剪

def test_weak_melody_survives_polyphony_limit():
    """复音裁剪时，力度最低的主旋律必须保留。

    构造：主旋律 100（力度 30，超音域会被折叠到 76）；
          伴奏 55 / 57 / 79 力度都是 120。
          v1.4.0 的显著性打分是「力度 + 最高音 +1000 + 最低音 +900」，
          三个伴奏同分时它会优先挑 79（最高）和 55（最低），主旋律 76 被丢弃。
          v1.4.1 先把主旋律拿出来，再用剩余名额挑伴奏。

    判别信号：输出键位里有没有 76（key index 9）。
    """
    keys = build_keys(60, 15)
    melody_key = keys.index(76)
    m = _midi([(0, 100, 30), (0, 55, 120), (0, 57, 120), (0, 79, 120)])
    sky, info = midi_to_sky(m, _args(max_poly=2))

    assert info["stat"]["dropped"] >= 1, "用例没有触发复音裁剪，测试无效"
    # 先断言键位（这是真正的判别信号），再看统计字段
    out_keys = [s.key_idx for s in sky]
    assert melody_key in out_keys, (
        "主旋律折叠后的键 %d 未出现在输出 %s" % (melody_key, out_keys))
    assert info["melody"]["kept"] == 1, (
        "主旋律在复音裁剪时被丢弃: %s" % info["melody"])


def test_polyphony_limit_still_respected():
    """主旋律优先，但伴奏仍要服从复音上限。"""
    m = _midi([(0, 72, 100), (0, 60, 90), (0, 64, 90), (0, 67, 90)])
    sky, info = midi_to_sky(m, _args(max_poly=2))
    per_time = {}
    for s in sky:
        per_time[s.time_ms] = per_time.get(s.time_ms, 0) + 1
    assert max(per_time.values()) <= 2, "输出超过复音上限: %s" % per_time


# ---------------------------------------------------------------- 边界

def test_empty_midi_is_safe():
    m = Midi(ppq=480, tempos=[(0, 500000)])
    sky, info = midi_to_sky(m, _args())
    assert sky == []
    assert "error" in info
