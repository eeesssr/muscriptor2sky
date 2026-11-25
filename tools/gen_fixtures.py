#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""gen_fixtures.py —— 生成 web/tests/fixtures/*.json（Python 侧是唯一真源）。

为什么要有这个脚本
==================
web/sky-core.js 是 muscriptor2sky/core.py 的 1:1 JS 移植，验收标准是
「同一个 MIDI + 同一组参数 -> 逐字节相同的 .txt」。所以夹具不能手写，
必须由 Python 参考实现跑出来，JS 侧只负责复现。

主体用**合成 MIDI**（用 core.write_midi_file / core._write_varlen 拼），
不往仓库里引入任何第三方版权 MIDI；唯一的外部输入是仓库自带的
examples/flower-dance/input.mid。

每个用例跑同一组 opts（默认 / grid=0 / grid=0.125 / transpose=none /
pitchLevel=3 / encoding=utf-8 / maxPoly=2 / virtualNotes=true / bpm=200），
每个 opts 组合产出：

    sha256   write_sky 写出的**完整字节**的哈希（含 BOM）
    size     字节数
    info     transpose / bpm / unitMs / range / stat / playability /
             melody / gridOk 等摘要
    checks   设计意图断言（Python 侧生成时先跑一遍，JS 侧再复验一次）

另外挑 3 个最小用例额外存 "expectText"（完整 JSON 文本），JS 侧失败时
可以直接 diff 出第一个不同的字节。

用法
====
    python tools/gen_fixtures.py            # 生成 / 刷新夹具
    python tools/gen_fixtures.py --check    # 只校验不写（CI 用，不一致则退出码 1）

脚本是幂等的：同样的 core.py 重跑一定得到同样的文件。
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import struct
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from muscriptor2sky import core  # noqa: E402

FIXTURES_DIR = os.path.join(REPO, "web", "tests", "fixtures")
PPQ = 480

# ============================================================ opts 组
#
# 键名是 JS 侧 opts 的 camelCase（见 web/API.md「Opts」表），
# 由 _opts_to_args() 翻译成 core.midi_to_sky 需要的 snake_case argparse.Namespace。
OPTS_GROUPS = [
    ("default", {}),
    ("grid-0", {"grid": 0}),
    ("grid-0.125", {"grid": 0.125}),
    ("transpose-none", {"transpose": "none"}),
    ("pitch-level-3", {"pitchLevel": 3}),
    ("encoding-utf8", {"encoding": "utf-8"}),
    ("max-poly-2", {"maxPoly": 2}),
    ("virtual-notes", {"virtualNotes": True}),
    ("bpm-200", {"bpm": 200}),
]


def _opts_to_args(slug: str, opts: dict) -> argparse.Namespace:
    """把夹具里的 JS 风格 opts 翻译成 core.midi_to_sky 认识的 args 对象。"""
    return argparse.Namespace(
        input=slug + ".mid",
        out=None,
        name=opts.get("name"),
        author=opts.get("author"),
        arranged=opts.get("arranged"),
        transcribed=opts.get("transcribed"),
        bpm=opts.get("bpm"),
        bits_per_page=int(opts.get("bitsPerPage", 16)),
        pitch_level=int(opts.get("pitchLevel", 0)),
        virtual_notes=bool(opts.get("virtualNotes", False)),
        encoding=opts.get("encoding", "utf-16"),
        root=int(opts.get("root", 60)),
        transpose=opts.get("transpose", "auto"),
        grid=float(opts.get("grid", 0.25)),
        max_poly=int(opts.get("maxPoly", 0)),
        ppq=int(opts.get("ppq", 480)),
        note_len=float(opts.get("noteLen", 0.25)),
        verify=False,
        no_preview=True,
    )


# ============================================================ 合成 MIDI
#
# 两套拼法：
#   _midi_via_core()  单轨 + 单速度 —— 直接用 core.write_midi_file
#   _build_midi()     多轨 / 多段速度 / 无速度 —— 按同样字节布局自己拼
#                     （write_midi_file 只会在 tick 0 写一个 tempo meta）

