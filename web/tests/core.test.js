'use strict';
/**
 * web/tests/core.test.js
 * ======================
 * sky-core.js 与 muscriptor2sky/core.py 的逐字节一致性验收。
 *
 * 契约见 web/API.md。夹具由 tools/gen_fixtures.py 用 Python 参考实现生成，
 * 是唯一真源 —— 这里只负责复现并比对，不手写任何期望值。
 *
 * 零依赖：只用 Node 内置的 node:test / node:assert / node:fs / node:crypto。
 *
 * 在仓库根目录跑：
 *     node --test web/tests/core.test.js
 *
 * ⚠️ 不要写成 `node --test web/tests/`（传目录）：Node 会把目录当模块
 * 去 require，直接报 MODULE_NOT_FOUND。必须显式给出测试文件。
 */

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

const REPO = path.resolve(__dirname, '..', '..');
const CORE_PATH = path.join(REPO, 'web', 'sky-core.js');
const FIXTURES_DIR = path.join(__dirname, 'fixtures');

// ---------------------------------------------------------------------------
// 加载被测实现
//
// sky-core.js 可能还没写完。这里不静默跳过 —— 加载失败时每个用例都会
// 以「无法加载 ...」失败，把问题明确暴露出来（不要为此放宽断言）。
// ---------------------------------------------------------------------------
let SkyCore = null;
let loadError = null;
try {
  SkyCore = require(CORE_PATH);
} catch (e) {
  loadError = e;
}

function core() {
  if (!SkyCore) {
    throw new Error(
      '无法加载 ' + CORE_PATH + '\n  ' + (loadError && loadError.message)
    );
  }
  return SkyCore;
}

/** 同一时间戳上最多几个键（复音数）。 */
function maxPoly(notes) {
  const byTime = new Map();
  for (const s of notes) {
    byTime.set(s.time, (byTime.get(s.time) || 0) + 1);
  }
  let m = 0;
  for (const v of byTime.values()) if (v > m) m = v;
  return m;
}

/** 每条 check 一句话说明，失败时直接用。 */
function checkLabel(chk) {
  switch (chk.kind) {
    case 'error': return '空输入应返回 notes=[] 且 info.error 存在';
    case 'transpose': return 'transpose == ' + chk.equals;
    case 'stat-min': return 'stat.' + chk.field + ' >= ' + chk.min;
    case 'stat-eq': return 'stat.' + chk.field + ' == ' + chk.equals;
    case 'bpm': return 'bpm == ' + chk.equals;
    case 'drums': return 'drums == ' + chk.equals;
    case 'pitch-level': return 'pitchLevel == ' + chk.equals;
    case 'melody-all-kept': return '主旋律 100% 保留';
    case 'max-poly-at-most': return '复音数 <= ' + chk.max;
    case 'max-poly-at-least': return '复音数 >= ' + chk.min;
    case 'keys-in-range': return '键位都在 0..14';
    case 'notes-at-least': return '音符数 >= ' + chk.min;
    case 'no-tempo-120': return '无 tempo 事件时 bpm == 120';
    case 'stat-eq-default': return 'stat 与 default 组一致';
    case 'size-ne': return '字节数与 default 组不同（opts 确实生效）';
    case 'mono': return '音符映射与 default 组一致';
    default: return chk.kind;
  }
}

/**
 * 复验夹具里记录的「设计意图」check。
 *
 * 这些 check 在 tools/gen_fixtures.py 生成夹具时已经用 Python 跑过一遍，
 * 这里在 JS 侧再验一次 —— 保证不只是字节对得上，行为语义也对得上
 * （比如 maxPoly 真的限了复音、主旋律真的一音没丢）。
 *
 * defaultRef 是同一夹具 default 组的 {size, stat, keys}，供跨组 check 使用。
 */
