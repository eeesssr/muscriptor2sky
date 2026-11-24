# -*- coding: utf-8 -*-
"""反向转换（琴谱 -> MIDI）与往返一致性测试。"""

import types

from muscriptor2sky.core import (
    midi_to_sky,
    read_midi,
    read_sky,
    sky_to_midi,
    write_sky,
    write_midi_file,
)


def _args(**kw):
    base = dict(
        root=60, transpose="auto", grid=0.25, max_poly=0,
        name="t", author="", arranged=None, transcribed=None, bpm=None,
        bits_per_page=16, pitch_level=0, encoding="utf-16",
        input="a.mid", ppq=480, note_len=0.25,
    )
    base.update(kw)
    return types.SimpleNamespace(**base)


def test_sky_to_midi_produces_notes(tmp_path):
    """琴谱转 MIDI 后音数应保持一致。"""
    mid = tmp_path / "s.mid"
    events = []
    for i, p in enumerate([60, 62, 64]):
        t = i * 480
        events.append((t, 0x90, p, 100))
        events.append((t + 400, 0x80, p, 64))
    write_midi_file(str(mid), events, 480)

    m = read_midi(str(mid))
    notes, info = midi_to_sky(m, _args())
    txt = tmp_path / "s.txt"
    write_sky(str(txt), notes, _args(), info)

    out_mid = tmp_path / "back.mid"
    result = sky_to_midi(str(txt), str(out_mid), _args())
    assert result["notes"] == len(notes)

    m2 = read_midi(str(out_mid))
    assert len(m2.notes) == len(notes)


def test_roundtrip_preserves_songnotes(tmp_path):
    """完整往返：MIDI -> 琴谱 -> MIDI -> 琴谱，songNotes 应完全一致。"""
    mid = tmp_path / "a.mid"
    events = []
    pitches = [60, 64, 67, 72]
    for i, p in enumerate(pitches):
        t = i * 480
        events.append((t, 0x90, p, 100))
        events.append((t + 400, 0x80, p, 64))
    write_midi_file(str(mid), events, 480, tempo_us=200000)   # bpm=300

    m = read_midi(str(mid))
    notes1, info1 = midi_to_sky(m, _args())
    txt1 = tmp_path / "1.txt"
    write_sky(str(txt1), notes1, _args(), info1)

    mid2 = tmp_path / "2.mid"
    sky_to_midi(str(txt1), str(mid2), _args())

    m2 = read_midi(str(mid2))
    # bpm 必须跟着走，否则时间轴会被整体缩放
    notes2, info2 = midi_to_sky(m2, _args())
    txt2 = tmp_path / "2.txt"
    write_sky(str(txt2), notes2, _args(), info2)

    a = read_sky(str(txt1))[0]["notes"]
    b = read_sky(str(txt2))[0]["notes"]
    assert a == b
