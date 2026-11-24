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
    """选一个整体移调量，让最多的音正好落在 15 个白键上。"""
    if not weighted:
        return 0
    total = sum(w for _, w in weighted) or 1.0
    best = None
    for t in range(-6, 7):
        diatonic = 0.0
        folds = 0.0
        hist: Dict[int, float] = {}
        for p, w in weighted:
            q = p + t
            pc = q % 12
            hist[pc] = hist.get(pc, 0.0) + w
            if pc in key_pcs:
                diatonic += w
            folds += w * fold_steps(q, lo, hi)
        tonic_pc = max(hist, key=lambda k: hist[k])
        bonus = 0.06 if tonic_pc in (0, 9) else 0.0
        bonus += 0.02 * (hist.get(7, 0.0) / total)
        score = diatonic / total - 0.05 * (folds / total) + bonus
        cand = (round(score, 6), -abs(t), t)
        if best is None or cand > best:
            best = cand
    return best[2]


def snap(p: int, keys: Sequence[int], prefer_up: bool, bass_pc: Optional[int]) -> int:
    def rank(k: int) -> Tuple[int, int, int]:
        d = abs(k - p)
        up = 0 if ((k > p) if prefer_up else (k < p)) else 1
        cons = 0
        if bass_pc is not None:
            cons = 0 if ((k - bass_pc) % 12) in CONSONANT else 1
        return (d, cons, up)
    return min(keys, key=rank)


# ============================================================ MIDI -> 光遇

@dataclass
class SkyNote:
    time_ms: int
    key_idx: int
    layer: int = 1
    src_pitch: int = 0
    how: str = "exact"


def midi_to_sky(m: Midi, args) -> Tuple[List[SkyNote], dict]:
    ppq = m.ppq
    tmap = TempoMap(ppq, m.tempos)
    keys = build_keys(args.root, 15)
    lo, hi = keys[0], keys[-1]
    key_pcs = {k % 12 for k in keys}
    grid_beats = args.grid if (args.grid and args.grid > 0) else 0.0

    notes = [n for n in m.notes if n.dur >= 1]
    if not notes:
        return [], {"error": "没有可用音符"}

    if args.transpose == "none":
        transpose = 0
    else:
        beat_len = ppq / 4.0
        weighted = [(n.pitch, (n.dur / beat_len) ** 0.5) for n in notes]
        transpose = pick_transpose(weighted, key_pcs, lo, hi)

    # 旋律走向（黑键吸附平局时用）
    ordered = sorted(notes, key=lambda n: (n.start, n.pitch))
    nxt: Dict[int, int] = {}
    prv: Dict[int, int] = {}
    for i, n in enumerate(ordered):
        if i + 1 < len(ordered):
            nxt[id(n)] = ordered[i + 1].pitch
        if i > 0:
            prv[id(n)] = ordered[i - 1].pitch

    # 按量化后的时间分桶
    # 注意：SkyStudio 谱面规范的 key 形如 "^(?:\d)?Key(\d+)$"，前缀数字会被忽略，
    # 因此所有音统一写 "1KeyN"，不要臆造 2Key 分层（那不会产生第二个八度）。
    buckets: Dict[int, List[Note]] = {}
    for n in notes:
        beat = n.start / ppq
        if grid_beats > 0:
            beat = round(beat / grid_beats) * grid_beats
        tick = beat * ppq
        ms = tmap.to_ms(tick)
        buckets.setdefault(round(ms), []).append(n)

    out: List[SkyNote] = []
    stat = {"exact": 0, "octave": 0, "snapped": 0, "merged": 0, "dropped": 0}

    for ms in sorted(buckets):
        grp = buckets[ms]
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
                k = snap(folded, keys, prefer_up, bass_pc)
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

        for k in sorted(seen):
            how = seen[k][1]
            stat[how] += 1
            out.append(SkyNote(ms, keys.index(k), 1, k - transpose, how))

    out.sort(key=lambda s: (s.time_ms, s.key_idx))
    return out, {
        "transpose": transpose,
        "bpm": tmap.bpm(),
        "range": (lo, hi),
        "stat": stat,
        "drums": m.drums,
        "src": len(notes),
    }


def write_sky(path: str, notes: Sequence[SkyNote], args, info: dict) -> None:
    songNotes = [{"time": int(s.time_ms), "key": key_id(s.key_idx)} for s in notes]
    meta = {
        "name": args.name or os.path.splitext(os.path.basename(args.input))[0],
        "author": args.author or "",
        "arrangedBy": args.arranged or "",
        "transcribedBy": args.transcribed or "MuScriptor",
        "permission": "",
        "isComposed": True,
        "bpm": int(args.bpm or info.get("bpm", 300)),
        "bitsPerPage": int(args.bits_per_page),
        "pitchLevel": int(args.pitch_level),
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