function runChecks(checks, notes, info, defaultRef, label, written) {
  const st = info.stat || {};
  const stat0 = (k) => (st[k] === undefined ? 0 : st[k]);

  for (const chk of checks) {
    const why = label + ' [' + checkLabel(chk) + ']';
    switch (chk.kind) {
      case 'error':
        assert.strictEqual(notes.length, 0, why + ': 期望 0 个音符，实际 ' + notes.length);
        assert.ok(info.error, why + ': info.error 必须存在');
        break;
      case 'transpose':
        assert.strictEqual(info.transpose, chk.equals,
          why + ': 实际 transpose=' + info.transpose);
        break;
      case 'stat-min':
        assert.ok(stat0(chk.field) >= chk.min,
          why + ': 实际 stat.' + chk.field + '=' + stat0(chk.field));
        break;
      case 'stat-eq':
        assert.strictEqual(stat0(chk.field), chk.equals,
          why + ': 实际 stat.' + chk.field + '=' + stat0(chk.field));
        break;
      case 'bpm':
        assert.ok(closeTo(info.bpm, chk.equals),
          why + ': 实际 bpm=' + info.bpm);
        break;
      case 'drums':
        assert.strictEqual(info.drums, chk.equals, why + ': 实际 drums=' + info.drums);
        break;
      case 'pitch-level':
        assert.strictEqual(info.pitchLevel, chk.equals,
          why + ': 实际 pitchLevel=' + info.pitchLevel);
        break;
      case 'melody-all-kept':
        assert.strictEqual(info.melody.kept, info.melody.total,
          why + ': 实际 ' + info.melody.kept + '/' + info.melody.total);
        break;
      case 'max-poly-at-most':
        assert.ok(maxPoly(notes) <= chk.max,
          why + ': 实际复音数 ' + maxPoly(notes));
        break;
      case 'max-poly-at-least':
        assert.ok(maxPoly(notes) >= chk.min,
          why + ': 实际复音数 ' + maxPoly(notes));
        break;
      case 'keys-in-range':
        for (const s of notes) {
          assert.ok(s.key >= 0 && s.key <= 14,
            why + ': 出现越界键位 ' + s.key);
        }
        break;
      case 'notes-at-least':
        assert.ok(notes.length >= chk.min,
          why + ': 实际 ' + notes.length + ' 个音符');
        break;
      case 'no-tempo-120':
        assert.ok(closeTo(info.bpm, 120),
          why + ': 实际 bpm=' + info.bpm);
        break;
      case 'stat-eq-default':
        assert.ok(defaultRef, why + ': 缺少 default 组参照');
        assertParity(st, defaultRef.stat, why);
        break;
      case 'size-ne': {
        assert.ok(defaultRef, why + ': 缺少 default 组参照');
        assert.ok(defaultRef.size > 0, why + ': default 组没有字节数可比');
        assert.ok(written && written.bytes, why + ': 需要本组 writeSky 的结果');
        assert.notStrictEqual(written.bytes.length, defaultRef.size,
          why + ': 本组字节数 ' + written.bytes.length +
          ' 与 default 组相同，说明这组 opts 根本没生效');
        break;
      }
      case 'mono':
        assert.ok(defaultRef, why + ': 缺少 default 组参照');
        assert.deepStrictEqual(
          notes.map((s) => [s.time, s.key]), defaultRef.keys, why);
        break;
      default:
        assert.fail(label + ': 夹具里出现未知 check ' + describe(chk));
    }
  }
}

// ---------------------------------------------------------------------------
// 比对工具
// ---------------------------------------------------------------------------

/** 浮点相对误差比较（默认 1e-12），NaN/Infinity 必须完全相等。 */
function closeTo(actual, expected, rel) {
  rel = rel === undefined ? 1e-12 : rel;
  if (typeof actual !== 'number' || typeof expected !== 'number') return false;
  if (Number.isNaN(actual) || Number.isNaN(expected)) return false;
  if (actual === expected) return true;
  if (!Number.isFinite(actual) || !Number.isFinite(expected)) return false;
  const diff = Math.abs(actual - expected);
  const scale = Math.max(Math.abs(actual), Math.abs(expected));
  return diff <= rel * scale;
}

function describe(v) {
  if (v === undefined) return 'undefined';
  try {
    return JSON.stringify(v);
  } catch (e) {
    return String(v);
  }
}

