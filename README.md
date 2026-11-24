# muscriptor2sky

把 MIDI 文件转成光遇 15 键琴谱,输出 SkyStudio 能直接读的 `.txt` 格式。也支持反向转换,把琴谱还原成 MIDI。

这个工具接受任何标准 MIDI 文件——DAW 导出的、手写的、MuScriptor/MT3 转谱的都可以。生成的琴谱能被 SkyStudio 和各种光遇弹琴工具直接使用。

**主要特性**
- 兼容 SkyStudio 格式标准(UTF-16LE + BOM)
- 零依赖,只用 Python 标准库
- 自动移调,让旋律尽量落在 15 个白键上
- 黑键智能吸附到最近的白键
- 内置格式校验(`--verify`)
- 支持双向转换

---

## 安装

需要 Python 3.8+。克隆后直接用:

```bash
git clone https://github.com/eeesssr/muscriptor2sky.git
cd muscriptor2sky
```

或者装成命令行工具:

```bash
pip install -e .
muscriptor2sky --help
```

---

## 快速上手

### 命令行

```bash
# 最简单:生成同名 .txt
python -m muscriptor2sky song.mid

# 推荐:带上曲名作者,顺便自检
python -m muscriptor2sky song.mid -n "晴天" -a "周杰伦" --verify
```

### Windows 拖拽

把 `.mid` 文件拖到 `.bat` 上就行。仓库里有三个:

| 文件 | 说明 | 适用场景 |
|---|---|---|
| `转换-C调默认.bat` | 标准输出,15 键白键 | ⭐ 大部分情况用这个 |
| `转换-定调版.bat` | 交互选调 | 乐器调在别的调时用 |
| `转换-虚音版.bat` | 实验性输出 | 研究用,见 [虚音说明](docs/虚音说明.md) |

详细说明看 [定调与 pitchLevel](docs/定调与pitchLevel.md)。

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
print(info["stat"])  # 转换统计
```

---

## 15 键与简谱对照

光遇键名从 0 开始计数:

| 键名 | 位置 | 简谱 |
|---|---|---|
| `1Key0` ~ `1Key6` | 1–7 | `1 2 3 4 5 6 7` |
| `1Key7` ~ `1Key13` | 8–14 | `1' 2' 3' 4' 5' 6' 7'` |
| `1Key14` | 15 | `1''` |

对应 MIDI 音高 C4(60) ~ C6(84)。

---

## 输出统计解读

运行后会显示:

```
输入: song.mid
音域: 15 键 C 大调 C(60) ~ C(84)
移调: -2 半音   bpm: 120   源音符: 34   鼓(丢弃): 16
映射: 精确 14 / 八度折叠 12 / 半音吸附 6 / 同键合并 2 / 超复音丢弃 0
输出音符: 32
[格式自检] 通过,可直接被 APP 播放
```

**关键指标**:
- **精确**: 音高正好落在白键上(越高越好)
- **半音吸附**: 黑键吸到白键(太多会走样)
- **八度折叠**: 超音域的音移了八度(少量正常)
- **最大复音**: 同时按几个键(>4 手弹不了)

---

## 常用参数

```bash
# 限制复音,适合密集的钢琴曲
python -m muscriptor2sky song.mid --max-poly 3

# 只要主旋律
python -m muscriptor2sky song.mid --max-poly 1

# 更细的网格,适合十六分音符
python -m muscriptor2sky song.mid --grid 0.125

# 保持原调不移调
python -m muscriptor2sky song.mid --transpose none

# 换音域(从 A3 开始)
python -m muscriptor2sky song.mid --root 57
```

完整参数列表:

| 参数 | 默认 | 说明 |
|---|---|---|
| `-o, --out` | 同名 .txt | 输出路径 |
| `-n, --name` | 文件名 | 曲名 |
| `-a, --author` | 空 | 作者 |
| `--bpm` | MIDI 速度 | 只影响编辑器显示 |
| `--pitch-level` | 0 | 定调(0=C 调) |
| `--root` | 60 | 最低键音高 |
| `--transpose` | `auto` | 自动移调 |
| `--grid` | 0.25 | 量化网格 |
| `--max-poly` | 0 | 复音上限 |
| `--verify` | 关 | 格式自检 |

---

## 反向转换

把琴谱转回 MIDI,用来核对或听听效果:

```bash
python -m muscriptor2sky "晴天.txt" -o 晴天.mid
```

---

## 完整工作流:音频转琴谱

