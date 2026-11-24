# muscriptor2sky

**MIDI → 光遇 15 键琴谱** 转换器，输出 **SkyStudio 兼容**的 `.txt` 格式，也能反向把琴谱还原成 MIDI。

接受任何标准 MIDI：DAW 导出的工程、手写谱、[MuScriptor](https://huggingface.co/MuScriptor/muscriptor-small)/MT3 等音频转谱模型的输出都可以。生成的谱子能被 SkyStudio 及一系列兼容它的光遇弹琴工具直接读取播放。

- **兼容 SkyStudio**：按 SkyStudio 的琴谱规范输出（UTF-16LE + BOM 的 JSON），这是光遇谱面的事实标准
- **零依赖**：只用 Python 标准库，不需要 `pip install` 任何东西
- **自动移调**：把原曲移到 C 大调，让最多音符正好落在 15 个白键上
- **黑键智能吸附**：就近吸附，平局时按和声与旋律走向决定
- **自带校验**：`--verify` 按 SkyStudio 格式规范回读自检，确保 APP 能播
- **双向转换**：琴谱也能转回 MIDI，方便核对别人的谱子

---

## 安装

需要 **Python 3.8+**。克隆后即可使用，无需安装依赖：

```bash
git clone https://github.com/eeesssr/muscriptor2sky.git
cd muscriptor2sky
```

也可以装成命令行工具：

```bash
pip install -e .
muscriptor2sky --help
```

---

## 快速开始

### 命令行

```bash
# 最简：同目录生成同名 .txt
python -m muscriptor2sky song.mid

# 推荐：带曲名作者 + 自检
python -m muscriptor2sky song.mid -n "晴天" -a "周杰伦" --verify
```

### Windows 拖拽

把 `.mid` 文件拖到对应的 `.bat` 上松手即可。仓库提供三个，对应三种输出模式：

| 文件 | 输出 | 需要花货币 | 推荐度 |
|---|---|---|---|
| `转换-C调默认.bat` | `pitchLevel = 0`，游戏默认 C 调 | 不需要 | ⭐ 默认用这个 |
| `转换-定调版.bat` | 交互式选 `pitchLevel = 0~11` | **需要** | 乐器已调在别的调时用 |
| `转换-虚音版.bat` | 用两键凑差音代替黑键（实验性） | 不需要 | 仅作研究，见[虚音说明](docs/虚音说明.md) |

三个模式共用一个核心，差别只在输出头部的 `pitchLevel` 是否改动、以及是否补虚音键。
详见 [定调与 pitchLevel](docs/定调与pitchLevel.md)。

### Python API

```python
import types
from muscriptor2sky.core import read_midi, midi_to_sky, write_sky

args = types.SimpleNamespace(
    root=60, transpose="auto", grid=0.25, max_poly=0,
    name="晴天", author="", arranged=None, transcribed=None,
    bpm=None, bits_per_page=16, pitch_level=0, encoding="utf-16",
)

m = read_midi("song.mid")
notes, info = midi_to_sky(m, args)
write_sky("song.txt", notes, args, info)
print(info["stat"])   # {'exact': .., 'octave': .., 'snapped': .., 'merged': .., 'dropped': ..}
```

---

## 15 键与简谱对照

光遇的键名是 **0 基**编号，这一点最容易搞错：

| 文件里的 key | 键位 | 简谱 |
|---|---|---|
| `1Key0` … `1Key6` | 1–7 | `1 2 3 4 5 6 7` |
| `1Key7` … `1Key13` | 8–14 | `1' 2' 3' 4' 5' 6' 7'` |
| `1Key14` | 15 | `1''` |

对应 MIDI 音高：C4(60) D4 E4 F4 G4 A4 B4 · C5 D5 E5 F5 G5 A5 B5 · C6(84)。

> **键名约定依据 SkyStudio 谱面规范**：key 的数字部分是 **0 基**键位索引，
> 没有 `+1` 偏移，所以第一键是 `1Key0` 而不是 `1Key1`。
> 形如 `1Key5` / `2Key5` 的前缀数字不参与音高计算，两种写法指向同一个键。

---

## 输出字段解读

运行后打印的统计：

```
输入: song.mid
音域: 15 键 C 大调 C(60) ~ C(84)
移调: -2 半音   bpm: 120   源音符: 34   鼓(丢弃): 16
映射: 精确 14 / 八度折叠 12 / 半音吸附 6 / 同键合并 2 / 超复音丢弃 0
输出音符: 32
[格式自检] 编码 UTF-16LE(BOM) | 音符 32 | 事件 14 | 最大复音 5 | 时长 7.5s
[格式自检] 通过，可直接被 APP 播放
```

| 字段 | 含义 | 怎样算好 |
|---|---|---|
| 移调 | 整体升降半音数 | 正常 −6~+6，太大说明原曲调性远 |
| 精确 | 音高正好落在白键 | 越高越好 |
| 八度折叠 | 超音域，移动了八度 | 少量正常 |
| 半音吸附 | 黑键吸到最近白键 | 越少越好，多了旋律会走样 |
| 同键合并 | 两音抢同一键，丢一个 | 少量正常 |
| 最大复音 | 同时按几个键 | **>4 手弹不了** |

---

## 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `-o, --out` | 同名 .txt | 输出路径 |
| `-n, --name` | MIDI 文件名 | 曲名 |
| `-a, --author` | 空 | 作者 |
| `--arranged` / `--transcribed` | 空 | arrangedBy / transcribedBy 字段 |
| `--bpm` | MIDI 速度 | 只影响 SkyStudio 编辑器格子显示，不影响播放 |
| `--bits-per-page` | 16 | SkyStudio 分页 |
| `--pitch-level` | 0 | 谱面八度显示偏移 |
| `--encoding` | `utf-16` | `utf-16`（标准）或 `utf-8` |
| `--root` | 60 (C4) | 15 键里最低键的 MIDI 音高 |
| `--transpose` | `auto` | `auto` 自动移调 / `none` 保持原调 |
| `--grid` | 0.25 | 量化网格（拍），0 关闭 |
| `--max-poly` | 0 | 同时发音上限，0 不限 |
| `--verify` | 关 | 按 SkyStudio 谱面规范回读自检 |
| `--no-preview` | 关 | 不打印简谱预览 |

### 常用组合

```bash
# 手指弹不动的密集钢琴曲 → 限制复音
python -m muscriptor2sky song.mid --max-poly 3

# 只要主旋律，最容易弹
python -m muscriptor2sky song.mid --max-poly 1

# 有十六分音符，需要更细网格
python -m muscriptor2sky song.mid --grid 0.125

# 完全保留原始时间，不量化
python -m muscriptor2sky song.mid --grid 0

# 保持原调不移调
python -m muscriptor2sky song.mid --transpose none

# 换音域（从 A3 开始，共 15 键）
python -m muscriptor2sky song.mid --root 57
```

---

## 反向转换：琴谱 → MIDI

用来核对别人的谱子，或把琴谱转成能听的 MIDI：

```bash
python -m muscriptor2sky "晴天.txt" -o 晴天.mid
```

---

## 完整工作流：音频 → 琴谱

```bash
# 1) 用 MuScriptor 把音频转成 MIDI
#    关键：用 --instruments 只要钢琴轨，比事后删音干净得多
muscriptor transcribe --model medium --instruments "acoustic_piano" audio.wav -o piano.mid

# 2) 转成光遇琴谱
python -m muscriptor2sky piano.mid -n "曲名" -a "作者" --verify

# 3) 把 .txt 放到手机
#    Android: /sdcard/skyMusicAuto/   或用 APP 的文件选择器导入
```

MuScriptor 默认按**音色分组**分轨（每个 detected program 一轨，鼓单独一轨在 channel 9），
并不按"旋律/和弦/贝斯"分声部。转谱阶段用 `--instruments` 限定是最省事的做法。

---

## 批量转换

```bash
# PowerShell
Get-ChildItem *.mid | ForEach-Object {
    python -m muscriptor2sky $_.FullName --verify --no-preview
}

# bash
for f in *.mid; do python -m muscriptor2sky "$f" --verify --no-preview; done
```

---

## 示例

[`examples/flower-dance/`](examples/flower-dance/) 提供了一份完整样例：

| 文件 | 说明 |
|---|---|
| `input.mid` | MuScriptor 输出的原始 MIDI（27 KB，多轨含打击乐） |
| `output.txt` | 转换出的光遇琴谱（约 135 KB，2250 个音符） |
| `README.md` | 转换结果说明与网格验证方法 |

```bash
python -m muscriptor2sky examples/flower-dance/input.mid \
    -o out.txt -n "DJ OKAWARI - Flower Dance" --verify
```

可以直接用它验证工具在你机器上的行为是否符合预期：

```
移调: +1 半音   bpm: 319   源音符: 2584   鼓(丢弃): 945
映射: 精确 1568 / 八度折叠 629 / 半音吸附 53 / 同键合并 334 / 超复音丢弃 0
输出音符: 2250
定调: pitchLevel = 0（游戏默认 C 调，无需额外兑换）
[可弹性] 旋律可用 15 键弹奏的比例 97.9%
时间网格: 单位 1 拍 = 188 ms  [SkyStudio 兼容]
```

> 该目录仅用于验证格式转换，原曲版权归原作者所有。

---

## 工作原理

```
读取 MIDI（丢弃 channel 9 打击乐）
  ↓
取旋律声部（每个起始点的最高音）
  ↓
选移调量：在 ±18 半音（3 个八度）内搜索，按「转换后实际被改动的音符比例」打分
  ↓
超音域的音做八度折叠（只改八度，不改音名）
  ↓
黑键吸附最近白键（平局按和声协和度 → 旋律走向决定）
  ↓
同时刻同键合并（保留时值更长的）
  ↓
按 --grid 量化时间
  ↓
写 UTF-16LE+BOM 的 JSON
```

### 为什么移调要搜到 ±3 个八度

这是踩过的一个大坑，也是「转出来旋律丢了」的根因。

15 键只有 C4~C6 一个八度多一点。一首钢琴曲的旋律往往横跨 4 个八度，
注定有一部分音要八度折叠。**折叠本身不可怕，可怕的是折叠发生在旋律中段。**

如果整体移调选得偏高，旋律下半段还在键上、上半段全被折回低音区，
那条旋律线就会在中间被拦腰截断，听感就是「旋律没了」。

正确做法是**把整条旋律尽量整体放进 C4~C6**，只在真的放不下时才折叠
（也就是只在旋律两端折，不在中间折）。这靠的是移调量里那个 12 的倍数，
而这恰恰要求搜索范围能跨越八度。

旧实现把搜索范围写死成 `[-6, +6]`，根本表达不了「整体挪一个八度」，
于是只能靠音级统计挑一个「白键命中率高」的值，结果把大量音符挤出音域、
再逐个折叠。修复前后的实测对比（5 份真实 MuScriptor MIDI）：

| 指标 | 修复前 | 修复后 |
|---|---|---|
| 旋律音完全正确 | 74.4% | **82.0%** |
| 八度缠绕（音对但音区错） | 16.8% | **9.0%** |
| 音级被改（弹错音） | 8.8% | 9.0% |

在 178 份社区谱面（[SkyAutoPlayerScript](https://github.com/StageGuard/SkyAutoPlayerScript)
的 shared_sheets，随机移到别的调后再转回 C 调）上的回环还原率：
旧实现 96.1%，新实现 **99.89%**。

另外，**不要用 SkyStudio 的 `pitchLevel` 来「修」音域**。

游戏内乐器默认就是 **C 调**，而我们的 15 键铺的正是 C 大调 C4~C6——两者天然对齐。
`pitchLevel` 是游戏侧的定调提示，换算要花货币；我们统计了 178 份谱面，
它从 0 到 11 都用过，**但键位分布与音域分布都没跟着变**
（`pitchLevel` 与实际音域的相关系数在 +0.04 左右，接近于零）。

也就是说：**谱面本身已经是 C 大调，游戏默认也是 C，再调只会多此一举。**
所以输出固定 `pitchLevel = 0`，把所有音塞进最初的 15 个键里。

### 为什么黑键要统一吸附方向

15 键琴只有白键，遇到黑键音必须改成相邻白键。改成哪边？这里有两个选择：

- **逐音决定**：旋律上行就向上取，下行就向下取。单看一个音最贴近原音高。
- **全局统一**：每个黑键音级固定朝一个方向。

旧实现用的是第一种，会导致一个隐蔽但很伤听感的问题：**同一个音级在曲子里会落到不同的白键上**。

实测星降る海，C# 分别被映射到了 G、A、B 三个白键：

| | 源音级 | 输出白键 |
|---|---|---|
| 修复前 | C# | G / A / B（3 个） |
| 修复后 | C# | 固定 1 个 |

同一句旋律重奏时音名变了，听感就是「跑调」「变色」。这就是用户说的「像是音都不是那个音」。

现在改成全局统一：穷举 2⁵ = 32 种「每个黑键朝哪边」的组合，选音级轮廓最吻合的一组。
有趣的是，5 份真实 MIDI 和 178 份社区谱面**都独立收敛到同一个答案：全部向上取**。

顺带修了另一个 bug：旧实现从整个 15 键里挑「最协和」的白键，
`bass_pc` 一变就可能把 C#4(61) 吸到 E4(64)——跨过整个 D4，音级直接被改掉。
现在吸附候选限定为**最近的上下两个白键**。

### 输出格式

```json
[{
  "name": "晴天",
  "author": "周杰伦",
  "arrangedBy": "",
  "transcribedBy": "MuScriptor",
  "permission": "",
  "isComposed": true,
  "bpm": 300,
  "bitsPerPage": 16,
  "pitchLevel": 0,
  "isEncrypted": false,
  "songNotes": [
    {"time": 400, "key": "1Key5"},
    {"time": 800, "key": "1Key7"}
  ]
}]
```

- 文件编码：**UTF-16LE + BOM**（SkyStudio 谱面规范，播放器靠 BOM 判定编码）
- `time` 是**毫秒绝对时间戳**，播放器用相邻音符差值作为延时
- 同一 `time` 出现多个 key = 和弦同时按下

---

## 开发

```bash
# 跑测试（零依赖运行器，不需要 pytest）
python run_tests.py

# 或者用 pytest
pip install pytest && pytest
```

测试覆盖：音高映射、键位 0 基约定、MIDI 解析（含 program change 单字节陷阱、
鼓轨过滤）、黑键吸附、复音限制、同键合并、UTF-16 编码、往返一致性。

---

## 常见问题

**Q: 播放出来整体低了一个音级？**
键名是 **0 基**，第一键是 `1Key0`。如果你手写琴谱用了 `1Key1` 开头，就会整体偏移。

**Q: skyR 能播，但 SkyStudio 报错 / 播放速度不对 / 音不对？**

这是 **SkyStudio 时间模型**的问题，不是编码也不是音高映射（v1.2 已修复）。

SkyStudio 读谱面后这样算每个音的播放延时：

```js
// 来源：SkyStudio 生态的开源实现 buildTimingModel / 播放循环
unit      = gcd(所有相邻 time 的间隔);   // 时间单位
sleepUnit = duration / unit;
实际延时   = sleepUnit * (60000 / bpm);   // 注意这里又乘了 bpm

// 代入：实际延时 = (duration / unit) * (60000 / bpm)
```

要让实际延时等于 duration（即**播放速度和原曲一致**），必须满足：

```
gcd(times) == 60000 / bpm        ← 铁律
```

两个推论，正好对应两种症状：

| 情况 | 结果 |
|---|---|
| gcd 退化成 1ms（bpm 除不尽，量化抖动） | SkyStudio **无法建立节拍网格 → 报错** |
| gcd != 60000/bpm（差 2/4 倍等） | **播放速度整体快慢若干倍** |

以 `bpm=117` 为例：一拍 512.8205ms，八分音符 256.41ms 取整后
256/257 交替，gcd 退化成 1ms。此时 skyR 按毫秒差直接计时，一切正常；
SkyStudio 则报错或变速——这就是「skyR 能播、SkyStudio 不行」的根源。

**修复方式（v1.2）**：

1. 把 bpm 归一到能整除 60000 的值（`grid_safe_bpm`），保证 `60000/bpm` 是整数毫秒；
2. 找出原曲最细音符，令 `cell = 该音符毫秒数`，把 bpm 设为 `60000/cell`；
3. 所有 `time` 都取 `cell` 的整数倍，并做**后验校准**：
   实测输出时间戳的 gcd，若与 `cell` 不等，就用 gcd 反推 bpm。

这样 `gcd(times) == 60000/bpm` 恒成立，速度和音高都正确。

CLI 会直接显示网格状态：

```
时间网格: 单位 1 拍 = 128 ms  [SkyStudio 兼容]
```

> **注意**：为了满足上面的等式，工具可能会把 bpm 改成 468、1760 这类值。
> 这是正常的——SkyStudio 的 bpm 同时充当「网格分辨率」，不等于原曲速度
> 才有问题。实际播放速度由 time 与 bpm 共同决定，两者已经对齐。

**Q: APP 显示"乐谱格式不受支持"（编码问题）？**
如果不是上面那种情况，就检查编码。用 `--verify` 让工具自检，不要手动改 txt 编码。

**Q: 旋律跑调明显？**

先看输出里的一行统计：

```
映射: 精确 N / 八度折叠 N / 半音吸附 N / 同键合并 N / 超复音丢弃 N
```

判断标准（v1.3 实测口径）：

| 现象 | 说明 | 怎么办 |
|---|---|---|
| 「半音吸附」占比高 | 原曲大量用黑键（半音化程度高），15 键琴**物理上弹不出来** | 见下方「乐器上限」 |
| 「八度折叠」占比高 | 旋律音域远超 C4~C6 | 通常已由自动移调优化；仍高说明旋律本身跨 4 个八度 |
| 两者都低但听着不对 | 多半是复音过密或节奏太碎 | 试 `--max-poly 3` 或 `--grid 0.125` |

**关于「乐器上限」（重要）**：光遇 15 键琴是 **C 大调纯白键**乐器。
任何旋律里只要出现黑键音（钢琴上的黑键），就必然被改成相邻白键，
这是乐器的固有限制，不是转换错误。

我们实测过一首半音化很重的曲子（Relaxu - 星降る海），它最好的 7 音自然音阶
只能覆盖 **68.3%** 的旋律音 —— 剩下 31.7% 无论怎么移调都避不开。
这类曲子换成谁来编排都一样会走音，属于选曲问题而非工具问题。

判断你自己的曲子属于哪种，可以看「半音吸附」占源音符的比例：

- **< 5%**：调性音乐，转换基本忠实
- **5% ~ 15%**：有较多离调音，会有明显改动
- **> 15%**：半音化很强，建议换曲或接受改编

**Q: 换了 `--root` 或手动移调，会不会比自动选得好？**

可以试，但通常不会。自动移调（v1.3 起）在 ±3 个八度内穷举，评分直接对齐
「转换后有多少音符被改动」，实测在 178 份社区谱面上达到 99.89% 的还原率。
手工调音域很难超过它。真想换，用 `--root 57` 之类整八度移动即可。

**Q: 和弦太密弹不了？**
`--max-poly 3` 或 `--max-poly 1`。

**Q: 中文乱码（Windows）？**
PowerShell 里先执行 `$env:PYTHONIOENCODING='utf-8'`。
`转换.bat` 已处理编码，直接用即可。

**Q: 为什么 bpm 字段和实际听起来不一样？**
播放器按 `songNotes[].time` 的毫秒差计时，`bpm` 只用于 SkyStudio 编辑器显示格子。

**Q: `pitchLevel` 是什么？**

它是**这个谱面要在哪个调上演奏**（相对 C 调的半音数，0~11）。

关键：谱面内容**始终写成 C 大调形状（do-re-mi）**，换调靠 `pitchLevel` 声明，
不是把音符改写成别的黑键。证据：语料里 `Canon卡农_C大调` 的 `pitchLevel=0`、
`Pachelbel's Canon（D大调卡农）` 的 `pitchLevel=2`，而后者**黑键率是 0%**——
如果内容真写成 D 大调，必然出现 F#、C#。

**Q: 那要改它吗？**

默认不用。游戏默认就是 C 调，我们的谱面也已经排成 C 大调白键，两者天然对齐。

只有两种情况需要动它：

- 你的乐器已调在某个调上，想让谱面跟着对齐 → `--pitch-level N`（或 `转换-定调版.bat`）
- **代价：游戏内改调要花货币**

想换**音区**（不是换调）请用 `--root`。三者区别见 [定调与 pitchLevel](docs/定调与pitchLevel.md)。

---

## 更新日志

### v1.4.0 — 三种输出模式

把三个用途分流成三条独立路径，避免「默认输出」被少数特殊场景拖累。

- **`转换-C调默认.bat`**（默认）：`pitchLevel = 0`，游戏默认 C 调，不需要花货币。
- **`转换-定调版.bat`**：交互选 `pitchLevel = 0~11`，给「乐器已调在别的调」的场景。
  对应 CLI 的 `--pitch-level N`，现在它**真的写进头部字段**。
- **`转换-虚音版.bat`**：`--virtual-notes`，用两键凑差音代替黑键。
  **实验性** —— 数学上误差仅 5~6 音分，但实测差音比基音低 67~102 dB，会被完全掩蔽。
  保留此模式是为了把结论记录在案，详见 [虚音说明](docs/虚音说明.md)。

顺带新增 `[可弹性]` 指标：旋律中能用 15 键弹奏的比例，用来提前判断「这首歌适不适合」。

> **重要纠正**：v1.3.1 的文档曾断言「`pitchLevel` 与音高无关」，**那是错的**。
> 正确结论是：`pitchLevel` 表示谱面要在哪个调上演奏，而谱面内容恒定写成 C 大调形状。
> 证据是语料里的同曲异调对照 —— D 大调卡农 `pitchLevel=2` 且黑键率为 0%。
> 详见 [定调与 pitchLevel](docs/定调与pitchLevel.md)。

### v1.3.1 — 黑键吸附方向一致化

修了「听起来很奇怪，像是音都不是那个音」的第二个成因。

- **根因**：`snap()` 按旋律走向逐个决定黑键向上还是向下吸附，于是同一个音级
  在曲子里会落到不同的白键上。实测星降る海：C# 被映射到 G / A / B 三个白键。
- **修复**：新增 `pick_snap_directions()` 穷举 2⁵ 种方向组合；`snap()` 把方向排到
  排序键首位；吸附候选限定为最近上下两个白键。
- **效果**（同进程 A/B）：音级映射一致率 54.2% → **69.4%**，星降る海 58.3% → **83.3%**。
- 新增 `tests/test_snapdir.py`（7 个测试）。

### v1.3.0 — 旋律保真度修复

修了一个「转出来的琴谱旋律丢了」的严重问题。

- **根因**：移调量的搜索范围被写死成 `[-6, +6]` 半音，表达不了「整首挪一个八度」。
  于是为了音级统计好看，把大量音符挤出 C4~C6，再逐个八度折叠，
  旋律线在中间被反复截断。
- **修复**：搜索范围放宽到 `[-18, +18]`（3 个八度），评分改为直接对齐
  「转换后实际被改动的音符比例」（出界 + 黑键，等权），且只用旋律声部决策。
- **效果**（5 份真实 MuScriptor MIDI）：旋律音正确率 74.4% → **82.0%**，
  八度缠绕 16.8% → **9.0%**。
- **验证**（178 份社区谱面移位回环）：还原率 96.1% → **99.89%**。
- 新增 `tests/test_transpose.py`，锁定搜索范围、整体平移、等权评分等行为。

### v1.3.1 — 黑键吸附方向一致化

修了「听起来很奇怪，像是音都不是那个音」的第二个成因。

- **根因**：`snap()` 按旋律走向逐个决定黑键向上还是向下吸附，于是**同一个音级在曲子里会落到不同的白键上**。
  实测星降る海：C# 被映射到 G / A / B 三个不同白键，33.1% 的旋律音落在音级映射不一致的音级上。
  同一句旋律重奏时音名变了，听感就是「跑调 / 变色」。
- **第二个 bug**：`snap()` 原来从整个 15 键里按 `(距离, 协和度, 方向)` 排序取最小，
  `bass_pc` 一变就可能把 C#4(61) 吸到 E4(64) —— 跨过整个 D4，音级直接被改掉。
- **修复**：
  1. 新增 `pick_snap_directions()`，穷举 2⁵=32 种「每个黑键朝哪边」的组合，
     选音级轮廓最吻合的一组（5 份 MIDI 与 178 份社区谱面都独立收敛到「全部向上」）；
  2. `snap()` 把**方向**排到排序键第一位（优先于距离、协和度）；
  3. 吸附候选**限定为最近的上下两个白键**，不允许为了协和度跳到很远的键。
- **效果**（同进程 A/B，3 份可精确对齐的样本）：
  音级轮廓保真度 82.4% → **83.9%**，音级映射一致率 54.2% → **69.4%**；
  其中星降る海 单曲改善最明显：一致率 58.3% → **83.3%**。
- 新增 `tests/test_snapdir.py`（7 个测试），锁定方向优先、最近邻、音级一致性等不变式。
- 时间网格铁律不受影响，5 份样本速度偏差仍为 0.00%。

### v1.2.0 — SkyStudio 时间网格修复

修了「skyR 能播、SkyStudio 报错或变速」的问题。根因是 SkyStudio 要求
`gcd(所有 time) == 60000/bpm`，详见下方「常见问题」。

---

## 致谢

- [SkyStudio](https://play.google.com/store/apps/details?id=com.Maple.SkyStudio) — 光遇琴谱编辑器的定义者，本项目的输出格式以它的谱面规范为准
- [MuScriptor](https://huggingface.co/MuScriptor/muscriptor-small) — Mirelo × Kyutai 的开源多乐器转谱模型，典型的上游工具
- [MT3](https://github.com/magenta/mt3) — note event tokenization 的源头
- [skyR](https://github.com/iKeilo/skyR) — 优秀的开源光遇弹琴实现，本项目的兼容性测试参考之一
- [SkyAutoPlayerScript](https://github.com/StageGuard/SkyAutoPlayerScript) — 提供了 178 份社区光遇谱面，本项目的移调算法用它做回环验证

## 许可证

[MIT](LICENSE)

本项目只做格式转换，不附带任何乐谱。
转谱他人作品时请自行取得授权。