/** 递归比较：数字用 closeTo，其余严格相等。返回第一处差异的描述或 null。 */
function diffDeep(actual, expected, where) {
  where = where || '';
  if (expected === null || typeof expected !== 'object') {
    if (typeof expected === 'number') {
      if (!closeTo(actual, expected)) {
        return where + ': 期望 ' + expected + '，实际 ' + describe(actual);
      }
      return null;
    }
    if (actual !== expected) {
      return where + ': 期望 ' + describe(expected) + '，实际 ' + describe(actual);
    }
    return null;
  }
  if (Array.isArray(expected)) {
    if (!Array.isArray(actual)) {
      return where + ': 期望数组，实际 ' + describe(actual);
    }
    if (actual.length !== expected.length) {
      return where + ': 数组长度期望 ' + expected.length + '，实际 ' + actual.length;
    }
    for (let i = 0; i < expected.length; i++) {
      const d = diffDeep(actual[i], expected[i], where + '[' + i + ']');
      if (d) return d;
    }
    return null;
  }
  if (actual === null || typeof actual !== 'object') {
    return where + ': 期望对象，实际 ' + describe(actual);
  }
  const missing = [];
  for (const k of Object.keys(expected)) {
    if (!(k in actual)) missing.push(k);
  }
  if (missing.length) {
    return where + ': 缺少字段 ' + missing.join(', ') +
      '（实际字段: ' + Object.keys(actual).join(', ') + '）';
  }
  for (const k of Object.keys(expected)) {
    const d = diffDeep(actual[k], expected[k], where ? where + '.' + k : k);
    if (d) return d;
  }
  return null;
}

function assertParity(actual, expected, where) {
  const d = diffDeep(actual, expected, where);
  if (d) assert.fail(d);
}

function sha256(bytes) {
  return crypto.createHash('sha256').update(bytes).digest('hex');
}

function b64ToBytes(b64) {
  return new Uint8Array(Buffer.from(b64, 'base64'));
}

function hexHead(bytes, n) {
  const parts = [];
  for (let i = 0; i < Math.min(n, bytes.length); i++) {
    parts.push((bytes[i] < 16 ? '0' : '') + bytes[i].toString(16));
  }
  return parts.join(' ');
}

// ---------------------------------------------------------------------------
// 夹具加载
// ---------------------------------------------------------------------------

const FIXTURE_FILES = fs.existsSync(FIXTURES_DIR)
  ? fs.readdirSync(FIXTURES_DIR).filter((f) => f.endsWith('.json')).sort()
  : [];

function loadFixture(file) {
  const raw = fs.readFileSync(path.join(FIXTURES_DIR, file), 'utf8');
  return JSON.parse(raw);
}

if (!FIXTURE_FILES.length) {
  test('夹具目录必须存在且非空', () => {
    assert.fail(
      '没有在 ' + FIXTURES_DIR + ' 找到任何 .json 夹具。\n' +
      '请先在仓库根目录运行: python tools/gen_fixtures.py'
    );
  });
}

// ---------------------------------------------------------------------------
// 主验收：逐个夹具、逐个 case 做逐字节比对
// ---------------------------------------------------------------------------

/**
 * 算出同一夹具 default 组的参照摘要，供跨组 check（stat-eq-default /
 * size-ne / mono）使用。惰性求值并缓存，避免重复跑大用例。
 */
function defaultRefOf(fixture) {
  if (fixture._defaultRef !== undefined) return fixture._defaultRef;
  const S = core();
  const def = fixture.cases.find((c) => c.name === 'default');
  if (!def || def.error !== undefined) {
    fixture._defaultRef = null;
    return null;
  }
  const midi = S.readMidi(b64ToBytes(fixture.midiB64));
  const out = S.midiToSky(midi, def.opts || {});
  const written = S.writeSky(out.notes, def.opts || {}, out.info);
  fixture._defaultRef = {
    size: written.bytes.length,
    stat: out.info.stat || {},
    keys: out.notes.map((s) => [s.time, s.key]),
    noteCount: out.notes.length,
  };
  return fixture._defaultRef;
}

