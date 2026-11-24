# -*- coding: utf-8 -*-
"""零依赖测试运行器：没有 pytest 也能跑全部用例。

支持 pytest 的一个子集：
  - test_* 函数
  - fixture: tmp_path
  - pytest.raises 上下文
  - assert 断言

用法：python run_tests.py
"""

import importlib.util
import os
import sys
import tempfile
import traceback
import types
import shutil


class _Raises:
    def __init__(self, exc):
        self.exc = exc
        self.value = None

    def __enter__(self):
        return self

    def __exit__(self, et, ev, tb):
        if et is None:
            raise AssertionError("期望抛出 %s，但没有异常" % self.exc.__name__)
        if not issubclass(et, self.exc):
            return False
        self.value = ev
        return True


# 造一个最小可用的假 pytest 模块
fake = types.ModuleType("pytest")
fake.raises = lambda exc: _Raises(exc)
sys.modules["pytest"] = fake


_counter = 0


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_file(path):
    name = os.path.splitext(os.path.basename(path))[0]
    mod = load_module(path, name)
    passed = failed = 0
    failures = []
    for attr in sorted(dir(mod)):
        if not attr.startswith("test_"):
            continue
        fn = getattr(mod, attr)
        if not callable(fn):
            continue
        global _counter
        _counter += 1
        tmp = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".testtmp", "t%03d" % _counter)
        os.makedirs(tmp, exist_ok=True)
        try:
            import inspect
            params = inspect.signature(fn).parameters
            if "tmp_path" in params:
                fn(tmp_path=__import__("pathlib").Path(tmp))
            else:
                fn()
            passed += 1
            print("  PASS  %s.%s" % (name, attr))
        except Exception:
            failed += 1
            failures.append((name, attr, traceback.format_exc()))
            print("  FAIL  %s.%s" % (name, attr))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return passed, failed, failures


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(os.path.join(here, ".testtmp"), exist_ok=True)
    tests_dir = os.path.join(here, "muscriptor2sky", "tests")
    files = sorted(
        os.path.join(tests_dir, f)
        for f in os.listdir(tests_dir)
        if f.startswith("test_") and f.endswith(".py")
    )
    if not files:
        print("没有找到测试文件")
        return 1

    sys.path.insert(0, here)
    total_p = total_f = 0
    all_failures = []
    for f in files:
        print("[%s]" % os.path.basename(f))
        p, fl, failures = run_file(f)
        total_p += p
        total_f += fl
        all_failures.extend(failures)
        print()

    print("=" * 60)
    print("通过 %d / 失败 %d" % (total_p, total_f))
    if all_failures:
        print()
        for name, attr, tb in all_failures:
            print("-" * 60)
            print("FAILED %s.%s" % (name, attr))
            print(tb)
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
