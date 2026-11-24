"""muscriptor2sky: 把 MIDI 转换成光遇（Sky）15 键琴谱，兼容 SkyStudio。"""

from .core import (
    BEAT_SUBDIVISION,
    DEGREE_NAMES,
    MAJOR_STEPS,
    NOTE_NAMES,
    Midi,
    Note,
    SkyNote,
    beat_to_ms,
    beat_unit_ms,
    build_keys,
    grid_compatible,
    grid_safe_bpm,
    key_id,
    midi_to_sky,
    read_midi,
    read_sky,
    skyr_parse,
    sky_to_midi,
    write_sky,
)

__version__ = "1.2.0"

__all__ = [
    "BEAT_SUBDIVISION",
    "DEGREE_NAMES",
    "MAJOR_STEPS",
    "NOTE_NAMES",
    "Midi",
    "Note",
    "SkyNote",
    "beat_to_ms",
    "beat_unit_ms",
    "build_keys",
    "grid_compatible",
    "grid_safe_bpm",
    "key_id",
    "midi_to_sky",
    "read_midi",
    "read_sky",
    "skyr_parse",
    "sky_to_midi",
    "write_sky",
    "__version__",
]