for (const file of FIXTURE_FILES) {
  const fixture = loadFixture(file);
  const slug = fixture.slug || path.basename(file, '.json');

  test('夹具完整性: ' + slug, () => {
    assert.ok(fixture.midiB64, slug + ' 缺少 midiB64');
    assert.ok(Array.isArray(fixture.cases) && fixture.cases.length > 0,
      slug + ' 的 cases 必须是非空数组');

    const midiBytes = b64ToBytes(fixture.midiB64);
    if (fixture.midiSha256) {
      assert.strictEqual(sha256(midiBytes), fixture.midiSha256,
        slug + ' 的 midiB64 解码后与 midiSha256 不一致（base64 内嵌被破坏）');
    }
    // 合法 MIDI 必须以 MThd 开头
    assert.strictEqual(
      String.fromCharCode(midiBytes[0], midiBytes[1], midiBytes[2], midiBytes[3]),
      'MThd', slug + ' 的 midiB64 不是标准 MIDI');
  });

  for (const c of fixture.cases) {
    const label = slug + ' / ' + c.name;

    test('逐字节对齐: ' + label, () => {
      const S = core();
      const midiBytes = b64ToBytes(fixture.midiB64);
      const midi = S.readMidi(midiBytes);
      assert.ok(midi && typeof midi === 'object', label + ': readMidi 必须返回对象');
      assert.strictEqual(midi.ppq, fixture.ppq, label + ': ppq 不一致');

      const out = S.midiToSky(midi, c.opts || {});
      assert.ok(out && typeof out === 'object', label + ': midiToSky 必须返回对象');
      const notes = out.notes;
      const info = out.info;
      assert.ok(Array.isArray(notes), label + ': notes 必须是数组');
      assert.ok(info && typeof info === 'object', label + ': info 必须是对象');

      // ---- 空输入分支：core.py 返回 ([], {"error": ...}) ----
      if (c.error !== undefined) {
        assert.strictEqual(notes.length, 0,
          label + ': 空 MIDI 应产出 0 个音符，实际 ' + notes.length);
        assert.strictEqual(info.error, c.error,
          label + ': info.error 期望 ' + describe(c.error) + '，实际 ' + describe(info.error));
        return;
      }

      assert.ok(c.sha256, label + ': 夹具缺少 sha256');

      // ---- info 摘要逐字段比对（浮点用 1e-12 相对误差）----
      //
      // web/API.md 的 Info 结构里没有 noteCount（它是本测试自己加的便利字段），
      // 所以实现方不返回它也合法；此时用 notes.length 补上再比。
      const actualInfo = Object.assign({}, info);
      if (actualInfo.noteCount === undefined) actualInfo.noteCount = notes.length;
      assertParity(actualInfo, c.info, label + ' info');

      // noteCount 无论实现方是否返回，都必须等于实际音符数
      assert.strictEqual(notes.length, c.info.noteCount,
        label + ': 音符数期望 ' + c.info.noteCount + '，实际 ' + notes.length);

      // ---- writeSky -> 完整字节 ----
      const written = S.writeSky(notes, c.opts || {}, info);
      assert.ok(written && written.bytes, label + ': writeSky 必须返回 {bytes, text}');
      const bytes = written.bytes;
      assert.ok(bytes instanceof Uint8Array, label + ': writeSky.bytes 必须是 Uint8Array');

      assert.strictEqual(bytes.length, c.size,
        label + ': 字节数期望 ' + c.size + '，实际 ' + bytes.length +
        '（前 16 字节: ' + hexHead(bytes, 16) + '）');
      assert.strictEqual(sha256(bytes), c.sha256,
        label + ': sha256 不一致\n  期望 ' + c.sha256 + '\n  实际 ' + sha256(bytes) +
        '\n  前 16 字节: ' + hexHead(bytes, 16));

      // ---- 完整文本（只有极小用例存了）----
      if (c.expectText !== undefined) {
        assert.strictEqual(typeof written.text, 'string',
          label + ': writeSky.text 必须是字符串');
        if (written.text !== c.expectText) {
          // 给出第一处差异的位置，方便定位
          let i = 0;
          const n = Math.min(written.text.length, c.expectText.length);
          while (i < n && written.text[i] === c.expectText[i]) i++;
          assert.fail(
            label + ': text 与期望不一致（第 ' + i + ' 个字符起）\n' +
            '  期望 ...' + c.expectText.slice(Math.max(0, i - 30), i + 60) + '\n' +
            '  实际 ...' + written.text.slice(Math.max(0, i - 30), i + 60)
          );
        }
      }
    });

    // ---- 设计意图 check（gen_fixtures.py 生成时已用 Python 验过一遍）----
    if (Array.isArray(c.checks) && c.checks.length) {
      test('设计意图: ' + label, () => {
        const S = core();
        const midi = S.readMidi(b64ToBytes(fixture.midiB64));
        const out = S.midiToSky(midi, c.opts || {});
        // 空输入没有谱面可写；其余组先写出字节，size-ne 要用
        const written = out.notes.length
          ? S.writeSky(out.notes, c.opts || {}, out.info)
          : null;
        runChecks(c.checks, out.notes, out.info, defaultRefOf(fixture), label, written);
      });
    }
  }
}