```bash
# 1. 用 MuScriptor 把音频转成 MIDI
#    用 --instruments 只要钢琴轨
muscriptor transcribe --model medium --instruments "acoustic_piano" audio.wav -o piano.mid

# 2. 转成光遇琴谱
python -m muscriptor2sky piano.mid -n "曲名" -a "作者" --verify

# 3. 把 .txt 传到手机
#    Android: /sdcard/skyMusicAuto/
```

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

## 示例文件

[`examples/flower-dance/`](examples/flower-dance/) 里有个完整样例,可以用来验证工具行为:

```bash
python -m muscriptor2sky examples/flower-dance/input.mid \
    -o out.txt -n "DJ OKAWARI - Flower Dance" --verify
```

预期输出:

```
移调: +1 半音   bpm: 319   源音符: 2584   鼓(丢弃): 945
映射: 精确 1568 / 八度折叠 629 / 半音吸附 53
输出音符: 2250
可弹性: 97.9%
```

---

## 工作原理

```
读 MIDI(跳过打击乐) → 提取旋律(每个时刻的最高音) → 
搜索最佳移调量 → 八度折叠 → 黑键吸附 → 
同键合并 → 时间量化 → 写 UTF-16LE+BOM
```

### 移调算法

在 ±18 半音(3 个八度)内搜索,目标是让整条旋律尽量完整地落进 C4~C6 音域。这比简单统计"白键命中率"更准确——后者会把大量音挤出音域,再逐个折叠,导致旋律中断。

实测效果(178 份社区谱面):回环还原率从 96.1% 提升到 99.89%。

### 黑键吸附

每个黑键音级统一朝一个方向吸附,而不是逐音决定。这样同一个音级在整首曲子里总是落到同一个白键上,避免"同一句旋律重奏时音名变了"的问题。

实测星降る海:修复前 C# 被映射到 G/A/B 三个不同白键,修复后固定一个。

### SkyStudio 时间模型

SkyStudio 要求 `gcd(time 间隔) == 60000/bpm`,否则播放速度会变。工具会自动调整 bpm 来满足这个条件,保证速度准确。

---

## 常见问题

**Q: 播放出来低了一个音?**
键名是 0 基的,第一键是 `1Key0` 不是 `1Key1`。

**Q: skyR 能播,SkyStudio 报错?**
这是时间网格问题,v1.2 已修复。用 `--verify` 自检。

**Q: 旋律跑调?**
看输出里的"半音吸附"占比。如果很高,说明原曲大量用黑键,15 键琴物理上弹不出来。这是乐器限制,不是转换错误。

判断标准:
- < 5%: 转换基本忠实
- 5~15%: 有明显改动
- \> 15%: 建议换曲或接受改编

**Q: 和弦太密弹不了?**
用 `--max-poly 3` 或 `--max-poly 1` 限制复音。

**Q: 中文乱码(Windows)?**
PowerShell 里先 `$env:PYTHONIOENCODING='utf-8'`,或直接用 `.bat` 文件。

---

## 版本历史

### v1.4.0 — 三种输出模式
- 分离为三条独立路径:C 调默认、定调版、虚音版
- 新增"可弹性"指标
- 修正了关于 `pitchLevel` 的理解

### v1.3.1 — 黑键吸附方向统一
- 修复同一音级映射到不同白键的问题
- 音级轮廓保真度 82.4% → 83.9%

### v1.3.0 — 旋律保真度修复
- 搜索范围扩展到 ±18 半音
- 旋律音正确率 74.4% → 82.0%
- 回环还原率 96.1% → 99.89%

### v1.2.0 — SkyStudio 时间网格修复
- 修复"skyR 能播、SkyStudio 报错"的问题
- 保证 `gcd(time) == 60000/bpm`

---

## 开发

```bash
# 跑测试
python run_tests.py

# 或用 pytest
pip install pytest && pytest
```

测试覆盖:音高映射、键位约定、MIDI 解析、黑键吸附、复音限制、编码、往返一致性。

---

## 致谢

- [SkyStudio](https://play.google.com/store/apps/details?id=com.Maple.SkyStudio) — 光遇琴谱编辑器标准
- [MuScriptor](https://huggingface.co/MuScriptor/muscriptor-small) — 开源多乐器转谱模型
- [skyR](https://github.com/iKeilo/skyR) — 开源光遇弹琴实现
- [SkyAutoPlayerScript](https://github.com/StageGuard/SkyAutoPlayerScript) — 提供社区谱面验证

## 许可

[MIT](LICENSE)

本项目只做格式转换,不附带任何乐谱。转谱他人作品请自行取得授权。
