# -*- coding: utf-8 -*-
"""音高映射与键位约定的单元测试。"""

import pytest

from muscriptor2sky.core import (
    DEGREE_NAMES,
    build_keys,
    key_id,
    skyr_parse,
)


def test_build_keys_default_range():
    """默认 15 键必须是 C4(60) ~ C6(84)。"""
    keys = build_keys()
    assert len(keys) == 15
    assert keys[0] == 60
    assert keys[-1] == 84


def test_build_keys_is_c_major():
    """15 个键全部落在 C 大调白键上，且顺序递增。"""
    keys = build_keys()
    pcs = {k % 12 for k in keys}
    assert pcs == {0, 2, 4, 5, 7, 9, 11}
    assert keys == sorted(keys)


def test_degree_names_match_15_keys():
    """简谱名与键位一一对应：1..7, 1'..7', 1''。"""
    assert len(DEGREE_NAMES) == 15
    assert DEGREE_NAMES[0] == "1"
    assert DEGREE_NAMES[6] == "7"
    assert DEGREE_NAMES[7] == "1'"
    assert DEGREE_NAMES[13] == "7'"
    assert DEGREE_NAMES[14] == "1''"


def test_key_id_is_zero_based():
    """键名是 0 基：第一键是 1Key0，最后一键是 1Key14。

    这是最容易搞错的地方——SkyStudio 谱面规范里 key 是 0 基索引，
    没有 +1 偏移，第一键就是 1Key0。
    """
    assert key_id(0) == "1Key0"
    assert key_id(14) == "1Key14"
    assert key_id(7) == "1Key7"


def test_build_keys_custom_root():
    """--root 可以整体挪动音域。"""
    keys = build_keys(root=57, count=15)
    assert keys[0] == 57
    assert keys[-1] == 81