// ---------------------------------------------------------------------------
// 额外单测（不依赖夹具）
// ---------------------------------------------------------------------------

/**
 * 取 pyRound。
 *
 * web/API.md 的导出表里没有它（它是内部工具函数），但「半值行为」是
 * 逐字节一致性的根因之一，必须单独验。所以优先用导出的 pyRound；
 * 没导出就从 sky-core.js 源码里把函数体捞出来 —— 两种情况都测同一份逻辑，
 * 绝不会因为「没导出」就把这条测试悄悄跳过。
 */
function getPyRound() {
  const S = core();
  if (typeof S.pyRound === 'function') return S.pyRound;

  const src = fs.readFileSync(CORE_PATH, 'utf8');
  const m = /function\s+pyRound\s*\(([^)]*)\)\s*\{/.exec(src);
  assert.ok(m, 'sky-core.js 里既没有导出 pyRound，也找不到 function pyRound(...) 定义；' +
    '逐字节对齐依赖它，请按 web/API.md「坑 1」实现');
  // 从函数头开始做花括号配平，抠出完整函数体
  let i = src.indexOf('{', m.index + m[0].length - 1);
  let depth = 0;
  let end = -1;
  for (let j = i; j < src.length; j++) {
    const ch = src[j];
    if (ch === '{') depth++;
    else if (ch === '}') {
      depth--;
      if (depth === 0) { end = j + 1; break; }
    }
  }
  assert.ok(end > 0, '无法从 sky-core.js 源码里完整抠出 pyRound 的函数体');
  const body = src.slice(m.index, end);
  // eslint-disable-next-line no-new-func
  const fn = new Function('return (' + body + ')')();
  assert.strictEqual(typeof fn, 'function', '从源码抠出的 pyRound 不是函数');
  return fn;
}

test('pyRound: 半值必须四舍六入五成双', () => {
  const pyRound = getPyRound();
  // Python round() 是 half-to-even，Math.round() 是 half-up，这里必须不同
  assert.strictEqual(pyRound(0.5), 0, 'pyRound(0.5) 应为 0（half-even）');
  assert.strictEqual(pyRound(1.5), 2, 'pyRound(1.5) 应为 2');
  assert.strictEqual(pyRound(2.5), 2, 'pyRound(2.5) 应为 2（half-even）');
  assert.strictEqual(pyRound(-0.5), 0, 'pyRound(-0.5) 应为 0（half-even）');
  assert.strictEqual(pyRound(-2.5), -2, 'pyRound(-2.5) 应为 -2（half-even）');
  // 非半值方向必须与 Math.round 一致
  assert.strictEqual(pyRound(0.4), 0);
  assert.strictEqual(pyRound(0.6), 1);
  assert.strictEqual(pyRound(-0.6), -1);
  assert.strictEqual(pyRound(2.4), 2);
  assert.strictEqual(pyRound(2.6), 3);
  assert.strictEqual(pyRound(0), 0);
});

