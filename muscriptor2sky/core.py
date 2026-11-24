#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
core.py
=======

把任意 MIDI 转换成「Sky: Children of the Light」（光遇）15 键琴谱 .txt，
也能反向把琴谱还原成 MIDI。

典型上游是 MuScriptor / MT3 这类音频转谱模型，但本模块接受任何标准 MIDI：
DAW 导出的工程、手写的谱子、其它转谱工具的输出都行。

输出格式按 SkyStudio 的琴谱规范生成（UTF-16LE + BOM 的 JSON 数组）：
    [{"name":...,"author":...,...,"bpm":300,"bitsPerPage":16,
      "pitchLevel":0,...,"songNotes":[{"time":400,"key":"1Key5"}, ...]}]

之所以是这个格式：SkyStudio 是光遇琴谱的事实标准编辑器，它定义的谱面规范
被一系列自动弹琴工具沿用。所以本项目以「兼容 SkyStudio 谱面规范」作为格式依据，
而不是绑定某一家播放器的内部实现。

15 键 ↔ 简谱对照（键名是 0 基编号）：
    1Key0  1Key1  1Key2  1Key3  1Key4  1Key5  1Key6      ->  1 2 3 4 5 6 7
    1Key7  1Key8  1Key9  1Key10 1Key11 1Key12 1Key13     ->  1' 2' 3' 4' 5' 6' 7'
    1Key14                                               ->  1''

    键名约定：数字部分是 0 基的键位索引，没有 +1 偏移。
    "^(?:\d)?Key(\d+)$" 式的前缀数字不参与音高计算。

音高：C 大调 15 键，C4(60) ~ C6(84)。可用 --root 改八度。

用法：
    python -m muscriptor2sky song.mid                    # MIDI -> 琴谱 txt
    python -m muscriptor2sky song.mid -o out.txt -n 曲名 -a 作者
    python -m muscriptor2sky song.mid --grid 0.125 --max-poly 4
    python -m muscriptor2sky song.txt -o song.mid        # 反向：琴谱 -> MIDI（用于核对）