def _ev(notes, ch: int = 0, vel: int = 100):
    """[(tick, pitch|pitchlist, dur)] -> write_midi_file 的 (tick, status, d1, d2)。"""
    out = []
    for tick, pitch, dur in notes:
        ps = pitch if isinstance(pitch, (list, tuple)) else [pitch]
        for p in ps:
            out.append((int(tick), 0x90 | ch, int(p), int(vel)))
            out.append((int(tick) + int(dur), 0x80 | ch, int(p), 64))
    return out


def _midi_via_core(events, ppq: int = PPQ, tempo_us: int = 500000, program: int = 0) -> bytes:
    """用 core.write_midi_file 拼一个单轨 MIDI 并读回字节。"""
    fd, path = tempfile.mkstemp(suffix=".mid")
    os.close(fd)
    try:
        core.write_midi_file(path, events, ppq, program=program, tempo_us=tempo_us)
        with open(path, "rb") as f:
            return f.read()
    finally:
        os.unlink(path)


def _build_midi(tracks, ppq: int = PPQ) -> bytes:
    """自己拼 MIDI（format 1），支持多轨 / 多段 tempo / 完全没有 tempo。

    tracks: [{"tempos": [(tick, us)] | None,
              "program": int | None,
              "events": [(tick, status, d1, d2)]}]
    字节布局与 core.write_midi_file 一致（varlen delta + 原样事件字节）。
    """
    out = bytearray()
    out += b"MThd" + struct.pack(">IHHH", 6, 1, len(tracks), ppq)
    for tr in tracks:
        items = []                                   # (tick, order, payload)
        for tick, us in (tr.get("tempos") or []):
            items.append((int(tick), 0, bytes([
                0xFF, 0x51, 0x03,
                (us >> 16) & 0xFF, (us >> 8) & 0xFF, us & 0xFF,
            ])))
        prog = tr.get("program")
        if prog is not None:
            items.append((0, 1, bytes([0xC0, int(prog) & 0x7F])))
        for tick, status, d1, d2 in (tr.get("events") or []):
            order = 2 if (status & 0xF0) == 0x80 else 3   # 同一 tick 先 note-off
            items.append((int(tick), order,
                          bytes([status & 0xFF, d1 & 0x7F, d2 & 0x7F])))
        items.sort(key=lambda it: (it[0], it[1]))     # 稳定排序
        body = bytearray()
        last = 0
        for tick, _order, payload in items:
            body += core._write_varlen(tick - last)
            body += payload
            last = tick
        body += core._write_varlen(0) + bytes([0xFF, 0x2F, 0x00])
        out += b"MTrk" + struct.pack(">I", len(body)) + bytes(body)
    return bytes(out)


def _simple(notes, tempo_us: int = 500000, ppq: int = PPQ) -> bytes:
    return _midi_via_core(_ev(notes), ppq=ppq, tempo_us=tempo_us)


# ------------------------------------------------------------ 各个用例

def midi_c_major_simple() -> bytes:
    """纯白键 C 大调简单旋律：transpose 必须是 0。"""
    scale = [60, 62, 64, 65, 67, 69, 71, 72]
    return _simple([(i * PPQ, p, PPQ) for i, p in enumerate(scale)])