test('utf-16 输出必须是 UTF-16LE + BOM，长度 == 2 + text.length*2', () => {
  const S = core();
  const fixture = loadFixture('c-major-simple.json');
  const midi = S.readMidi(b64ToBytes(fixture.midiB64));
  const opts = { name: '编码测试', encoding: 'utf-16' };
  const out = S.midiToSky(midi, opts);
  const written = S.writeSky(out.notes, opts, out.info);

  const bytes = written.bytes;
  assert.strictEqual(bytes[0], 0xFF, '第 0 字节必须是 0xFF（BOM 高字节）');
  assert.strictEqual(bytes[1], 0xFE, '第 1 字节必须是 0xFE（BOM 低字节）');
  assert.strictEqual(bytes.length, 2 + written.text.length * 2,
    'UTF-16LE 字节数必须等于 2 + text.length*2（每个码元 2 字节）');

  // 逐码元复核：不能是 UTF-16BE，也不能有结尾 NUL
  for (let i = 0; i < written.text.length; i++) {
    const c = written.text.charCodeAt(i);
    assert.strictEqual(bytes[2 + i * 2], c & 0xFF, '第 ' + i + ' 个码元的低字节不对');
    assert.strictEqual(bytes[3 + i * 2], (c >> 8) & 0xFF, '第 ' + i + ' 个码元的高字节不对');
  }

  // 中文曲名必须能被 UTF-16LE 正确解回（BMP 之外的字也不能错）
  const decoded = Buffer.from(bytes.slice(2)).toString('utf16le');
  assert.strictEqual(decoded, written.text, 'UTF-16LE 解码结果必须与 text 完全一致');
});

test('bpm 是整数时 JSON 文本里必须写 "300.0" 而不是 "300"', () => {
  const S = core();
  const fixture = loadFixture('c-major-simple.json');
  const midi = S.readMidi(b64ToBytes(fixture.midiB64));
  const opts = { name: 'bpm300', bpm: 300 };
  const out = S.midiToSky(midi, opts);
  assert.strictEqual(out.info.bpm, 300,
    'bpm=300 时 info.bpm 应为 300，实际 ' + out.info.bpm);

  const written = S.writeSky(out.notes, opts, out.info);
  assert.ok(written.text.indexOf('"bpm":300.0') >= 0,
    'JSON 文本里必须出现 "bpm":300.0（Python json.dumps(300.0) 行为），' +
    '实际片段: ' + written.text.slice(0, 200));
  assert.strictEqual(written.text.indexOf('"bpm":300,'), -1,
    'JSON 文本里不能出现 "bpm":300（会与 Python 输出差一个字节）');
});

