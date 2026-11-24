# -*- coding: utf-8 -*-
"""输出模式测试：自动定调 / 强制 C 调 / 手动定调 / 虚音。"""

import types

from muscriptor2sky.core import (
    KEY_NAMES,
    Midi,
    Note,
    VIRTUAL_NOTE_TABLE,
    build_keys,
    detect_key,
    key_ranking,
    major_scale,
    midi_to_sky,
    transpose_for_key,
    virtual_pair_for,
)


def _args(**kw):
    base = dict(root=60, transpose="auto", grid=0.25, max_poly=0, name="t",
                author="", arranged=None, transcribed=None, bpm=None,
                bits_per_page=16, key="auto", encoding="utf-16",
                input="a.mid", ppq=480, note_len=0.25, virtual_notes=False)
    base.update(kw)
    return types.SimpleNamespace(**base)


def _midi(pitches):
    m = Midi(ppq=480, tempos=[(0, 500000)])
    for i, p in enumerate(pitches):
        m.notes.append(Note(start=i * 480, dur=240, pitch=p, vel=100, ch=0, track=0))
    return m


# ---------------------------------------------------------------- 虚音表

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


# ---------------------------------------------------------------- 定调识别

def test_detect_key_recognizes_c_major_scale():
    w = [(p, 1.0) for p in [60, 62, 64, 65, 67, 69, 71] * 4]
    d = detect_key(w)
    assert d["tonic"] == 0
    assert d["name"] == "C"


def test_detect_key_recognizes_g_major():
    """G 大调音阶（含 F#）应被识别为 G（pitchLevel=7）。"""
    g = [67 + s for s in [0, 2, 4, 5, 7, 9, 11]]
    d = detect_key([(p, 1.0) for p in g * 4])
    assert d["tonic"] == 7, "识别成 %s，期望 G" % d["name"]


def test_detect_key_handles_all_twelve_tonics():
    """12 个大调音阶逐个喂进去，必须全部识别正确。"""
    for k in range(12):
        scale = sorted((k + s) % 12 for s in [0, 2, 4, 5, 7, 9, 11])
        # 铺两个八度，权重均匀
        pitches = [p for o in (60, 72) for p in (pc + o for pc in scale)]
        d = detect_key([(p, 1.0) for p in pitches] * 3)
        assert d["tonic"] == k, "K=%d 被识别成 %s" % (k, d["name"])


def test_detect_key_is_transposition_equivariant():
    """整段 +n 半音，识别结果也必须 +n。"""
    base = [60, 62, 64, 65, 67, 69, 71] * 4
    for n in (1, 5, 7, 11):
        a = detect_key([(p, 1.0) for p in base])
        b = detect_key([(p + n, 1.0) for p in base])
        assert b["tonic"] == (a["tonic"] + n) % 12


def test_detect_key_empty_is_safe():
    d = detect_key([])
    assert d["tonic"] == 0
    assert d["confidence"] == "empty"


def test_key_ranking_covers_all_twelve():
    rows = key_ranking([(p, 1.0) for p in [60, 62, 64]])
    assert len(rows) == 12
    assert {r["tonic"] for r in rows} == set(range(12))
    hits = [r["hit"] for r in rows]
    assert hits == sorted(hits, reverse=True), "排序应为命中率降序"


def test_major_scale_shape():
    assert major_scale(0) == {0, 2, 4, 5, 7, 9, 11}
    assert major_scale(7) == {7, 9, 11, 0, 2, 4, 6}


# ---------------------------------------------------------------- 移调约束

def test_transpose_respects_key_constraint():
    """移调量必须满足 t ≡ -K (mod 12)，否则谱面写不成 C 大调形状。"""
    w = [(p, 1.0) for p in [60, 62, 64, 65, 67]]
    for k in range(12):
        t = transpose_for_key(w, k, 60, 84)
        assert (t + k) % 12 == 0, "K=%d 给出 t=%d，(t+K)%%12=%d" % (k, t, (t + k) % 12)


def test_transpose_keeps_melody_in_range():
    """在满足调性约束的前提下，八度要选得让旋律落进音域。"""
    w = [(p, 1.0) for p in [84, 86, 88, 89, 91]]     # 很高的一段
    t = transpose_for_key(w, 0, 60, 84)
    inside = sum(1 for p in (84, 86, 88, 89, 91) if 60 <= p + t <= 84)
    assert inside >= 3, "t=%d 没把旋律带进音域" % t
    assert (t + 0) % 12 == 0


def test_transpose_empty_is_zero_residue():
    assert transpose_for_key([], 7, 60, 84) % 12 == (-7) % 12


# ---------------------------------------------------------------- 端到端

def test_auto_key_preserves_original_pitch_class():
    """自动定调的核心承诺：K 大调音阶上的音，转换后仍在 K 大调音阶上。"""
    g_scale = [67, 69, 71, 72, 74, 76, 78]          # G 大调（含 F#）
    m = _midi(g_scale * 4)
    sky, info = midi_to_sky(m, _args())
    assert info["key"]["tonic"] == 7
    assert info["pitch_level"] == 7
    # 输出全部落在 15 键白键上，且没有吸附
    assert info["stat"]["snapped"] == 0, "G 大调曲子不该产生吸附"
    assert all(0 <= s.key_idx <= 14 for s in sky)


