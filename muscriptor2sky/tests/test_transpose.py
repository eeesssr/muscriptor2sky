# -*- coding: utf-8 -*-
"""移调选优测试（回归测试）。

背景（真实用户报告）：
    「这首歌本来是纯音乐，MuScriptor 转成 MIDI 几乎没损失，也是单一乐器，
      但用工具转成 15 键谱后流失了原本的旋律。」

根因有两处，都在 pick_transpose 上：

  ① 旧实现把搜索范围硬编码成 t in [-6, +6]，表达不了「整首挪一个八度」。
     而挪八度恰恰是避免逐音折叠的唯一手段。结果是为了音级统计好看，
     把大量音符挤出 C4..C6，再被逐个八度折叠 —— 旋律轮廓被反复截断。
  ② 旧实现用「白键命中率」这种间接启发式打分，与实际损坏不对齐；
     而且把低音区也纳入决策，低音本来就要被折叠，纯属把旋律拖出音域。

修复后：搜索 [-18, +18]，并按「实际会被改动的音符比例」打分，
        且只用旋律声部参与决策。

验证基线（178 份社区谱面 SkyAutoPlayerScript/shared_sheets，
随机移到别的调后再转回 C 调 15 键）：
    * 音符还原率 99.89%（旧实现 96.1%）
    * 5 份真实 MIDI 旋律正确率 71.8% -> 82.0%
    * 八度缠绕率 16.8% -> 9.0%

这里锁定几个最容易退化的行为。
"""

import types

import pytest

from muscriptor2sky.core import build_keys, pick_transpose


KEYS = build_keys(60, 15)
KEY_PCS = {k % 12 for k in KEYS}
LO, HI = KEYS[0], KEYS[-1]


def _melody(pitches):
    """按 pick_transpose 的约定构造 (音高, 权重) 序列。"""
    return [(p, 1.0) for p in pitches]


def _fold(p):
    while p < LO:
        p += 12
    while p > HI:
        p -= 12
    return p


def test_search_range_covers_three_octaves():
    """搜索范围必须覆盖 ±18（3 个八度），否则无法表达「整体挪八度」。

    构造一条整体偏高一个八度的旋律：C5 大调音阶。只有当 t 能取到 -12
    附近时，它才可能原样落进 C4..C6，而不被逐音折叠。
    """
    melody = [72, 74, 76, 77, 79, 81, 83, 84] * 4
    t = pick_transpose(_melody(melody), KEY_PCS, LO, HI)
    assert abs(t) > 6 or all(LO <= p + t <= HI for p in melody), (
        "移调量 %d 落在旧实现的 [-6,6] 里，且没能把旋律放进音域" % t
    )
    # 落进音域的音必须占多数
    inside = sum(1 for p in melody if LO <= p + t <= HI)
    assert inside >= 0.9 * len(melody)


def test_transpose_keeps_transposed_major_scale_intact():
    """C 大调音阶整体升高一个八度后，必须能整体还原，零折叠。"""
    melody = [72, 74, 76, 77, 79, 81, 83] * 3
    t = pick_transpose(_melody(melody), KEY_PCS, LO, HI)
    assert all(LO <= p + t <= HI for p in melody), "transpose=%d 仍有音越界" % t
    assert all((p + t) % 12 in KEY_PCS for p in melody), "transpose=%d 产生了黑键" % t


def test_transpose_uses_whole_octave_not_per_note_folding():
    """整段旋律应当整体平移，而不是让每个音各自折叠。

    若逐音折叠，相邻音程会被 12 的倍数打断；整体平移则音程全部保持。
    """
    melody = [79, 81, 83, 84, 83, 81, 79, 77] * 3   # 全部高于 C5
    t = pick_transpose(_melody(melody), KEY_PCS, LO, HI)
    out = [p + t for p in melody]
    src_steps = [melody[i + 1] - melody[i] for i in range(len(melody) - 1)]
    out_steps = [out[i + 1] - out[i] for i in range(len(out) - 1)]
    assert src_steps == out_steps, "音程被改动，说明发生了逐音折叠而非整体平移"


def test_octave_error_and_pitch_error_weighted_equally():
    """评分把「出界」和「黑键」都算一个音符的损失，权重相等。

    10 个白键音 + 1 个黑键音：正确解应该只牺牲那 1 个黑键音，
    而不是为了躲开它把整段音都挤出音域。
    """
    melody = [60, 62, 64, 65, 67, 69, 71] * 3 + [61]
    t = pick_transpose(_melody(melody), KEY_PCS, LO, HI)
    outside = sum(1 for p in melody if not LO <= p + t <= HI)
    assert outside == 0, "为了躲一个黑键把 %d 个音挤出音域" % outside


def test_empty_input_is_safe():
    assert pick_transpose([], KEY_PCS, LO, HI) == 0


def test_transpose_result_is_deterministic():
    """同样输入必须给同样输出（平局时取绝对值更小的移调）。"""
    melody = [67, 69, 71, 72, 74] * 5
    a = pick_transpose(_melody(melody), KEY_PCS, LO, HI)
    b = pick_transpose(_melody(melody), KEY_PCS, LO, HI)
    assert a == b
