#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""命令行入口：muscriptor2sky"""

from __future__ import annotations

import argparse
import os
import sys

from .core import (
    NOTE_NAMES,
    midi_to_sky,
    preview,
    read_midi,
    read_sky,
    sky_to_midi,
    skyr_parse,
    write_sky,
)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="muscriptor2sky",
        description="把 MIDI 转换成光遇（Sky）15 键琴谱 txt（兼容 SkyStudio）",
        epilog="示例: muscriptor2sky song.mid -n 曲名 -a 作者 --verify",
    )
    ap.add_argument("input", help="输入 .mid/.midi；或反向模式下的光遇琴谱 .txt")
    ap.add_argument("-o", "--out", default=None, help="输出路径（默认同名换扩展名）")
    ap.add_argument("-n", "--name", default=None, help="曲名（写入 name 字段）")
    ap.add_argument("-a", "--author", default=None, help="作者（写入 author 字段）")
    ap.add_argument("--arranged", default=None, help="arrangedBy 字段")
    ap.add_argument("--transcribed", default=None, help="transcribedBy 字段")
    ap.add_argument("--bpm", type=float, default=None, help="bpm 字段（默认取 MIDI 速度）")
    ap.add_argument("--bits-per-page", type=int, default=16, help="bitsPerPage 字段，默认 16")
    ap.add_argument("--pitch-level", type=int, default=0, help="pitchLevel 字段，默认 0")
    ap.add_argument(
        "--encoding", default="utf-16",
        help="输出编码：utf-16（默认，SkyStudio 标准）| utf-8",
    )
    ap.add_argument("--root", type=int, default=60, help="最低键 MIDI 音高，默认 60=C4")
    ap.add_argument(
        "--transpose", default="auto",
        help="auto 自动移调到 C 大调 | none 保持原调（默认 auto）",
    )
    ap.add_argument("--grid", type=float, default=0.25, help="量化网格（拍），0 关闭，默认 0.25")
    ap.add_argument("--max-poly", type=int, default=0, help="同时发音上限，0=不限，默认 0")
    ap.add_argument("--verify", action="store_true", help="按 SkyStudio 谱面规范回读自检")
    ap.add_argument("--ppq", type=int, default=480, help="反向模式 MIDI 的 ppq，默认 480")
    ap.add_argument("--note-len", type=float, default=0.25, help="反向模式音符长度（拍），默认 0.25")
    ap.add_argument("--no-preview", action="store_true", help="不打印简谱预览")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    ext = os.path.splitext(args.input)[1].lower()

    # ---------------- 反向：琴谱 -> MIDI
    if ext == ".txt":
        out = args.out or os.path.splitext(args.input)[0] + ".mid"
        info = sky_to_midi(args.input, out, args)
        print(
            "反向转换: %s -> %s（%d 个音, bpm=%s）"
            % (os.path.basename(args.input), out, info["notes"], info["bpm"])
        )
        return 0

    # ---------------- 正向：MIDI -> 琴谱
    try:
        m = read_midi(args.input)
    except FileNotFoundError:
        print("错误: 找不到文件 %s" % args.input, file=sys.stderr)
        return 1
    except ValueError as e:
        print("错误: %s" % e, file=sys.stderr)
        return 1

    notes, info = midi_to_sky(m, args)
    if not notes:
        print("没有可输出的音符: %s" % info.get("error", ""), file=sys.stderr)
        return 1

    out = args.out or os.path.splitext(args.input)[0] + ".txt"
    if not out.lower().endswith(".txt"):
        out += ".txt"
    write_sky(out, notes, args, info)

    st = info["stat"]
    lo, hi = info["range"]
    print("输入: %s" % os.path.basename(args.input))
    print(
        "音域: 15 键 C 大调 %s(%d) ~ %s(%d)"
        % (NOTE_NAMES[lo % 12], lo, NOTE_NAMES[hi % 12], hi)
    )
    print(
        "移调: %+d 半音   bpm: %s   源音符: %d   鼓(丢弃): %d"
        % (info["transpose"], int(args.bpm or info["bpm"]), info["src"], info["drums"])
    )
    print(
        "映射: 精确 %d / 八度折叠 %d / 半音吸附 %d / 同键合并 %d / 超复音丢弃 %d"
        % (st["exact"], st["octave"], st["snapped"], st["merged"], st["dropped"])
    )
    print("输出音符: %d" % len(notes))

    if not args.no_preview:
        print("-" * 78)
        print(preview(notes))

    print("-" * 78)
    print("已写出: %s" % out)

    if args.verify:
        try:
            v = skyr_parse(out)
        except Exception as e:
            print("[格式自检] 失败: %s" % e)
            return 2
        bad = [k for k in v["keysUsed"] if not (0 <= k <= 14)]
        print(
            "[格式自检] 编码 %s | 音符 %d | 事件 %d | 最大复音 %d | 时长 %.1fs"
            % (
                v["encoding"],
                v["noteCount"],
                v["eventCount"],
                v["polyphony"],
                v["durationMs"] / 1000.0,
            )
        )
        print("[格式自检] 用到键位 %s" % v["keysUsed"])
        if bad:
            print("[格式自检] 越界键位: %s" % bad)
            return 2
        print("[格式自检] 通过，可直接被 APP 播放")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