def test_c_mode_forces_pitch_level_zero():
    m = _midi([60, 62, 64, 65, 67])
    sky, info = midi_to_sky(m, _args(key="c"))
    assert info["pitch_level"] == 0
    assert info["key"]["mode"] == "c"


def test_manual_key_overrides_detection():
    """手动指定是备用选择：即使检测器判成别的，也必须听用户的。"""
    m = _midi([60, 62, 64, 65, 67])          # 明显是 C 大调
    _, auto_info = midi_to_sky(m, _args(key="auto"))
    assert auto_info["pitch_level"] == 0
    _, man_info = midi_to_sky(m, _args(key="5"))    # 硬说成 F 调
    assert man_info["pitch_level"] == 5
    assert man_info["key"]["mode"] == "manual"
    assert man_info["transpose"] % 12 == (-5) % 12


def test_manual_key_zero_is_not_truthy_confused():
    """--key 0 必须真的走「手动 C 调」，不能被当成空值回落 auto。"""
    m = _midi([67, 69, 71, 72, 74, 76, 78] * 3)     # G 大调，auto 会判 7
    _, info = midi_to_sky(m, _args(key="0"))
    assert info["pitch_level"] == 0
    assert info["key"]["mode"] == "manual"


def test_transpose_none_forces_c():
    m = _midi([61, 63, 66])           # 黑键
    _, info = midi_to_sky(m, _args(transpose="none"))
    assert info["pitch_level"] == 0
    assert info["transpose"] == 0


def test_default_mode_is_auto():
    """默认必须是自动识别，不是强制 C 调 —— 这是本次改动的核心。"""
    m = _midi([67, 69, 71, 72, 74, 76, 78] * 3)
    _, info = midi_to_sky(m, _args())
    assert info["key"]["auto"] is True
    assert info["key"]["mode"] == "auto"


# ---------------------------------------------------------------- 平局裁决

def test_pentatonic_tie_is_resolved_by_cadence():
    """五声音阶会让多个大调的覆盖率完全并列，必须靠终止式裁决。

    {C D E G A} 同时是 C 大调和 G 大调的子集 —— 覆盖率数值相等。
    末音落在 C 时，应判定为 C 大调。
    """
    penta_c = [60, 62, 64, 67, 69]        # C D E G A
    ending_c = penta_c * 3 + [60]         # 末音 C
    d = detect_key([(p, 1.0) for p in ending_c])
    assert d["tonic"] == 0, "末音是 C 却判成 %s" % d["name"]
    assert d["ambiguous"] is True, "应标记为并列解"
    assert "G" in d["tied"]


def test_pentatonic_tie_ending_on_g_resolves_to_g():
    """同样的音级集合，末音换成 G 就该判成 G 大调。"""
    penta_c = [60, 62, 64, 67, 69]
    ending_g = penta_c * 3 + [67]
    d = detect_key([(p, 1.0) for p in ending_g])
    assert d["tonic"] == 7, "末音是 G 却判成 %s" % d["name"]


def test_unambiguous_key_has_no_tied_set():
    """七个音级全用上时只有一个调能完全覆盖，不应标成并列。"""
    d = detect_key([(p, 1.0) for p in [60, 62, 64, 65, 67, 69, 71] * 4])
    assert d["ambiguous"] is False
    assert d["tied"] == ["C"]


def test_detect_key_is_deterministic():
    """并列时必须有确定的裁决结果，不能依赖 dict/set 顺序。"""
    seq = [60, 62, 64, 67, 69, 62, 64, 67, 60] * 3
    a = detect_key([(p, 1.0) for p in seq])
    b = detect_key([(p, 1.0) for p in seq])
    assert a["tonic"] == b["tonic"]
    assert a["tied"] == b["tied"]


def test_transpose_none_overrides_key_and_is_flagged():
    """--transpose none 与 --key N 互斥：必须按不移调处理，并标记冲突。

    否则 pitchLevel 会写成 N，演奏音高比原曲高出 N 个半音。
    """
    m = _midi([67, 69, 71, 72, 74, 76, 78] * 3)
    _, info = midi_to_sky(m, _args(key="7", transpose="none"))
    assert info["transpose"] == 0
    assert info["pitch_level"] == 0, "不移调就不能声明非 C 调"
    assert info["key"]["mode"] == "none"


def test_key_names_table():
    assert len(KEY_NAMES) == 12
    assert KEY_NAMES[0] == "C" and KEY_NAMES[7] == "G"


# ---------------------------------------------------------------- 其它指标

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


def test_virtual_mode_adds_notes():
    """虚音模式应为黑键音补上额外的键。"""
    m = _midi([61, 63, 66, 68, 70, 61, 63])
    a, info_a = midi_to_sky(m, _args(virtual_notes=False, key="c", transpose="none"))
    b, info_b = midi_to_sky(m, _args(virtual_notes=True, key="c", transpose="none"))
    assert len(b) >= len(a), "虚音模式不应减少音符"


def test_virtual_mode_keeps_all_keys_in_range():
    m = _midi([61, 63, 66, 68, 70] * 3)
    sky, info = midi_to_sky(m, _args(virtual_notes=True, transpose="none"))
    assert all(0 <= s.key_idx <= 14 for s in sky), "虚音模式产生了越界键"
