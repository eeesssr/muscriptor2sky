"""muscriptor2sky: 把 MIDI 转换成光遇（Sky）15 键琴谱，兼容 SkyStudio。"""

from .core import (
    DEGREE_NAMES,
    MAJOR_STEPS,
    NOTE_NAMES,
    Midi,
    Note,
    SkyNote,
    build_keys,
    key_id,
    midi_to_sky,
    read_midi,
    read_sky,
    skyr_parse,
    sky_to_midi,
    write_sky,
)

__version__ = "1.0.0"

__all__ = [
    "DEGREE_NAMES",
    "MAJOR_STEPS",
    "NOTE_NAMES",
    "Midi",
    "Note",
    "SkyNote",
    "build_keys",
    "key_id",
    "midi_to_sky",
    "read_midi",
    "read_sky",
    "skyr_parse",
    "sky_to_midi",
    "write_sky",
    "__version__",
]