test('readSky 能读回 writeSky 的输出，音符数一致', () => {
  const S = core();
  const fixture = loadFixture('poly-chords.json');
  const midi = S.readMidi(b64ToBytes(fixture.midiB64));
  const opts = { name: '回环测试', author: 'eeesssr' };
  const out = S.midiToSky(midi, opts);
  assert.ok(out.notes.length > 0, 'poly-chords 应产出音符');

  const written = S.writeSky(out.notes, opts, out.info);

  // 先确认文本本身能被 JSON.parse（结构合法）
  const parsed = JSON.parse(written.text);
  assert.ok(Array.isArray(parsed) && parsed.length === 1, '顶层必须是一个元素的 JSON 数组');
  assert.strictEqual(parsed[0].name, '回环测试');
  assert.strictEqual(parsed[0].author, 'eeesssr');
  assert.strictEqual(parsed[0].songNotes.length, out.notes.length,
    'songNotes 数量必须等于 SkyNote 数量');

  const songs = S.readSky(written.bytes);
  assert.ok(Array.isArray(songs) && songs.length === 1,
    'readSky 必须返回长度 1 的 Song 数组');
  assert.strictEqual(songs[0].notes.length, out.notes.length,
    'readSky 读回的音符数必须与写出的音符数一致');
  assert.strictEqual(songs[0].name, '回环测试');
  assert.strictEqual(songs[0].author, 'eeesssr');

  // 每个 note 必须是 [ms, layer, idx]，且 idx 在 15 键范围内
  for (const n of songs[0].notes) {
    assert.ok(Array.isArray(n) && n.length === 3, 'Song.notes 元素必须是 [ms, layer, idx]');
    assert.ok(n[0] >= 0, 'ms 不能为负');
    assert.ok(n[2] >= 0 && n[2] <= 14, '键位必须在 0..14，实际 ' + n[2]);
  }

  // utf-8 编码同样要能读回
  const optsUtf8 = { name: '回环测试', encoding: 'utf-8' };
  const outUtf8 = S.midiToSky(midi, optsUtf8);
  const writtenUtf8 = S.writeSky(outUtf8.notes, optsUtf8, outUtf8.info);
  assert.strictEqual(writtenUtf8.bytes[0], 0x5B,
    'utf-8 输出不应带 BOM，首字节应是 "[" (0x5B)');
  const songsUtf8 = S.readSky(writtenUtf8.bytes);
  assert.strictEqual(songsUtf8[0].notes.length, outUtf8.notes.length);
});

test('skyToMidi 产出的字节以 "MThd" 开头', () => {
  const S = core();
  const fixture = loadFixture('c-major-simple.json');
  const midi = S.readMidi(b64ToBytes(fixture.midiB64));
  const opts = { name: '反向测试' };
  const out = S.midiToSky(midi, opts);
  const written = S.writeSky(out.notes, opts, out.info);

  const songs = S.readSky(written.bytes);
  const midiBytes = S.skyToMidi(songs, { ppq: 480, noteLen: 0.25 });
  assert.ok(midiBytes instanceof Uint8Array, 'skyToMidi 必须返回 Uint8Array');
  assert.ok(midiBytes.length > 14, 'skyToMidi 输出太短: ' + midiBytes.length);
  assert.strictEqual(
    String.fromCharCode(midiBytes[0], midiBytes[1], midiBytes[2], midiBytes[3]),
    'MThd', 'skyToMidi 输出必须以 MThd 开头，实际: ' + hexHead(midiBytes, 8));

  // 反向产出的 MIDI 必须能被自己重新解析
  const reparsed = S.readMidi(midiBytes);
  assert.strictEqual(reparsed.ppq, 480);
  assert.strictEqual(reparsed.notes.length, out.notes.length,
    '反向 MIDI 的音符数应与原谱面一致');
});

test('DEFAULTS 必须与 web/API.md 的参数表一致', () => {
  const D = core().DEFAULTS;
  assert.ok(D && typeof D === 'object', 'sky-core.js 必须导出 DEFAULTS');
  assert.strictEqual(D.bitsPerPage, 16);
  assert.strictEqual(D.pitchLevel, 0);
  assert.strictEqual(D.virtualNotes, false);
  assert.strictEqual(D.encoding, 'utf-16');
  assert.strictEqual(D.root, 60);
  assert.strictEqual(D.transpose, 'auto');
  assert.strictEqual(D.grid, 0.25);
  assert.strictEqual(D.maxPoly, 0);
  assert.strictEqual(D.ppq, 480);
  assert.strictEqual(D.noteLen, 0.25);
  assert.strictEqual(D.bpm, null);
  assert.strictEqual(D.name, null);
  assert.strictEqual(D.author, null);
});

test('VERSION 与 Python 包版本一致', () => {
  const v = core().VERSION;
  assert.strictEqual(typeof v, 'string', 'sky-core.js 必须导出 VERSION 字符串');
  const pyproject = fs.readFileSync(path.join(REPO, 'pyproject.toml'), 'utf8');
  const m = /^version\s*=\s*"([^"]+)"/m.exec(pyproject);
  assert.ok(m, '无法从 pyproject.toml 读出 version');
  assert.strictEqual(v, m[1], 'VERSION 应与 pyproject.toml 的 version 一致');
});