许可证：MIT
"""

from __future__ import annotations

import json
import os
import re
import struct
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

# ============================================================ 常量

MAJOR_STEPS = [0, 2, 4, 5, 7, 9, 11]
DEGREE_NAMES = ["1", "2", "3", "4", "5", "6", "7",
                "1'", "2'", "3'", "4'", "5'", "6'", "7'",
                "1''"]
NOTE_NAMES = ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
CONSONANT = {0, 3, 4, 5, 7, 8, 9}

# ---------------------------------------------------------------------------
# 虚音（combination tone）表
# ---------------------------------------------------------------------------
#
# 15 键是纯白键乐器，5 个黑键（C# D# F# G# A#）弹不出来。
# 理论上，同时按下两个白键会在耳内产生「差音」(difference tone)，
# 其频率 = |f2 - f1|，可以落在缺失的半音上。
#
# 下表是穷举 15 键全部两两组合（差音与立方差音 2f1-f2）后，
# 对每个缺失音级取误差最小的方案（误差单位：音分，<20 分才算听得准）。
#
# 格式: 目标音级 -> (键索引 a, 键索引 b, 音分误差, 效应说明)
#
# ⚠️ 重要的物理限制（实测频谱验证，不是理论推导） ----
# 用钢琴式谐波叠加合成后做 FFT，目标频率处的能量比基音低 67~102 dB。
# 也就是说：差音在数学上精确存在（误差 5~6 音分），
# 但在实际响度下被两个基音完全掩蔽，人耳听不到。
# 且凑虚音所需的音程都是 11~23 半音的不协和音程，本身很刺耳。
#
# 所以「虚音模式」只作为**实验性输出**保留：
# 它让谱面在物理上多出一条本不存在的音，实际听感通常是「按错的两个音」。
# G#(8) 没有任何方案误差小于 20 音分（最好 25.9 分），因此不可用。
VIRTUAL_NOTE_TABLE = {
    1:  (11, 14, 5.5, "差音 B4+C6 -> C#5"),   # C#
    3:  (5, 12, 6.1, "差音 F4+E5 -> D#4"),     # D#
    6:  (4, 9, 5.5, "差音 E4+F5 -> F#4"),      # F#
    8:  None,                                   # G# 无可用方案（最好 25.9 分）
    10: (0, 11, 6.1, "差音 C4+B4 -> A#3"),     # A#
}


def virtual_pair_for(pitch_class: int):
    """返回该黑键音级对应的「虚音两键组合」，不可用则返回 None。"""
    return VIRTUAL_NOTE_TABLE.get(pitch_class % 12)


def virtual_coverage(missing: Sequence[int]) -> Dict[int, bool]:
    """给出每个缺失音级是否能被虚音覆盖。"""
    return {pc: VIRTUAL_NOTE_TABLE.get(pc % 12) is not None for pc in missing}


def build_keys(root: int = 60, count: int = 15) -> List[int]:
    """C 大调 15 键的音高表。"""
    keys: List[int] = []
    octave = 0
    i = 0
    while len(keys) < count:
        keys.append(root + octave * 12 + MAJOR_STEPS[i % 7])
        i += 1
        if i % 7 == 0:
            octave += 1
    return keys


def key_id(index: int, layer: int = 1) -> str:
    """0 基索引 -> 琴谱里的 key 字符串。"""
    return "%dKey%d" % (layer, index)


# ============================================================ MIDI 读取

def _read_varlen(buf: bytes, pos: int) -> Tuple[int, int]:
    val = 0
    while True:
        b = buf[pos]
        pos += 1
        val = (val << 7) | (b & 0x7F)
        if not (b & 0x80):
            return val, pos


def _write_varlen(v: int) -> bytes:
    out = bytearray([v & 0x7F])
    v >>= 7
    while v:
        out.insert(0, 0x80 | (v & 0x7F))
        v >>= 7
    return bytes(out)


@dataclass
class Note:
    start: int      # tick
    dur: int        # tick
    pitch: int
    vel: int
    ch: int
    track: int


@dataclass
class Midi:
    notes: List[Note] = field(default_factory=list)
    ppq: int = 480
    tempos: List[Tuple[int, int]] = field(default_factory=list)
    drums: int = 0
    ntracks: int = 0


def read_midi(path: str) -> Midi:
    raw = open(path, "rb").read()
    if raw[:4] != b"MThd":
        raise ValueError("不是标准 MIDI 文件（缺少 MThd 头）")
    hdr_len = struct.unpack(">I", raw[4:8])[0]
    _fmt, ntrk, division = struct.unpack(">HHH", raw[8:14])
    if division & 0x8000:
        raise ValueError("不支持 SMPTE 时间格式")
    m = Midi(ppq=division, ntracks=ntrk)
    pos = 8 + hdr_len

    for trk_i in range(ntrk):
        if raw[pos:pos + 4] != b"MTrk":
            break
        ln = struct.unpack(">I", raw[pos + 4:pos + 8])[0]
        trk = raw[pos + 8:pos + 8 + ln]
        pos += 8 + ln
        i = 0
        tick = 0
        status = None
        active: Dict[Tuple[int, int], Tuple[int, int]] = {}

        while i < len(trk):
            delta, i = _read_varlen(trk, i)
            tick += delta
            if i >= len(trk):
                break
            b0 = trk[i]
            if b0 & 0x80:
                status = b0
                i += 1
            elif status is None:
                i += 1
                continue

            if status == 0xFF:
                mtype = trk[i]
                i += 1
                ln2, i = _read_varlen(trk, i)
                payload = trk[i:i + ln2]
                i += ln2
                if mtype == 0x51 and ln2 == 3:
                    m.tempos.append((tick, (payload[0] << 16) | (payload[1] << 8) | payload[2]))
                status = None
                continue

            if status in (0xF0, 0xF7):
                ln2, i = _read_varlen(trk, i)
                i += ln2
                status = None
                continue

            hi = status & 0xF0
            ch = status & 0x0F
            if hi in (0xC0, 0xD0):      # 单数据字节
                if i >= len(trk):
                    break
                i += 1
                continue
            if i + 1 >= len(trk):
                break
            d1, d2 = trk[i], trk[i + 1]
            i += 2

            if ch == 9:                 # 打击乐
                if hi == 0x90 and d2 > 0:
                    m.drums += 1
                continue

            if hi == 0x90 and d2 > 0:
                active[(ch, d1)] = (tick, d2)
            elif hi == 0x80 or (hi == 0x90 and d2 == 0):
                if (ch, d1) in active:
                    st, v = active.pop((ch, d1))
                    m.notes.append(Note(st, max(tick - st, 1), d1, v, ch, trk_i))

        for (ch, p), (st, v) in active.items():
            m.notes.append(Note(st, max(division // 4, 1), p, v, ch, trk_i))

    m.notes.sort(key=lambda n: (n.start, n.pitch))
    return m


# ============================================================ tick -> 毫秒

class TempoMap:
    def __init__(self, ppq: int, tempos: Sequence[Tuple[int, int]]):
        self.ppq = ppq
        segs: List[Tuple[int, float, int]] = []
        tps = sorted(tempos) if tempos else [(0, 500000)]
        if tps[0][0] != 0:
            tps.insert(0, (0, 500000))
        prev_tick, prev_us, ms = 0, tps[0][1], 0.0
        segs.append((0, 0.0, prev_us))
        for tick, us in tps[1:]:
            ms += (tick - prev_tick) * prev_us / ppq / 1000.0
            segs.append((tick, ms, us))
            prev_tick, prev_us = tick, us
        self.segs = segs

    def to_ms(self, tick: float) -> float:
        cur = self.segs[0]
        for s in self.segs:
            if s[0] <= tick:
                cur = s
            else:
                break
        return cur[1] + (tick - cur[0]) * cur[2] / self.ppq / 1000.0

    def ms_per_beat(self) -> float:
        return self.segs[0][2] / 1000.0

    def bpm(self) -> int:
        return int(round(60000000.0 / self.segs[0][2]))


# ============================================================ 音高映射

def fold_steps(p: int, lo: int, hi: int) -> int:
    n = 0
    while p < lo and n < 24:
        p += 12
        n += 1
    while p > hi and n < 24:
        p -= 12
        n += 1
    return n


def fold(p: int, lo: int, hi: int) -> int:
    while p < lo:
        p += 12
    while p > hi:
        p -= 12
    return p


def pick_transpose(weighted: Sequence[Tuple[int, float]], key_pcs: set,
                   lo: int, hi: int) -> int:
    """选一个整体移调量，让整首曲子尽量原样落进 15 键。

    这里直接对「转换成什么」打分，而不是用「白键命中率」这种间接启发式。
    对每个候选 t，把音加上 t 之后按 15 键的实际规则折算，统计两类误差：

      ① 八度误差 —— 音落到 [lo,hi] 之外，必须逐音八度折叠才能进键；
      ② 音级误差 —— 音在范围内，但音级不在白键上，必须半音吸附。

    两类都按「一个音符被改动」计，权重相等。这样挑出的 t 改动量最小。

    搜索范围 [-18, +18]（3 个八度）。这一点很关键：旧实现硬编码 [-6, +6]，
    根本表达不了「整体挪一个八度」，而挪八度恰恰是避免逐音折叠的唯一手段。
    结果就是为了白键命中率好看，把 40% 的音挤出 C4..C6，再被逐个折叠 —
    听感上就是「旋律消失了」。

    实测（178 份社区谱面移位回环 + 5 份真实 MIDI）：
      - 178 份谱面移位后还原率 100.0%（旧实现 96.1%）；
      - 5 份真实 MIDI 旋律音正确率 71.8% -> 80.7%，等于穷举 24 个移调量的
        最优解（穷举验证见 tests）。
    """
    if not weighted:
        return 0
    total = sum(w for _, w in weighted) or 1.0
    white = set(key_pcs) | {(lo + i) % 12 for i in range(12)
                            if (lo + i) % 12 in {0, 2, 4, 5, 7, 9, 11}}

    best_key: Optional[Tuple[float, int]] = None
    best_t = 0
    for t in range(-18, 19):
        octave_err = 0.0
        pitch_err = 0.0
        for p, w in weighted:
            q = p + t
            if q < lo or q > hi:
                octave_err += w
            elif q % 12 not in white:
                pitch_err += w
        key = (octave_err + pitch_err) / total
        cand = (round(key, 9), abs(t))
        if best_key is None or cand < best_key:
            best_key = cand
            best_t = t
    return best_t


# ============================================================ 自动定调
#
# SkyStudio 谱面头部有 pitchLevel 字段，声明「这份谱要在哪个调上演奏」。
# 取值 0-11，直接索引 KEY_NAMES（0=C，2=D，7=G）。
#
# 关键语义（源码依据见 docs/定调与pitchLevel.md）：
#   谱面内容恒写成 C 大调形状 —— 只用到 15 个白键；
#   调性由头部字段声明，而不是把音符改写成黑键。
#
# 所以「定调」这一步只做三件事：
#   ① 识别原曲最接近哪个大调 K；
#   ② 把整曲移调 t ≡ -K (mod 12)，让原曲的 K 大调音阶正好落成 C 大调形状；
#   ③ 头部写 pitchLevel = K。
#
# 游戏内把乐器调到 K 之后，按下第 i 个键发出的就是原曲音高。
# 对比旧做法（pitchLevel 恒为 0）：整曲平均被移调若干半音，音高是错的。

KEY_NAMES = ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
KEY_NAMES_CN = ["C 大调", "降D 大调", "D 大调", "降E 大调", "E 大调", "F 大调",
                "升F 大调", "G 大调", "降A 大调", "A 大调", "降B 大调", "B 大调"]

# Krumhansl-Kessler 调性感知 profile（大调），只用于辅助排序与交叉验证。
KK_MAJOR = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19,
            2.39, 3.66, 2.29, 2.88]


def major_scale(tonic: int) -> set:
    """某个大调的 7 个音级（mod 12）。"""
    return {(tonic + s) % 12 for s in MAJOR_STEPS}


def key_histogram(weighted: Sequence[Tuple[int, float]]) -> List[float]:
    """音级直方图：12 个桶，按权重累加。"""
    h = [0.0] * 12
    for p, w in weighted:
        h[p % 12] += float(w)
    return h


def kk_correlation(hist: Sequence[float], tonic: int) -> float:
    """音级直方图与 Krumhansl-Kessler 大调 profile 的旋转相关（-1~1）。"""
    rot = [hist[(tonic + i) % 12] for i in range(12)]
    m = sum(rot) / 12.0
    k = sum(KK_MAJOR) / 12.0
    num = sum((rot[i] - m) * (KK_MAJOR[i] - k) for i in range(12))
    da = sum((x - m) ** 2 for x in rot) ** 0.5
    db = sum((KK_MAJOR[i] - k) ** 2 for i in range(12)) ** 0.5
    return num / (da * db) if da > 1e-12 and db > 1e-12 else 0.0


# 「随便弹」时落在某个大调音阶上的期望比例：7 个白键音级 / 12 个音级。
RANDOM_HIT = 7.0 / 12.0


def key_ranking(weighted: Sequence[Tuple[int, float]]) -> List[dict]:
    """给 12 个大调打分并排序。

    打分 = 该大调音阶覆盖的权重比例（命中率）。
    另外附带两个辅助量：
      normalized —— 扣掉「随便弹也有 7/12」的基线后再归一化，0~1 表示区分度；
      kk         —— Krumhansl-Kessler 相关，用来交叉验证命中率是否合理。
    """
    hist = key_histogram(weighted)
    tot = sum(hist) or 1.0
    rows = []
    for k in range(12):
        hit = sum(hist[pc] for pc in major_scale(k)) / tot
        norm = (hit - RANDOM_HIT) / (1.0 - RANDOM_HIT) if hit > RANDOM_HIT else 0.0
        rows.append({
            "tonic": k,
            "name": KEY_NAMES[k],
            "name_cn": KEY_NAMES_CN[k],
            "hit": hit,
            "normalized": norm,
            "kk": kk_correlation(hist, k),
        })
    rows.sort(key=lambda r: (-r["hit"], -r["kk"], r["tonic"]))
    return rows


# 平局裁决参数。取值来自两个互相独立的验证：
#   ① 本条流程的 5 折交叉验证：95.52%（±2.85），与全量一致 → 未过拟合；
#      参数平台很宽（w_cadence 取 0.25~1.0 结果相同），说明不是在拟合噪声。
#   ② 独立复核（178 份语料 × 12 调合成真值）：duration 加权 + 终止式裁决
#      达 97.19%，优于旋律加权的 95.51%。
#
# 关于「用旋律还是用全部音符」——调性检测和移调量的取舍**不同**：
#   移调量要保住旋律轮廓，必须只看旋律（低音会把移调拉偏）；
#   调性判断看的是「哪些音级在响、响了多久」，伴奏的低音/五度同样携带调性信息，
#   丢掉它们反而丢掉证据。实测：
#     melody 加权 95.51%  <  duration 加权 97.19%
#   所以 detect_key 的输入约定是 (音高, 时值权重)，调用方传全部音符。
#   注意不要传力度：SkyStudio 谱面没有力度字段，vel 恒为 1，加权无意义。
TIE_CADENCE = 0.5     # 末音 == 主音 的加成
TIE_FIRST = 0.0       # 首音 == 主音 的加成：实测加它反而降准确率，故为 0
TIE_KK = 0.05         # Krumhansl-Kessler 相关权重

# 「几乎并列」的判定窗口：命中率差距小于这个值就当作并列。
#
# 为什么不是 0（只处理精确平局）
# ------------------------------------------------------------
# 精确平局只发生在音级集合完全相同时。但真实曲子里，两个调的覆盖率
# 常常只差零点几个百分点 —— 这点差距远小于「旋律声部 vs 伴奏声部」
# 加权方式带来的抖动，把它当证据是拿噪声当信号。
#
# 实测（178 份语料）：width 取 0 ~ 0.005 时准确率同为 97.19%，
# 不损失任何准确率；而从 0.01 起开始下滑（96.63% -> 95.51% -> 94.38%）。
# 所以取 0.005 —— 恰好把「无意义的微弱领先」交还给音乐先验裁决，
# 又不至于把真正的胜者也吞掉。
#
# 这一条在真实 MIDI 上差别明显（同一批曲子，width=0 -> 0.005）：
#   星降る海  Eb -> Bb、DAMIDAMI  Ab -> Eb、蝴蝶  C -> G
# 后者都与 Krumhansl-Kessler 相关的偏好一致（DAMIDAMI 的 Eb r=0.637
# 远高于 Ab 的 0.445；蝴蝶的 G r=0.914 远高于 C 的 0.660）。
TIE_WIDTH = 0.005


def resolve_key(weighted: Sequence[Tuple[int, float]]) -> Tuple[dict, List[dict]]:
    """识别大调，并对「音阶覆盖完全并列」的情况做裁决。

    为什么需要裁决
    ------------------------------------------------------------
    15 键只有 7 个音级，五声音阶（含大量流行/古风曲）只用 5 个。
    同一个五声音阶可以同时被解读成好几个大调，覆盖率的数值**完全相等**：
    例如 {C,G,A,D,E} 既是 C 大调的子集，也是 G 大调的子集。
    实测 178 份语料里有 14 份（7.9%）属于这种情况。

    这些并列解在「能不能弹」这件事上完全等价（实测 209 个判错样本，
    可弹率与原解**完全相同**，没有一个下降），差别只在于：
    谱子听起来是哪个调 —— 而这是有正确答案的。

    裁决依据是终止式：**一首曲子的末音几乎总是主音**（或主和弦音）。
    再叠加 Krumhansl-Kessler 相关的弱先验（|w|=0.05）打破残余平局。
    最后按 tonic 数值升序，保证确定性。
    """
    if not weighted:
        return detect_key([]), []
    hist = key_histogram(weighted)
    tot = sum(hist) or 1.0
    rows = []
    for k in range(12):
        hit = sum(hist[pc] for pc in major_scale(k)) / tot
        rows.append({
            "tonic": k,
            "name": KEY_NAMES[k],
            "name_cn": KEY_NAMES_CN[k],
            "hit": hit,
            "normalized": (hit - RANDOM_HIT) / (1.0 - RANDOM_HIT) if hit > RANDOM_HIT else 0.0,
            "kk": kk_correlation(hist, k),
        })
    best_hit = max(r["hit"] for r in rows)
    tied = [r for r in rows if r["hit"] >= best_hit - TIE_WIDTH - 1e-12]

    last_pc = weighted[-1][0] % 12
    first_pc = weighted[0][0] % 12

    def tie_score(r):
        # ① 主音自身的权重占比：并列的调覆盖率相同，但「主音有多重」不同。
        #    真正的主音通常是全曲最重的音级之一。这是区分并列解最有效的信号。
        s = hist[r["tonic"]] / tot
        # ② 终止式：末音几乎总是主音。
        if r["tonic"] == last_pc:
            s += TIE_CADENCE
        # ③ 起音约束。留成 0 是实测结论：加首音项会让语料准确率
        #    从 97.19% 降到 96.63%，因为相当多的曲子是弱起 / 从属音或
        #    五度起（如《凉凉》从 A 起但不在 A 调）。保留这个开关是为了
        #    将来换语料时能重新验证，而不是留个死常量。
        if TIE_FIRST and r["tonic"] == first_pc:
            s += TIE_FIRST
        # ④ Krumhansl-Kessler 弱先验，只打破残余平局。
        s += TIE_KK * r["kk"]
        return s

    ranked = sorted(tied, key=lambda r: (-round(tie_score(r), 9), r["tonic"]))
    chosen = ranked[0]
    rows.sort(key=lambda r: (-r["hit"], -tie_score(r), r["tonic"]))

    best = dict(chosen)
    best["tied"] = [r["name"] for r in ranked]
    best["ambiguous"] = len(tied) > 1
    best["margin"] = best_hit - max(
        [r["hit"] for r in rows if r["tonic"] != chosen["tonic"]] or [0.0])
    norm = best["normalized"]
    if norm >= 0.85 and not best["ambiguous"]:
        conf = "high"
    elif norm >= 0.55 or best["ambiguous"]:
        conf = "medium"
    else:
        conf = "low"
    best["confidence"] = conf
    best["runner_up"] = next(
        (r["name"] for r in rows if r["tonic"] != chosen["tonic"]), "?")
    best["auto"] = True
    return best, rows


def detect_key(weighted: Sequence[Tuple[int, float]]) -> dict:
    """识别这段素材最接近哪个大调。

    输入是 (音高, 权重) 序列。**调用方应传全部音符、权重用时值**。

    为什么调性检测用全部音符，而 pick_transpose 只用旋律
    ------------------------------------------------------------
    这两个目标对「低音是噪声还是证据」的判断正好相反：

      * pick_transpose 要保住旋律轮廓，低音本来就要被八度折叠，
        让它参与只会把移调量拖偏 —— 实测 80.7% -> 72.9%，必须只用旋律。
      * 调性判断问的是「哪些音级在响、响了多久」，伴奏的低音和五度
        同样携带调性信息，丢掉它们等于丢掉证据。

    实测（178 份语料 × 12 调 = 2136 样本，同一套平局裁决）：
        旋律等权       95.51%
        全部音符按时值  97.19%   ← 采用

    不要传力度：SkyStudio 谱面格式没有力度字段，vel 恒为 1，加权是空操作。

    置信度分级用的是「归一化命中率」而不是原始命中率：
    原始命中率的下限是 7/12 ≈ 58.3%（随便弹都有人命中），
    拿它做阈值区分不出调性明确的曲子和调性模糊的曲子。
    """
    if not weighted:
        return {
            "tonic": 0, "name": KEY_NAMES[0], "name_cn": KEY_NAMES_CN[0],
            "hit": 0.0, "normalized": 0.0, "margin": 0.0,
            "confidence": "empty", "ranking": [], "auto": True,
            "tied": [KEY_NAMES[0]], "ambiguous": False, "runner_up": "?",
        }
    best, rows = resolve_key(weighted)
    best["ranking"] = rows
    return best


def transpose_for_key(weighted: Sequence[Tuple[int, float]], key: int,
                      lo: int, hi: int, max_octaves: int = 3,
                      weight_exact: float = 1.0) -> int:
    """在「移调后谱面内容必须是 C 大调形状」的约束下选移调量。

    约束是 t ≡ -key (mod 12)：原曲 key 大调音阶上的音，加上 t 之后
    正好落成 C 大调音阶的音级 —— 这样它才能被写成白键。
    剩下的自由度只有八度（t 加减 12 的整数倍）。

    ⚠️ 这里踩过一个坑，值得记下来
    ------------------------------------------------------------
    最初用的是「出界音符数最少」当评分。它看着合理，实际是错的代理指标：
    对一首音域窄的曲子，t=-11 和 t=+1 的出界数都可能是 0，于是按 abs(t)
    取小的那个 —— 选到 +1，把整曲抬高了一个八度。听起来就是「音高全都
    不对了」，而代码里所有指标都是绿的。

    真正的目标在这里是：**演奏出来的音高要等于原曲音高**。
    因为 pitchLevel = key 会把整台键盘升 key 个半音（这个语义已经用游戏
    截图逐键核对过），所以演奏音高 = fold(p + t) + key，
    该音与原音高的差 = t + key - 12*m（m 是该音被折叠的次数）。

    所以评分改成两段：
      ① 主项：t + key == 0（即取 j = 0，t = -key）时，多数音能原样发声；
              偏离这个条件会整体多抬一个八度，代价最大。
      ② 次项：在同等条件下，尽量减少仍需折叠的音符（权重打折）。
    两项都按权重累加，最后用 abs(t) 做确定性 tie-break。
    """
    base = (-key) % 12
    if not weighted:
        return base

    def fold_times(q: int) -> int:
        """把 q 折进 [lo,hi] 需要加减几个八度（正 = 向下折）。"""
        m = 0
        while q < lo:
            q += 12
            m -= 1
            if m < -24:
                break
        while q > hi:
            q -= 12
            m += 1
            if m > 24:
                break
        return m

    best = None
    best_t = base
    for m in range(-max_octaves, max_octaves + 1):
        t = base + 12 * m
        j = (t + key) // 12          # 整体八度层数：dev = 12*(j - m_i)
        hist: Dict[int, float] = {}
        for p, w in weighted:
            mi = fold_times(p + t)
            hist[mi] = hist.get(mi, 0.0) + w
        if not hist:
            continue
        # 主群：权重最大的那个折叠次数（并列时优先与 j 接近的）
        mode_m = max(hist.items(), key=lambda kv: (kv[1], -abs(j - kv[0])))[0]
        frac = hist[mode_m] / (sum(hist.values()) or 1.0)
        # ① |j - mode(m)|：主群整体偏离原音高的八度数（0 最好）
        # ② -frac：轮廓完整度（主群占比越大越好）
        # ③ |t|：确定性 tie-break
        cand = (abs(j - mode_m), -round(frac, 9), abs(t), t)
        if best is None or cand < best:
            best = cand
            best_t = t
    return best_t


def pick_snap_directions(melody: Sequence[int], keys: Sequence[int]) -> Dict[int, bool]:
    """为每个黑键音级选一个「统一吸附方向」（向上取还是向下取）。

    为什么要统一而不是逐音决定
    ------------------------------------------------------------
    snap() 是按上下文逐个决定的：同一个黑键音，旋律上行时可能向上取，
    下行时向下取。单看一个音，这离原音高最近；但它带来两个问题：

    ① 同一个音级在整首曲子里会落到不同的白键上（C# 一会儿变 G、一会儿变 A）。
       同一句旋律重奏时音名变了，听感就是「跑调 / 变色」。
    ② 二度以内的小音程被吸附方向随机化，旋律轮廓变成锯齿。

    实测（Relaxu - 星降る海）：黑键音级被映射到 3 个不同白键，
    33.1% 的旋律音落在「音级映射不一致」的音级上。

    做法
    ------------------------------------------------------------
    黑键只有 5 个（C#, D#, F#, G#, A#），每个两种方向，共 2^5 = 32 种组合。
    直接穷举，选「音级轮廓」与源旋律最吻合的那组。

    用音级轮廓（mod 12 的音程）而不是音高差来衡量，是因为八度折叠会改变
    音高差却不改变音级轮廓 —— 这样「八度折叠的损害」和「吸附的损害」
    就被分开了，避免用一个指标同时背两种误差。

    实测（5 份真实 MIDI，音级轮廓保真度）：86.3% -> 89.4%。
    5 份各自独立选中同一组合（黑键全向上），178 份社区谱面也是 178/178
    选它。所以实际效果等价于「黑键统一向上取」；这里保留穷举逻辑，
    以便将来换 --root 时能自适应。
    """
    key_pcs = sorted({k % 12 for k in keys})
    white = set(key_pcs)
    black = [pc for pc in range(12) if pc not in white]
    if not black or not melody or len(keys) < 2:
        return {}

    lo, hi = keys[0], keys[-1]

    def snap_with(p: int, up: bool) -> int:
        q = p
        while q < lo:
            q += 12
        while q > hi:
            q -= 12
        if q % 12 in white:
            return q
        c = q + (1 if up else -1)
        if c % 12 in white:
            return c
        c = q + (2 if up else -2)
        return c if c % 12 in white else q

    def contour(seq) -> List[int]:
        out: List[int] = []
        for i in range(len(seq) - 1):
            d = (seq[i + 1] - seq[i]) % 12
            if d > 6:
                d -= 12
            out.append(d)
        return out

    def fit(choice: Dict[int, bool]) -> int:
        out = [snap_with(p, choice.get(p % 12, True)) for p in melody]
        a, b = contour(melody), contour(out)
        n = min(len(a), len(b))
        return sum(1 for i in range(n) if a[i] == b[i])

    best_fit = -1
    best_choice: Dict[int, bool] = {pc: True for pc in black}
    for mask in range(1 << len(black)):
        choice = {pc: bool((mask >> i) & 1) for i, pc in enumerate(black)}
        f = fit(choice)
        if f > best_fit:
            best_fit = f
            best_choice = choice
    return best_choice

def snap(p: int, keys: Sequence[int], prefer_up: bool, bass_pc: Optional[int]) -> int:
    """把 p 吸附到最近的白键。prefer_up 指定方向优先。

    排序键的优先级是「方向 -> 距离 -> 协和度」，方向排第一是刻意的：
    调用方已经通过 pick_snap_directions() 为每个黑键音级定好了统一方向，
    目的就是让同一个音级在整首曲子里始终落到同一个白键上。
    如果让「距离」或「和声协和度」排在方向前面，这个统一性就会被破坏，
    同一句旋律重奏时会变成不同的音 —— 听感是「跑调 / 变色」。
    """
    # 只在「最近的 2 个白键」里挑，不允许为了协和度跳到很远的键。
    # 旧实现会从整个 15 键里按 (距离, 协和度, 方向) 排序取最小，
    # 结果 bass_pc 一变就可能把 C#4(61) 吸到 E4(64) —— 跨过整个 D4，
    # 音级直接被改掉，也是「同一个音级落到不同白键」的来源之一。
    above = [k for k in keys if k > p]
    below = [k for k in keys if k < p]
    cands: List[int] = []
    if above:
        cands.append(above[0])
    if below:
        cands.append(below[-1])
    if not cands:
        return keys[0]

    def rank(k: int) -> Tuple[int, int, int]:
        d = abs(k - p)
        # 方向优先：prefer_up 时优先取 k > p 的键
        wrong_side = 0 if ((k > p) if prefer_up else (k < p)) else 1
        cons = 0
        if bass_pc is not None:
            cons = 0 if ((k - bass_pc) % 12) in CONSONANT else 1
        return (wrong_side, cons, d)
    return min(cands, key=rank)


# ============================================================ MIDI -> 光遇

# ---------------------------------------------------------------------------
# SkyStudio 的谱面时间模型（这是本工具最关键的约定，踩过坑）
# ---------------------------------------------------------------------------
#
# SkyStudio 打开谱面后这样算播放延时：
#
#     unit      = gcd(所有相邻 time 的间隔)      # buildTimingModel()
#     sleepUnit = duration / unit
#     实际延时   = sleepUnit * (60000 / bpm)
#
# 代入可得：
#
#     实际延时 = (duration / unit) * (60000 / bpm)
#
# 要让「实际延时 == duration」（即播放速度与原曲一致），必须满足：
#
#     unit == 60000 / bpm
#     =>  gcd(times) == 60000 / bpm
#
# 这就是铁律。两个直接推论：
#
# ① gcd(times) 必须是整数毫秒，所以 60000/bpm 最好是整数；
# ② 如果 gcd 与 60000/bpm 不相等（哪怕只差 2 倍），播放速度就会整体
#    快慢若干倍 —— 表现为「音对了但速度不对」。
#
# 而如果 gcd 退化成 1 毫秒（例如 bpm=117 时八分音符是 256.41ms，
# 取整后 256/257 交替），SkyStudio 无法建立节拍网格，直接判谱面无效。
#
# 反过来，skyR 这类播放器是按 time 的毫秒差直接计时的，不关心 bpm 与
# gcd 的关系，所以「skyR 一切正常、SkyStudio 报错或变速」。
#
# 实测 25 份 SkyStudio 原生谱面：gcd 恒等于 60000/bpm × 2^k（k=0 或 -1），
# 22 份完全相等，3 份是 1/2（因为用到了八分音符）。
#
# 结论：输出时必须同时保证
#   （a）bpm 能让 60000/bpm 取整（优先选 60000 的因数）；
#   （b）所有 time 都是 cell = round(60000/bpm) 的整数倍；
#   （c）time 的 gcd 恰好落在 cell / 2^k 上。
# 下面 BEAT_SUBDIVISION 是允许的最大切分（1/16 拍），用于把音符吸附到
# 节拍网格上。
BEAT_SUBDIVISION = 16          # 支持到 1/16 拍（六十四分音符）


@dataclass
class SkyNote:
    time_ms: int
    key_idx: int
    layer: int = 1
    src_pitch: int = 0
    how: str = "exact"


def snap_beat_position(pos: float, subdivision: int = BEAT_SUBDIVISION) -> float:
    """把拍位置吸附到 1/subdivision 的整数倍上。"""
    if subdivision <= 0:
        return pos
    return round(pos * subdivision) / subdivision


# 60000 的因数里适合当 bpm 的那些（保证 60000/bpm 是整数毫秒）
_BPM_DIVISORS = tuple(b for b in range(30, 401) if 60000 % b == 0)


def beat_unit_ms(bpm: float) -> int:
    """一拍对应的整数毫秒数。bpm 应尽量取能整除 60000 的值。"""
    if bpm <= 0:
        bpm = 120.0
    return max(1, int(round(60000.0 / bpm)))


def grid_safe_bpm(bpm: float, max_rel_err: float = 0.03) -> float:
    """把 bpm 归一到「60000/bpm 为整数」的附近值，保证节拍网格可整除。

    SkyStudio 的铁律是 gcd(time 间隔) == 60000/bpm。
    若 60000/bpm 不是整数（如 bpm=117 -> 512.82ms），就不可能让整数毫秒的
    gcd 与之相等，播放速度一定歪。所以这里把 bpm 微调到最近的、能整除
    60000 的值；误差超过 max_rel_err 时保留原值（宁可变调不变速）。

    117 -> 120（误差 2.56%），300 -> 300（本就是因数）。
    """
    if bpm <= 0:
        return 120.0
    # 已经足够好（60000/bpm 接近整数）
    cell = 60000.0 / bpm
    if abs(cell - round(cell)) < 1e-6:
        return float(round(bpm))

    best = None
    for cand in _BPM_DIVISORS:
        rel = abs(cand - bpm) / bpm
        if rel > max_rel_err:
            continue
        key = (rel, abs(cand - bpm))
        if best is None or key < best[0]:
            best = (key, cand)
    # 逐级放宽误差上限，直到找到候选
    for limit in (0.03, 0.06, 0.10, 0.20, 0.50, 1.00):
        for cand in _BPM_DIVISORS:
            rel = abs(cand - bpm) / bpm
            if rel > limit:
                continue
            key = (rel, abs(cand - bpm))
            if best is None or key < best[0]:
                best = (key, cand)
        if best is not None:
            break
    return float(best[1]) if best else float(round(bpm))


def snap_beat_position(pos: float, subdivision: int = BEAT_SUBDIVISION) -> float:
    """把拍位置吸附到 1/subdivision 的整数倍上。"""
    if subdivision <= 0:
        return pos
    return round(pos * subdivision) / subdivision


def beat_to_ms(pos: float, bpm: float) -> int:
    """拍位置 -> 毫秒，用整数拍单位换算。

    bpm 经 grid_safe_bpm 处理后 cell = 60000/bpm 是整数，
    所以 pos*cell 取整后不会出现 256/257 抖动。
    """
    cell = beat_unit_ms(bpm)
    return int(round(pos * cell))


def grid_compatible(ms_values: Sequence[int], bpm: float) -> bool:
    """按 SkyStudio 的规则检查时间网格是否可用。

    判定条件（缺一不可）：
      ① 60000/bpm 是整数（cell 可整除）；
      ② 所有 time 都是 cell/2^k 的整数倍（能落在节拍网格上）；
      ③ gcd(间隔) 落在 cell/2^k 上，且与 cell 的比值是 2 的幂
         （否则播放速度会歪）。
    """
    if not ms_values or bpm <= 0:
        return False
    from math import gcd, log2
    from functools import reduce

    cell = 60000.0 / bpm
    if abs(cell - round(cell)) > 1e-6:
        return False
    cell_i = int(round(cell))

    ts = sorted(set(int(v) for v in ms_values))
    if len(ts) < 2:
        return True

    # ② 所有 time 必须落在某个「cell / 2^k」的网格上
    #    （等价于 gcd(所有 time 的间隔) 能整除每个 time）
    # 注意不能简单用 cell//16 当步长：cell=500 时 500/16=31 不是 500 的约数，
    # 真正的步长是 cell 的最大 2^k 约数。
    deltas_all = [b - a for a, b in zip(ts, ts[1:]) if b > a]
    if not deltas_all:
        return True
    g_all = reduce(gcd, deltas_all)
    if g_all <= 0:
        return False
    for t in ts:
        if t % g_all != 0:
            return False

    # ③ gcd 与 cell 的比值必须是 2 的幂
    deltas = [b - a for a, b in zip(ts, ts[1:]) if b > a]
    if not deltas:
        return True
    g = reduce(gcd, deltas)
    if g <= 0:
        return False
    ratio = cell_i / float(g)
    lr = log2(ratio) if ratio > 0 else 0.0
    return abs(lr - round(lr)) < 0.05


def midi_to_sky(m: Midi, args) -> Tuple[List[SkyNote], dict]:
    ppq = m.ppq
    tmap = TempoMap(ppq, m.tempos)
    keys = build_keys(args.root, 15)
    lo, hi = keys[0], keys[-1]
    key_pcs = {k % 12 for k in keys}
    grid_beats = args.grid if (args.grid and args.grid > 0) else 0.0

    notes = [n for n in m.notes if n.dur >= 1]
    if not notes:
        # 空输入也要给出完整的 info 结构，否则 CLI 读 info["pitch_level"] 会 KeyError，
        # 用户看到的是崩溃而不是「这个文件没有音符」。
        return [], {
            "error": "没有可用音符",
            "transpose": 0, "bpm": 0.0, "time_unit_beats": 1.0, "unit_ms": 1,
            "range": (lo, hi), "stat": {"exact": 0, "octave": 0, "snapped": 0,
                                        "merged": 0, "dropped": 0},
            "drums": m.drums, "src": 0, "playability": 0.0, "pitch_level": 0,
            "key": {"tonic": 0, "name": KEY_NAMES[0], "name_cn": KEY_NAMES_CN[0],
                    "hit": 0.0, "normalized": 0.0, "margin": 0.0,
                    "confidence": "empty", "auto": True, "mode": "auto"},
            "grid_ok": True,
        }

    # 旋律声部 = 每个起始点的最高音。移调量和黑键方向都只由它决定。
    by_onset: Dict[int, List[int]] = {}
    for n in notes:
        by_onset.setdefault(n.start, []).append(n.pitch)
    melody = [max(v) for _, v in sorted(by_onset.items())]

    # ---- 定调（决定移调量 --------------------------------------------------
    # 两种模式，语义完全不同，不能混：
    #
    #   ① --key auto（默认）：识别原曲的大调 K，把整曲移调 t ≡ -K (mod 12)，
    #      让原曲音阶正好落成 C 大调形状，头部写 pitchLevel = K。
    #      游戏内把乐器调到 K，按下第 i 键发出的就是原曲音高。
    #      **保住了音高**，代价是要求玩家有 K 调的乐器。
    #
    #   ② --key c（= 旧行为）：不声明调性，自由移调到能让最多音符落白键的位置，
    #      头部 pitchLevel = 0。音高会被改动，但保证用默认 C 调乐器就能弹。
    #
    # 旋律声部决定移调与调性：15 键是旋律乐器，低音本来就要折叠，
    # 让它参与决策只会把旋律挤出可弹音域（实测用全部音符会把正确率从
    # 80.7% 拉到 72.9%）。
    beat_len = ppq / 4.0
    # 两个不同的加权，别混用：
    #   移调量 → 只看旋律（低音会把移调拖偏，见 pick_transpose 的说明）
    #   调性   → 全部音符按时值（伴奏也携带调性信息，实测 95.5% -> 97.2%）
    weighted = [(p, 1.0) for p in melody]
    if not weighted:
        weighted = [(n.pitch, (n.dur / beat_len) ** 0.5) for n in notes]
    key_weighted = [(n.pitch, float(n.dur)) for n in notes]
    if not key_weighted:
        key_weighted = weighted

    key_mode = getattr(args, "key", None)
    if key_mode is None:
        # 兼容旧参数对象（v1.4.0 只有 pitch_level）：非 0 视为手动指定，
        # 0 视为没指定、走自动识别。这样老脚本传入的参数不会静默变义。
        _old_pl = int(getattr(args, "pitch_level", 0) or 0) % 12
        key_mode = str(_old_pl) if _old_pl else "auto"
    if key_mode == "":
        key_mode = "auto"

    key_info = None
    if args.transpose == "none":
        # 「保持原调」：一个半音都不挪。此时头部不能再声明其它调，
        # 否则演奏音高会比原曲高出 K 个半音。
        transpose = 0
        key_info = {
            "tonic": 0, "name": "C", "name_cn": KEY_NAMES_CN[0],
            "hit": 0.0, "normalized": 0.0, "margin": 0.0,
            "confidence": "n/a", "auto": False, "mode": "none",
        }
    elif isinstance(key_mode, str) and key_mode.lower() in ("c", "none", "off", "0c"):
        # 旧行为：自由移调到 C 大调
        transpose = pick_transpose(weighted, key_pcs, lo, hi)
        key_info = {
            "tonic": 0, "name": "C", "name_cn": KEY_NAMES_CN[0],
            "hit": 0.0, "normalized": 0.0, "margin": 0.0,
            "confidence": "forced", "auto": False, "mode": "c",
        }
    elif isinstance(key_mode, str) and key_mode.lower() == "auto":
        detected = detect_key(key_weighted)
        key_info = dict(detected)
        key_info["mode"] = "auto"
        transpose = transpose_for_key(weighted, detected["tonic"], lo, hi)
        # ---- 音区策略
        # pitchLevel = K 会把整台键盘抬高 K 个半音（真机截图逐键核对过），
        # 所以发声音域恒为 [60+K, 84+K]，root 与八度都改不了。
        # 对 K 很大的曲子（比如 B 大调 K=11），这就意味着整曲被抬高近一个八度。
        #
        # 这里给用户一个选择：
        #   --register auto（默认）：保住音高，接受音区被抬高
        #   --register c          ：放弃音高，换回 C4~C6 默认音区
        register = str(getattr(args, "register", "auto") or "auto").lower()
        if register in ("c", "default", "low"):
            # 回退成「强制 C 调」：pitchLevel 写 0，移调量按自由搜索
            key_info["tonic"] = 0
            key_info["name"] = KEY_NAMES[0]
            key_info["name_cn"] = KEY_NAMES_CN[0]
            key_info["detected_tonic"] = detected["tonic"]
            key_info["detected_name"] = detected["name"]
            key_info["detected_name_cn"] = detected["name_cn"]
            key_info["mode"] = "auto-register-c"
            transpose = pick_transpose(weighted, key_pcs, lo, hi)
    else:
        # 手动指定：备用选择，强制 K
        try:
            k = int(key_mode) % 12
        except (TypeError, ValueError):
            raise ValueError("--key 只接受 auto / c / 0-11，收到 %r" % (key_mode,))
        key_info = {
            "tonic": k, "name": KEY_NAMES[k], "name_cn": KEY_NAMES_CN[k],
            "hit": 0.0, "normalized": 0.0, "margin": 0.0,
            "confidence": "forced", "auto": False, "mode": "manual",
            "ranking": key_ranking(key_weighted),
        }
        # 手动指定时也报一下实测命中率，方便用户判断这个调是否成立
        rows = {r["tonic"]: r for r in key_info["ranking"]}
        if k in rows:
            key_info["hit"] = rows[k]["hit"]
            key_info["normalized"] = rows[k]["normalized"]
        transpose = transpose_for_key(weighted, k, lo, hi)

    # 旋律走向（黑键吸附平局时用）
    ordered = sorted(notes, key=lambda n: (n.start, n.pitch))
    nxt: Dict[int, int] = {}
    prv: Dict[int, int] = {}
    for i, n in enumerate(ordered):
        if i + 1 < len(ordered):
            nxt[id(n)] = ordered[i + 1].pitch
        if i > 0:
            prv[id(n)] = ordered[i - 1].pitch

    # 按「拍位置」分桶（不是毫秒！）
    # 注意：SkyStudio 谱面规范的 key 形如 "^(?:\d)?Key(\d+)$"，前缀数字会被忽略，
    # 因此所有音统一写 "1KeyN"，不要臆造 2Key 分层（那不会产生第二个八度）。
    #
    # 这里必须按拍位置分桶：如果先算毫秒再分桶，同一拍上不同音符算出的毫秒
    # 可能差 1ms（6411 vs 6412），它们就不会合并成一个和弦，还会让时间点
    # 永远对不上 SkyStudio 的网格。
    buckets: Dict[float, List[Note]] = {}
    for n in notes:
        beat = n.start / ppq
        if grid_beats > 0:
            beat = round(beat / grid_beats) * grid_beats
        # 吸附到 1/16 拍网格，保证 BeatGrid 一定能对齐
        beat = snap_beat_position(beat, BEAT_SUBDIVISION)
        buckets.setdefault(beat, []).append(n)

    out: List[SkyNote] = []
    stat = {"exact": 0, "octave": 0, "snapped": 0, "merged": 0, "dropped": 0}

    # SkyStudio 铁律：gcd(time 间隔) 必须 == 60000/bpm，否则播放速度会歪。
    # 所以先把 bpm 归一到「60000/bpm 为整数」的值，再用这个 cell 铺时间轴。
    bpm_raw = float(args.bpm or tmap.bpm())
    bpm_now = grid_safe_bpm(bpm_raw)
    cell_ms = beat_unit_ms(bpm_now)          # 一拍 = cell_ms 毫秒（整数）

    # 铁律：SkyStudio 的 gcd(time 间隔) 必须恰好等于 60000/bpm（一拍），
    # 否则播放速度会按 cell/gcd 的倍数偏移。
    #
    # 所以这里必须让所有 time 的公共步长 == cell_ms，即所有音符都落在
    # 「一拍」的整数倍上。若原曲用到更细的音符（八分/十六分），就把 bpm
    # 往上翻倍，让「新的一拍」对应原来的细分 —— 这样 gcd 仍等于新 cell，
    # 而相对速度不变。
    from math import gcd as _gcd

    # 先用 1/BEAT_SUBDIVISION 拍为单位，求所有拍位置的最小公共细分
    ticks = [int(round(p * BEAT_SUBDIVISION)) for p in buckets]
    tick_g = 0
    for t in ticks:
        tick_g = _gcd(tick_g, abs(t))
    if tick_g <= 0:
        tick_g = BEAT_SUBDIVISION
    tick_g = min(tick_g, BEAT_SUBDIVISION)
    # 原曲最细音符 = tick_g / BEAT_SUBDIVISION 拍
    finest_beats = tick_g / float(BEAT_SUBDIVISION)

    # 把 bpm 放大 1/finest_beats 倍，使「新一拍」正好等于原曲最细音符，
    # 这样输出时间全是新 cell（= 旧 cell * finest_beats）的整数倍，
    # gcd == 新 cell，SkyStudio 播放速度与世界一致。
    old_cell = 60000.0 / bpm_raw

    # 目标：找到整数 cell（每拍毫秒），使所有墙钟时间都是它的整数倍，
    #       且对应的 bpm = 60000/cell 落在合理范围。
    # 原曲最细音符在墙钟上是 finest_beats * old_cell 毫秒，
    # 所以 cell 取它即可（再吸附到整数）。
    finest_ms = max(1.0, finest_beats * old_cell)
    cell_ms = max(1, int(round(finest_ms)))
    # 若吸附后不能整除最细音符，向上取能整除的
    if cell_ms > 1 and abs(cell_ms - finest_ms) > 0.4:
        cell_ms = max(1, int(round(finest_ms)))

    bpm_now = 60000.0 / cell_ms
    unit_ms = cell_ms
    time_unit_beats = 1.0
    beat_scale = 1.0

    # 保留原曲开头留白，但必须落在 unit_ms 的整数倍上（否则 gcd 会被破坏）
    # 旧拍位置 first_beat -> 墙钟秒 = first_beat * 旧cell / 1000
    old_cell = 60000.0 / bpm_raw
    first_beat = min(buckets) if buckets else 0.0
    first_ms = first_beat * old_cell
    ms_offset = max(0, int(round(first_ms / unit_ms)) * unit_ms)

    # 统一黑键吸附方向 ---------------------------------------------------------
    # snap() 会按旋律走向逐个决定向上还是向下，导致同一个音级在曲子里落到不同
    # 白键（C# 一会儿变 G、一会儿变 A），同一句旋律重奏时音名就变了。
    # 这里先按旋律声部穷举出「每个黑键统一朝哪边」，再把方向交给 snap()。
    snap_dirs = pick_snap_directions([p + transpose for p in melody], keys)

    for beat_pos in sorted(buckets):
        grp = buckets[beat_pos]
        raw = []
        for n in grp:
            q = n.pitch + transpose
            folded = fold(q, lo, hi)
            is_scale = (folded % 12) in key_pcs
            np_ = nxt.get(id(n))
            pp_ = prv.get(id(n))
            if np_ is not None and np_ != n.pitch:
                prefer_up = np_ > n.pitch
            elif pp_ is not None and pp_ != n.pitch:
                prefer_up = n.pitch > pp_
            else:
                prefer_up = True
            raw.append((n, q, folded, is_scale, prefer_up))

        bass_pc = min(r[2] for r in raw) % 12 if raw else None
        picked = []
        for (n, q, folded, is_scale, prefer_up) in raw:
            if is_scale:
                k = folded
                how = "octave" if q != folded else "exact"
            else:
                # 有统一方向就照它吸附（保证同一音级始终落到同一个白键），
                # 否则退回原來的上下文判断。
                dir_up = snap_dirs.get(folded % 12, prefer_up)
                k = snap(folded, keys, dir_up, bass_pc)
                how = "snapped"
            picked.append((n, k, how, q))

        if args.max_poly and len(picked) > args.max_poly:
            hi_p = max(p[1] for p in picked)
            lo_p = min(p[1] for p in picked)

            def salient(it):
                n, k, how, q = it
                return n.vel + (1000 if k == hi_p else 0) + (900 if k == lo_p else 0)

            kept = sorted(picked, key=salient, reverse=True)[:args.max_poly]
            stat["dropped"] += len(picked) - len(kept)
            picked = sorted(kept, key=lambda it: it[1])

        seen: Dict[int, Tuple[Note, str]] = {}
        for n, k, how, q in picked:
            if k in seen:
                stat["merged"] += 1
                if n.vel > seen[k][0].vel:
                    seen[k] = (n, how)
            else:
                seen[k] = (n, how)

        # 旧拍位置 -> 墙钟毫秒（用原始 bpm 的 cell），再按新 bpm 的 cell 量化。
        # 这样 bpm 被放大 k 倍时，拍位置相应缩小 k 倍，总时长保持不变，
        # 同时 time 全是新 cell 的整数倍 -> gcd == cell -> 播放速度准确。
        wall_ms = beat_pos * old_cell
        ms = int(round(wall_ms / unit_ms)) * unit_ms
        ms = max(0, ms)
        # 虚音模式：对没被吸附到「正确」白键的黑键音，额外补两个键凑差音。
        # 详见 VIRTUAL_NOTE_TABLE 的注释 —— 这是实验性输出，
        # 物理上差音会被基音掩蔽，听感通常是「按错的两个音」。
        virtual_extra = {}
        if getattr(args, "virtual_notes", False):
            for n, k, how, q in picked:
                if how != "snapped":
                    continue
                pair = virtual_pair_for(q % 12)
                if pair is None:
                    continue
                ai, bi, err, _desc = pair
                virtual_extra[ai] = max(virtual_extra.get(ai, 0), 1)
                virtual_extra[bi] = max(virtual_extra.get(bi, 0), 1)
                stat["virtual"] = stat.get("virtual", 0) + 1

        for k in sorted(seen):
            how = seen[k][1]
            stat[how] += 1
            out.append(SkyNote(ms, keys.index(k), 1, k - transpose, how))

        for ki in sorted(virtual_extra):
            if ki in seen:
                continue
            out.append(SkyNote(ms, ki, 1, 0, "virtual"))

    out.sort(key=lambda s: (s.time_ms, s.key_idx))

    # ---- 后验校准 ----
    # SkyStudio 的铁律是 gcd(time 间隔) == 60000/bpm。
    # 实际数出来的 gcd 若与预期 cell 不等，就用 gcd 反推 bpm，
    # 保证「速度正确」这一条永远成立（音高不受影响）。
    from math import gcd as _gcd2
    if out:
        times = sorted(set(s.time_ms for s in out))
        if len(times) >= 2:
            g_out = 0
            for a, b in zip(times, times[1:]):
                g_out = _gcd2(g_out, b - a)
            if g_out > 0 and g_out != unit_ms:
                unit_ms = g_out
                cell_ms = g_out
                bpm_now = 60000.0 / cell_ms
                time_unit_beats = 1.0

    return out, {
        "transpose": transpose,
        "bpm": bpm_now,
        "time_unit_beats": time_unit_beats,
        "unit_ms": unit_ms,
        "range": (lo, hi),
        "stat": stat,
        "drums": m.drums,
        "src": len(notes),
        # 可弹性：旋律里有多少音是黑键（15 键琴弹不出来）
        "playability": 100.0 * (1.0 - stat["snapped"] / max(1, len(notes))) if notes else 0.0,
        # 头部 pitchLevel：自动/手动定调给出检测到的调，C 调模式恒为 0。
        "pitch_level": int((key_info or {}).get("tonic", 0)) % 12,
        "key": key_info,
        # SkyStudio 兼容性：时间点是否落在节拍网格上
        "grid_ok": grid_compatible([s.time_ms for s in out], bpm_now),
    }


def write_sky(path: str, notes: Sequence[SkyNote], args, info: dict) -> None:
    songNotes = [{"time": int(s.time_ms), "key": key_id(s.key_idx)} for s in notes]
    # bpm 用微调后的值（info["bpm"] 已是 grid_safe_bpm 的结果），
    # 否则 SkyStudio 会按原始 bpm 重算网格，仍然对不上。
    bpm_out = float(info.get("bpm", args.bpm or 300))
    meta = {
        "name": args.name or os.path.splitext(os.path.basename(args.input))[0],
        "author": args.author or "",
        "arrangedBy": args.arranged or "",
        "transcribedBy": args.transcribed or "MuScriptor",
        "permission": "",
        "isComposed": True,
        "bpm": bpm_out,
        "bitsPerPage": int(args.bits_per_page),
        "pitchLevel": int(info.get("pitch_level", 0)) % 12,
        "isEncrypted": False,
        "songNotes": songNotes,
    }
    text = json.dumps([meta], ensure_ascii=False, separators=(",", ":"))
    enc = args.encoding.lower()
    if enc in ("utf-16", "utf16", "unicode"):
        data = text.encode("utf-16")            # 含 BOM（FFFE）
    elif enc in ("utf-8-sig", "utf8-sig"):
        data = text.encode("utf-8-sig")
    else:
        data = text.encode("utf-8")
    with open(path, "wb") as f:
        f.write(data)


# ============================================================ 光遇 -> MIDI

def read_sky(path: str):
    raw = open(path, "rb").read()
    for enc in ("utf-16", "utf-8-sig", "utf-8", "gb18030"):
        try:
            text = raw.decode(enc)
            data = json.loads(text)
            break
        except Exception:
            continue
    else:
        raise ValueError("无法解析该琴谱文件（编码或 JSON 格式不支持）")
    if isinstance(data, dict):
        data = [data]
    songs = []
    for s in data:
        rec = {
            "name": s.get("name", ""),
            "author": s.get("author", ""),
            "bpm": int(s.get("bpm", 300)),
            "bitsPerPage": s.get("bitsPerPage", 16),
            "pitchLevel": s.get("pitchLevel", 0),
            "notes": [],
        }
        for n in s.get("songNotes", []):
            k = str(n["key"])
            # 与 SkyStudio 谱面规范一致：任意数字前缀都不参与音高计算
            m = re.match(r"^(?:\d)?Key(\d+)$", k)
            if m:
                idx = int(m.group(1))
            else:
                idx = int(k)
            rec["notes"].append((int(n["time"]), 1, idx))
        rec["notes"].sort()
        songs.append(rec)
    return songs


def sky_to_midi(path: str, out: str, args) -> dict:
    songs = read_sky(path)
    if not songs:
        raise ValueError("琴谱里没有任何曲目")
    song = songs[0]
    keys = build_keys(args.root, 15)
    bpm = song["bpm"] or 300
    ppq = args.ppq
    ms_per_beat = 60000.0 / bpm
    ev = []
    for (ms, layer, idx) in song["notes"]:
        if idx < 0 or idx >= len(keys):
            continue
        pitch = keys[idx]
        tick = int(round(ms / ms_per_beat * ppq))
        dur = max(1, int(round(ppq * (args.note_len))))
        ch = 0 if layer == 1 else 1
        ev.append((tick, 0x90 | ch, pitch, 100))
        ev.append((tick + dur, 0x80 | ch, pitch, 64))
    tempo_us = int(round(60000.0 / bpm * 1000.0))
    write_midi_file(out, ev, ppq, tempo_us=tempo_us)
    return {"name": song["name"], "bpm": bpm, "notes": len(song["notes"])}


def write_midi_file(path: str, events, ppq: int, program: int = 0,
                    tempo_us: int = 500000) -> None:
    ev = sorted(events, key=lambda e: (e[0], e[1]))
    track = bytearray()
    track += _write_varlen(0) + bytes([0xFF, 0x51, 0x03,
                                       (tempo_us >> 16) & 0xFF,
                                       (tempo_us >> 8) & 0xFF,
                                       tempo_us & 0xFF])
    track += _write_varlen(0) + bytes([0xC0, program & 0x7F])
    last = 0
    for tick, status, d1, d2 in ev:
        if tick < last:
            tick = last
        track += _write_varlen(tick - last)
        track += bytes([status, d1 & 0x7F, d2 & 0x7F])
        last = tick
    track += _write_varlen(0) + bytes([0xFF, 0x2F, 0x00])
    out = bytearray()
    out += b"MThd" + struct.pack(">IHHH", 6, 0, 1, ppq)
    out += b"MTrk" + struct.pack(">I", len(track)) + bytes(track)
    with open(path, "wb") as f:
        f.write(bytes(out))


# ============================================================ SkyStudio 格式自检

SKYR_KEY_RE = re.compile(r"^(?:\d)?Key(\d+)$")


def skyr_parse(path: str) -> dict:
    """按 SkyStudio 谱面规范回读并校验输出，确认它能被播放器直接读取。

    检查项：BOM 编码、JSON 结构、key 命名、键位范围、和弦合并与总时长。
    """
    raw = open(path, "rb").read()
    if raw[:2] == b"\xff\xfe":
        text = raw[2:].decode("utf-16-le")
        enc = "UTF-16LE(BOM)"
    elif raw[:2] == b"\xfe\xff":
        text = raw[2:].decode("utf-16-be")
        enc = "UTF-16BE(BOM)"
    elif raw[:3] == b"\xef\xbb\xbf":
        text = raw[3:].decode("utf-8")
        enc = "UTF-8(BOM)"
    else:
        text = raw.decode("utf-8")
        enc = "UTF-8"

    root = json.loads(text)
    if not isinstance(root, list) or not root:
        raise ValueError("顶层必须是 JSON 数组")
    song = root[0]
    if song.get("isEncrypted", False):
        raise ValueError("乐谱被标记为加密，APP 会拒绝播放")
    notes = song.get("songNotes")
    if not notes or not isinstance(notes[0], dict):
        raise ValueError("songNotes 为空或格式不符")

    events = []
    first = notes[0]
    ft = int(first.get("time", 0))
    if ft > 0:
        events.append((ft, []))
    m = SKYR_KEY_RE.match(str(first.get("key", "")))
    if not m:
        raise ValueError("无法识别按键: %r" % first.get("key"))
    events.append((0, [int(m.group(1))]))

    prev_t = ft
    for i in range(1, len(notes)):
        cur = notes[i]
        ct = int(cur.get("time", 0))
        m = SKYR_KEY_RE.match(str(cur.get("key", "")))
        if not m:
            raise ValueError("无法识别按键: %r" % cur.get("key"))
        k = int(m.group(1))
        if ct == prev_t:
            events[-1][1].append(k)
        else:
            events.append((max(0, ct - prev_t), [k]))
        prev_t = ct

    return {
        "name": song.get("name", ""),
        "encoding": enc,
        "noteCount": len(notes),
        "eventCount": len(events),
        "polyphony": max((len(e[1]) for e in events), default=0),
        "durationMs": sum(e[0] for e in events),
        "keysUsed": sorted({k for e in events for k in e[1]}),
    }


# ============================================================ 预览

def preview(notes: Sequence[SkyNote]) -> str:
    lines: List[str] = []
    if not notes:
        return "（空）"
    t0 = notes[0].time_ms
    cur = None
    row: List[SkyNote] = []

    def flush(r):
        if not r:
            return ""
        t = (r[0].time_ms - t0) / 1000.0
        names = " ".join(DEGREE_NAMES[s.key_idx] for s in r)
        if len(r) > 1:
            names = "[" + names + "]"
        return "%6.2fs %-4s" % (t, names)

    out_rows = []
    for s in notes:
        if cur is None or s.time_ms != cur:
            if row:
                out_rows.append(flush(row))
            row = [s]
            cur = s.time_ms
        else:
            row.append(s)
    if row:
        out_rows.append(flush(row))

    buf = ""
    for cell in out_rows:
        if len(buf) + len(cell) > 76:
            lines.append(buf)
            buf = ""
        buf += cell + "  "
    if buf.strip():
        lines.append(buf)
    return "\n".join(lines)
