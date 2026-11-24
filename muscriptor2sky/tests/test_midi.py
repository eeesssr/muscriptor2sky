# -*- coding: utf-8 -*-
"""MIDI 读写与往返一致性测试。"""

import struct

import pytest

from muscriptor2sky.core import read_midi, write_midi_file


def make_simple_midi(path, notes, ppq=480, tempo_us=500000):
    """notes: [(tick, pitch, dur_tick), ...]"""
    events = []
    for tick, pitch, dur in notes:
        events.append((tick, 0x90, pitch, 100))
        events.append((tick + dur, 0x80, pitch, 64))
    write_midi_file(str(path), events, ppq, tempo_us=tempo_us)


def test_read_midi_roundtrip(tmp_path):
    mid = tmp_path / "a.mid"
    make_simple_midi(mid, [(0, 60, 480), (480, 64, 480)])
    m = read_midi(str(mid))
    assert m.ppq == 480
    assert len(m.notes) == 2
    assert [n.pitch for n in m.notes] == [60, 64]
    assert m.notes[0].start == 0
    assert m.notes[1].start == 480


def test_read_midi_ignores_drums(tmp_path):
    """channel 9 是打击乐，必须被跳过并计数。"""
    mid = tmp_path / "drum.mid"
    write_midi_file(
        str(mid),
        [
            (0, 0x90, 60, 100),
            (480, 0x80, 60, 64),
            (0, 0x99, 36, 110),   # drums (channel 9)
            (480, 0x89, 36, 64),
        ],
        480,
    )
    m = read_midi(str(mid))
    assert len(m.notes) == 1
    assert m.notes[0].pitch == 60
    assert m.drums >= 1


def test_read_midi_handles_program_change(tmp_path):
    """program change 只有 1 个数据字节，解析器不能多吃。

    早期版本按 2 字节读取，导致后续整个字节流错位、时间戳全乱。
    """
    mid = tmp_path / "pc.mid"
    events = [
        (0, 0xC0, 0, 0),        # program change: 只写 status + 1 byte
        (0, 0x90, 60, 100),
        (480, 0x80, 60, 64),
    ]
    write_midi_file(str(mid), events, 480)
    m = read_midi(str(mid))
    assert len(m.notes) == 1
    assert m.notes[0].start == 0
    assert m.notes[0].pitch == 60


def test_read_midi_rejects_non_midi(tmp_path):
    bad = tmp_path / "x.mid"
    bad.write_bytes(b"not a midi file")
    with pytest.raises(ValueError):
        read_midi(str(bad))