def midi_black_keys_heavy() -> bytes:
    """大量黑键：逼出 snapped 分支 + pick_snap_directions 的 32 种组合搜索。"""
    seq = [61, 63, 66, 68, 70, 61, 63, 66, 68, 70,
           72, 73, 75, 78, 80, 73, 75, 78, 80, 82]
    return _simple([(i * (PPQ // 2), p, PPQ // 2) for i, p in enumerate(seq)])


def midi_octave_fold() -> bytes:
    """音域远超 C4..C6：逼出八度折叠（stat.octave）。"""
    seq = [36, 43, 48, 55, 60, 67, 72, 79, 84, 91, 96, 84, 72, 60, 48]
    return _simple([(i * (PPQ // 2), p, PPQ // 2) for i, p in enumerate(seq)])


def midi_poly_chords() -> bytes:
    """多音同时发声（复音数 6）+ 一条打击乐轨（应被计进 drums 并丢弃）。"""
    chords = [
        [60, 62, 64, 65, 67, 69],
        [62, 64, 65, 67, 69, 71],
        [64, 65, 67, 69, 71, 72],
        [60, 64, 67, 72, 76, 79],
    ]
    mel = _ev([(i * PPQ, c, PPQ) for i, c in enumerate(chords)])
    drums = _ev([(i * PPQ, 36, 60) for i in range(len(chords))]
                + [(i * PPQ + 240, 38, 60) for i in range(len(chords))],
                ch=9, vel=90)
    return _build_midi([
        {"tempos": [(0, 500000)], "program": 0, "events": mel},
        {"tempos": None, "program": None, "events": drums},
    ])


def midi_merge_same_key() -> bytes:
    """同一时刻两个音被吸附/折叠到同一个键 -> stat.merged。

    B3(59) 低于音域下限被折叠成 B4(71)，而 B4(71) 本来就在音域内；
    同刻两者都落到键位 6，必须合并成 1 个。
    """
    spec = [
        (0, [59, 71], PPQ),            # 八度折叠撞键
        (PPQ, [47, 59], PPQ),          # 八度折叠撞键
        (2 * PPQ, [59, 71, 83], PPQ),  # 三个音挤进同一个键
        (3 * PPQ, [61, 62], PPQ),      # 半音吸附撞键：C#5 被吸到 D5
        (4 * PPQ, [47, 59, 71], PPQ),
    ]
    return _simple([(t, ps, d) for t, ps, d in spec])


def midi_maxpoly_drop() -> bytes:
    """6 音和弦，主旋律是每个 onset 的最高音；maxPoly=1/2 时伴奏被丢弃，
    但主旋律必须 100% 保留。"""
    chords = [
        [60, 64, 67, 72, 76, 79],
        [62, 65, 69, 74, 77, 81],
        [59, 62, 67, 71, 74, 79],
        [60, 64, 67, 72, 76, 84],
    ]
    return _simple([(i * PPQ, c, PPQ) for i, c in enumerate(chords)])


def midi_no_tempo() -> bytes:
    """完全没有 tempo meta -> TempoMap 应退回默认 500000us（120bpm）。"""
    scale = [60, 62, 64, 65, 67, 69, 71, 72, 74, 76]
    # 全用四分音符：finest_beats == 1，输出 bpm 直接等于源 bpm，
    # 所以 bpm==120 就是「默认 500000us」的直接证据。
    return _build_midi([{
        "tempos": None,
        "program": 0,
        "events": _ev([(i * PPQ, p, PPQ) for i, p in enumerate(scale)]),
    }])


def midi_tempo_changes() -> bytes:
    """3 段 tempo 变化（120 / 150 / 100 bpm）。"""
    tempos = [(0, 400000), (1920, 500000), (3840, 600000)]
    seq = [60, 62, 64, 67, 69, 71, 72, 74, 76, 79, 81, 84]
    return _build_midi([{
        "tempos": tempos,
        "program": 0,
        "events": _ev([(i * PPQ, p, PPQ) for i, p in enumerate(seq)]),
    }])


def midi_single_note() -> bytes:
    """只有一个音符的边界用例。"""
    return _simple([(0, 60, PPQ)])


def midi_empty() -> bytes:
    """空 MIDI：只有 MThd + 一个仅含 end-of-track 的 MTrk。"""
    return _midi_via_core([], ppq=PPQ)


def midi_dense_16th() -> bytes:
    """极密十六分音符（1/16 拍）：逼出 BEAT_SUBDIVISION 与 cell 计算。"""
    seq = [60, 62, 64, 65, 67, 69, 71, 72,
           71, 69, 67, 65, 64, 62, 60, 59,
           60, 62, 64, 65, 67, 69, 71, 72,
           74, 72, 71, 69, 67, 65, 64, 62]
    step = PPQ // 4                                  # 120 tick = 十六分音符
    return _simple([(i * step, p, step) for i, p in enumerate(seq)])


def midi_flower_dance() -> bytes:
    """仓库自带的真实用例（无版权问题）。"""
    path = os.path.join(REPO, "examples", "flower-dance", "input.mid")
    with open(path, "rb") as f:
        return f.read()


# ============================================================ 用例表

CASES = [
    {
        "slug": "c-major-simple",
        "source": "synthetic",
        "description": "纯白键 C 大调音阶，自动移调结果必须是 0",
        "midi": midi_c_major_simple,
        "checks": {
            "default": [
                {"kind": "transpose", "equals": 0},
                {"kind": "stat-min", "field": "snapped", "min": 0},
                {"kind": "keys-in-range"},
                {"kind": "melody-all-kept"},
            ],
            "transpose-none": [{"kind": "transpose", "equals": 0}],
            "pitch-level-3": [
                {"kind": "pitch-level", "equals": 3},
                {"kind": "mono"},
            ],
            "encoding-utf8": [{"kind": "size-ne"}],
            "grid-0": [{"kind": "stat-eq-default"}],
        },
        "expectTextGroups": ["default"],
    },
    {
        "slug": "black-keys-heavy",
        "source": "synthetic",
        "description": "大量黑键，触发 snapped 与 pick_snap_directions 的 32 种组合搜索",
        "midi": midi_black_keys_heavy,
        "checks": {
            "default": [
                {"kind": "transpose", "equals": -1},
                {"kind": "stat-eq", "field": "snapped", "equals": 0},
                {"kind": "keys-in-range"},
            ],
            "transpose-none": [
                {"kind": "stat-min", "field": "snapped", "min": 10},
                {"kind": "keys-in-range"},
            ],
            # 自动移调后全是白键（snapped=0），虚音模式没有可补的音 -> 输出与 default 相同
            "virtual-notes": [
                {"kind": "transpose", "equals": -1},
                {"kind": "stat-eq-default"},
            ],
            "bpm-200": [{"kind": "size-ne"}, {"kind": "keys-in-range"}],
        },
    },
    {
        "slug": "octave-fold",
        "source": "synthetic",
        "description": "音域 C2..C7，远超 C4..C6，触发八度折叠",
        "midi": midi_octave_fold,
        "checks": {
            "default": [
                {"kind": "stat-min", "field": "octave", "min": 5},
                {"kind": "keys-in-range"},
            ],
            "bpm-200": [{"kind": "size-ne"}],
            "grid-0": [{"kind": "stat-eq-default"}],
        },
    },
    {
        "slug": "poly-chords",
        "source": "synthetic",
        "description": "6 音同时发声 + 打击乐轨（drums 计数后丢弃）",
        "midi": midi_poly_chords,
        "checks": {
            "default": [
                {"kind": "max-poly-at-least", "min": 3},
                {"kind": "max-poly-at-most", "max": 6},
                {"kind": "drums", "equals": 8},
                {"kind": "keys-in-range"},
            ],
            "max-poly-2": [
                {"kind": "max-poly-at-most", "max": 2},
                {"kind": "stat-min", "field": "dropped", "min": 1},
                {"kind": "melody-all-kept"},
            ],
        },
    },
    {
        "slug": "merge-same-key",
        "source": "synthetic",
        "description": "同刻两个音折叠到同一个键，触发 merged（transpose=none 下必然发生）",
        "midi": midi_merge_same_key,
        "checks": {
            "default": [
                {"kind": "stat-min", "field": "merged", "min": 1},
                {"kind": "keys-in-range"},
            ],
            "transpose-none": [
                {"kind": "stat-min", "field": "merged", "min": 2},
                {"kind": "keys-in-range"},
            ],
        },
        "expectTextGroups": ["transpose-none"],
    },
    {
        "slug": "maxpoly-drop",
        "source": "synthetic",
        "description": "6 音和弦 + maxPoly=1/2，触发 dropped，主旋律必须全部保留",
        "midi": midi_maxpoly_drop,
        "extraGroups": [("max-poly-1", {"maxPoly": 1})],
        "checks": {
            "max-poly-1": [
                {"kind": "stat-min", "field": "dropped", "min": 1},
                {"kind": "melody-all-kept"},
                {"kind": "max-poly-at-most", "max": 1},
                {"kind": "keys-in-range"},
            ],
            "max-poly-2": [
                {"kind": "stat-min", "field": "dropped", "min": 1},
                {"kind": "melody-all-kept"},
                {"kind": "max-poly-at-most", "max": 2},
            ],
            "default": [{"kind": "melody-all-kept"}],
        },
    },
    {
        "slug": "no-tempo",
        "source": "synthetic",
        "description": "没有 tempo 事件，TempoMap 应退回默认 500000us = 120bpm",
        "midi": midi_no_tempo,
        "checks": {
            "default": [
                {"kind": "no-tempo-120"},
                {"kind": "keys-in-range"},
                {"kind": "melody-all-kept"},
            ],
        },
    },
    {
        "slug": "tempo-changes",
        "source": "synthetic",
        "description": "3 段 tempo 变化（首段 150bpm，后接 120 / 100）",
        "midi": midi_tempo_changes,
        "checks": {
            "default": [
                {"kind": "bpm", "equals": 150.0},
                {"kind": "keys-in-range"},
            ],
            "bpm-200": [{"kind": "bpm", "equals": 200.0}, {"kind": "size-ne"}],
        },
    },
    {
        "slug": "single-note",
        "source": "synthetic",
        "description": "只有一个音符的边界用例",
        "midi": midi_single_note,
        "checks": {
            "default": [{"kind": "notes-at-least", "min": 1}, {"kind": "keys-in-range"}],
            "pitch-level-3": [
                {"kind": "pitch-level", "equals": 3},
                {"kind": "mono"},
            ],
            "encoding-utf8": [{"kind": "size-ne"}],
        },
        "expectTextGroups": ["default"],
    },
    {
        "slug": "empty-midi",
        "source": "synthetic",
        "description": "空 MIDI（只有 end-of-track），midiToSky 应返回空音符 + error",
        "midi": midi_empty,
        "checks": {
            "default": [{"kind": "error"}],
        },
    },
    {
        "slug": "dense-16th",
        "source": "synthetic",
        "description": "极密十六分音符，触发 BEAT_SUBDIVISION 与 cell 计算",
        "midi": midi_dense_16th,
        "checks": {
            "default": [{"kind": "keys-in-range"}, {"kind": "melody-all-kept"}],
        },
    },
    {
        "slug": "flower-dance",
        "source": "examples/flower-dance/input.mid",
        "description": "仓库自带的真实 MIDI（Flower Dance），全量回归",
        "midi": midi_flower_dance,
        "checks": {
            "default": [
                {"kind": "keys-in-range"},
                {"kind": "melody-all-kept"},
                {"kind": "stat-min", "field": "octave", "min": 1},
                {"kind": "stat-min", "field": "merged", "min": 1},
            ],
            "transpose-none": [
                {"kind": "stat-min", "field": "snapped", "min": 100},
                {"kind": "keys-in-range"},
            ],
            # 注意：maxPoly 是软上限。多个 onset 被 grid 量化进同一个拍桶后，
            # 每个 onset 的主旋律音都必须保留（main-melody-first 规则优先于上限），
            # 所以和弦峰值可能超过 maxPoly。这里只断言「确实丢了伴奏」。
            "max-poly-2": [
                {"kind": "stat-min", "field": "dropped", "min": 1},
                {"kind": "melody-all-kept"},
            ],
            "virtual-notes": [{"kind": "stat-min", "field": "virtual", "min": 1}],
            "bpm-200": [{"kind": "bpm", "equals": 800.0}],
        },
    },
]


# ============================================================ checks

def _max_poly(notes) -> int:
    by_time = {}
    for s in notes:
        by_time.setdefault(s.time_ms, 0)
        by_time[s.time_ms] += 1
    return max(by_time.values()) if by_time else 0


def _stat_of(info) -> dict:
    """空 MIDI 的 info 里没有 stat，统一补一个全零的。"""
    return info.get("stat") or {
        "exact": 0, "octave": 0, "snapped": 0, "merged": 0, "dropped": 0,
    }


def _check_one(chk, notes, info) -> None:
    """跑一条 check。

    kind 一览（夹具里会原样存下来，JS 侧再复验一遍）：
      error               期望 notes 为空且 info.error 存在
      transpose           info.transpose == equals
      stat-min            info.stat[field] >= min
      stat-eq             info.stat[field] == equals
      melody-all-kept     info.melody.kept == info.melody.total
      max-poly-at-most    同一 time 的键数 <= max
      max-poly-at-least   同一 time 的键数 >= min
      keys-in-range       0 <= key_idx <= 14
      notes-at-least      len(notes) >= min
      pitch-level         info.pitch_level == equals
      stat-eq-default     本组 stat 与 default 组完全相同（opts 不该改映射）
      size-ne             writeSky 字节数与 default 组不同（opts 确实生效）
      no-tempo-120        没有 tempo 事件时 bpm 必须是 120（500000us）
      mono                pitchLevel 只写头部字段，音符必须与 default 组一致
    """
    kind = chk["kind"]
    st = _stat_of(info)

    if kind == "error":
        if notes:
            raise AssertionError("期望空结果，实际有 %d 个音符" % len(notes))
        if not info.get("error"):
            raise AssertionError("期望 info.error，实际 %r" % (info,))
    elif kind == "transpose":
        if info["transpose"] != chk["equals"]:
            raise AssertionError("transpose 期望 %d，实际 %d"
                                 % (chk["equals"], info["transpose"]))
    elif kind == "stat-min":
        got = st.get(chk["field"], 0)
        if got < chk["min"]:
            raise AssertionError("stat.%s 期望 >= %d，实际 %d"
                                 % (chk["field"], chk["min"], got))
    elif kind == "stat-eq":
        got = st.get(chk["field"], 0)
        if got != chk["equals"]:
            raise AssertionError("stat.%s 期望 == %d，实际 %d"
                                 % (chk["field"], chk["equals"], got))
    elif kind == "melody-all-kept":
        md = info["melody"]
        if md["kept"] != md["total"]:
            raise AssertionError("主旋律没全部保留：%d/%d" % (md["kept"], md["total"]))
    elif kind == "max-poly-at-most":
        got = _max_poly(notes)
        if got > chk["max"]:
            raise AssertionError("复音数期望 <= %d，实际 %d" % (chk["max"], got))
    elif kind == "max-poly-at-least":
        got = _max_poly(notes)
        if got < chk["min"]:
            raise AssertionError("复音数期望 >= %d，实际 %d" % (chk["min"], got))
    elif kind == "keys-in-range":
        for s in notes:
            if not (0 <= s.key_idx <= 14):
                raise AssertionError("键位越界: %d" % s.key_idx)
    elif kind == "notes-at-least":
        if len(notes) < chk["min"]:
            raise AssertionError("音符数期望 >= %d，实际 %d" % (chk["min"], len(notes)))
    elif kind == "bpm":
        if abs(float(info["bpm"]) - float(chk["equals"])) > 1e-9:
            raise AssertionError("bpm 期望 %r，实际 %r" % (chk["equals"], info["bpm"]))
    elif kind == "drums":
        if int(info.get("drums", 0)) != int(chk["equals"]):
            raise AssertionError("drums 期望 %d，实际 %r"
                                 % (chk["equals"], info.get("drums")))
    elif kind == "pitch-level":
        if info["pitch_level"] != chk["equals"]:
            raise AssertionError("pitch_level 期望 %d，实际 %d"
                                 % (chk["equals"], info["pitch_level"]))
    elif kind == "no-tempo-120":
        if abs(float(info["bpm"]) - 120.0) > 1e-9:
            raise AssertionError("无 tempo 事件时期望 bpm=120，实际 %r" % (info["bpm"],))
    elif kind in ("stat-eq-default", "size-ne", "mono"):
        # 这三条要跟同夹具的 default 组比较，由 _run_checks 统一处理
        raise AssertionError("check %r 必须在 _run_checks 里处理" % (kind,))
    else:
        raise AssertionError("未知 check: %r" % (kind,))


def _run_checks(checks, notes, info, ref) -> None:
    """在 Python 侧先把「设计意图」验一遍，脚本跑不通就不该产出夹具。

    ref 是同一夹具 default 组的结果摘要（{size, stat, keys, noteCount}），
    供 stat-eq-default / size-ne / mono 三条「跨组」check 使用。
    """
    for chk in checks:
        kind = chk["kind"]
        if kind == "stat-eq-default":
            if ref is None:
                raise AssertionError("stat-eq-default 需要 default 组先跑")
            if _stat_of(info) != ref["stat"]:
                raise AssertionError("stat 与 default 不同: %r != %r"
                                     % (_stat_of(info), ref["stat"]))
        elif kind == "size-ne":
            if ref is None:
                raise AssertionError("size-ne 需要 default 组先跑")
            if chk["_size"] == ref["size"]:
                raise AssertionError("本组字节数与 default 相同（%d），opts 没生效"
                                     % chk["_size"])
        elif kind == "mono":
            if ref is None:
                raise AssertionError("mono 需要 default 组先跑")
            cur = [(s.time_ms, s.key_idx) for s in notes]
            if cur != ref["keys"]:
                raise AssertionError("pitchLevel 不应改变音符，但映射变了")
        else:
            _check_one(chk, notes, info)


# ============================================================ 生成

def _decode_text(raw: bytes) -> str:
    if raw[:2] == b"\xff\xfe":
        return raw[2:].decode("utf-16-le")
    if raw[:3] == b"\xef\xbb\xbf":
        return raw[3:].decode("utf-8")
    return raw.decode("utf-8")


def _run_one(midi_path: str, slug: str, opts: dict) -> dict:
    """跑一组 opts，返回 {case, notes, info, size, raw_text}。"""
    args = _opts_to_args(slug, opts)
    m = core.read_midi(midi_path)
    notes, info = core.midi_to_sky(m, args)
    if not notes:
        # 空 MIDI：core.midi_to_sky 返回 ([], {"error": ...})，没有别的字段。
        # 夹具里也只留 error，JS 侧断言 notes 为空 + info.error 完全相等。
        return {
            "case": {
                "opts": opts,
                "error": info.get("error", ""),
            },
            "notes": [],
            "info": info,
            "size": 0,
            "raw": b"",
        }

    fd, out_path = tempfile.mkstemp(suffix=".txt")
    os.close(fd)
    try:
        core.write_sky(out_path, notes, args, info)
        with open(out_path, "rb") as f:
            raw = f.read()
    finally:
        os.unlink(out_path)

    summary = {
        "transpose": info["transpose"],
        "bpm": info["bpm"],
        "unitMs": info["unit_ms"],
        "timeUnitBeats": info["time_unit_beats"],
        "range": [info["range"][0], info["range"][1]],
        "stat": dict(info["stat"]),
        "drums": info["drums"],
        "src": info["src"],
        "noteCount": len(notes),
        "playability": info["playability"],
        "melody": dict(info["melody"]),
        "pitchLevel": info["pitch_level"],
        "gridOk": bool(info["grid_ok"]),
    }
    return {
        "case": {
            "opts": opts,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "size": len(raw),
            "info": summary,
        },
        "notes": notes,
        "info": info,
        "size": len(raw),
        "raw": raw,
    }


def _make_fixture(spec: dict) -> dict:
    slug = spec["slug"]
    midi_bytes = spec["midi"]()
    groups = list(OPTS_GROUPS) + list(spec.get("extraGroups", []))
    expect_groups = set(spec.get("expectTextGroups", []))
    checks_map = spec.get("checks", {})

    fd, midi_path = tempfile.mkstemp(suffix=".mid")
    os.close(fd)
    try:
        with open(midi_path, "wb") as f:
            f.write(midi_bytes)
        # 先跑 default 组，后面的跨组 check 都以它为参照
        default_checks = list(checks_map.get("default", []))
        default_run = _run_one(midi_path, slug, _merge_opts(slug, dict(groups)["default"]))
        is_error_fixture = not default_run["notes"]
        if is_error_fixture:
            default_checks = [{"kind": "error"}]
        ref = {
            "size": default_run["size"],
            "stat": _stat_of(default_run["info"]),
            "keys": [(s.time_ms, s.key_idx) for s in default_run["notes"]],
            "noteCount": len(default_run["notes"]),
        }
        _run_checks(default_checks or [{"kind": "keys-in-range"}],
                    default_run["notes"], default_run["info"], ref)

        cases = []
        for group_name, group_opts in groups:
            opts = _merge_opts(slug, group_opts)
            checks = list(checks_map.get(group_name, []))
            if not checks:
                # 没显式声明时给一条兜底：空输入仍应报错，否则不许越界键位
                checks = ([{"kind": "error"}] if is_error_fixture
                          else [{"kind": "keys-in-range"}])
            if group_name == "default":
                run = default_run
            else:
                run = _run_one(midi_path, slug, opts)
            # size-ne 要在 checks 里带上本组字节数才能比较
            resolved = []
            for chk in checks:
                if chk["kind"] == "size-ne":
                    chk = dict(chk, _size=run["size"])
                resolved.append(chk)
            try:
                _run_checks(resolved, run["notes"], run["info"], ref)
            except AssertionError as e:
                raise AssertionError("[%s / %s] %s" % (slug, group_name, e))

            case = run["case"]
            case["name"] = group_name
            # 去掉 checks 里的内部字段，夹具里只留纯数据
            case["checks"] = [
                {k: v for k, v in chk.items() if not k.startswith("_")}
                for chk in resolved
            ]
            if group_name in expect_groups and run["raw"]:
                case["expectText"] = _decode_text(run["raw"])
            cases.append(case)
    finally:
        os.unlink(midi_path)

    return {
        "slug": slug,
        "source": spec["source"],
        "description": spec["description"],
        "ppq": PPQ,
        "midiSha256": hashlib.sha256(midi_bytes).hexdigest(),
        "midiB64": base64.b64encode(midi_bytes).decode("ascii"),
        "cases": cases,
    }


def _merge_opts(slug: str, group_opts: dict) -> dict:
    opts = {"name": slug, "fileName": slug + ".mid"}
    opts.update(group_opts)
    return opts


def build_all() -> dict:
    """返回 {文件名: JSON 文本}。"""
    out = {}
    for spec in CASES:
        fx = _make_fixture(spec)
        text = json.dumps(fx, ensure_ascii=False, indent=2) + "\n"
        out[spec["slug"] + ".json"] = text
    return out


# ============================================================ CLI

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="gen_fixtures.py",
        description="生成 web/tests/fixtures/*.json（Python 参考实现是唯一真源）",
    )
    ap.add_argument("--check", action="store_true",
                    help="只校验磁盘上的夹具是否与 Python 输出一致，不写文件")
    ap.add_argument("--out", default=FIXTURES_DIR, help="夹具输出目录")
    ns = ap.parse_args(argv)

    out_dir = os.path.abspath(ns.out)
    generated = build_all()

    total_cases = sum(len(json.loads(t)["cases"]) for t in generated.values())
    shas = []
    for name in sorted(generated):
        for c in json.loads(generated[name])["cases"]:
            if "sha256" in c:
                shas.append((name, c["name"], c["sha256"]))
                break

    if ns.check:
        problems = []
        existing = set()
        if os.path.isdir(out_dir):
            existing = {f for f in os.listdir(out_dir) if f.endswith(".json")}
        for name in sorted(generated):
            path = os.path.join(out_dir, name)
            if not os.path.exists(path):
                problems.append("缺少: %s" % name)
                continue
            with open(path, "r", encoding="utf-8") as f:
                disk = f.read()
            if disk != generated[name]:
                problems.append("内容不一致: %s" % name)
        for name in sorted(existing - set(generated)):
            problems.append("多余文件: %s" % name)
        if problems:
            print("夹具校验失败（%d 处）：" % len(problems))
            for p in problems:
                print("  - " + p)
            print("请运行: python tools/gen_fixtures.py")
            return 1
        print("夹具校验通过：%d 个文件 / %d 个 case" % (len(generated), total_cases))
        for name, case_name, sha in shas[:3]:
            print("  %s [%s] %s" % (name, case_name, sha))
        return 0

    os.makedirs(out_dir, exist_ok=True)
    # 清掉不在本次生成范围内的旧夹具，保证目录与脚本严格对应
    for f in os.listdir(out_dir):
        if f.endswith(".json") and f not in generated:
            os.unlink(os.path.join(out_dir, f))
    for name in sorted(generated):
        path = os.path.join(out_dir, name)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(generated[name])

    print("已写出 %d 个夹具到 %s" % (len(generated), out_dir))
    print("总 case 数: %d" % total_cases)
    for name, case_name, sha in shas[:3]:
        print("  %s [%s] %s" % (name, case_name, sha))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
