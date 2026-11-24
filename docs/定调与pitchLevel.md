# 定调与 `pitchLevel`

本文说明 SkyStudio 谱面里的 `pitchLevel` 字段是什么、本工具怎么自动识别它，
以及三种输出模式的区别。

## 结论先行

**`pitchLevel` = 这个谱面要在哪个调上演奏**，取值 0~11，直接索引
`['C','Db','D','Eb','E','F','Gb','G','Ab','A','Bb','B']`（0=C，2=D，7=G）。

关键点：**谱面内容永远写成 C 大调形状（do-re-mi），换调靠 `pitchLevel` 声明，
而不是把音符改写成别的黑键。**

## 源码证据（决定性）

Sky Music Nightly（[Specy/genshin-music](https://github.com/Specy/genshin-music)）
是 SkyStudio 谱面格式的开源实现，读写方向可直接对照：

```ts
// src/lib/core/sharedConfig.ts:156
export const PITCHES = ['C','Db','D','Eb','E','F','Gb','G','Ab','A','Bb','B'] as const

// src/lib/core/Songs/RecordedSong.ts:144  —— 写谱时
pitchLevel: PITCHES.indexOf(this.pitch),

// src/lib/core/Songs/RecordedSong.ts:605  —— 读谱时（完全可逆）
converted.pitch = (PITCHES[song.pitchLevel || 0]) || 'C'

// src/lib/core/Songs/RecordedSong.ts:619  —— 音符索引换算不查 pitchLevel
const index = legacyTables.importPositions.Sky[Number(data[1])] ?? -1
```

三条合起来就是因果证明：写入时取调名下标、读取时可逆还原、
而**音符索引的换算完全不看这个字段** → 它不 remap 15 个按键，只声明调。

第二份独立实现 [iamjunioru/SkyAutoPlayer-BR](https://github.com/iamjunioru/SkyAutoPlayer-BR)
有一张独立的 `pitch_suggestion` 表，把每个档位映射到该调在游戏内的位置，
**两张表 12/12 完全一致**（`Db/Eb/Gb/Ab/Bb` 只是等音写法差异）。
两份互不相关的实现导出同一张 12 档表，可作为「0~11 就是 12 个半音」的强证据。

补充一条旁证：纯播放器 [iKeilo/skyR](https://github.com/iKeilo/skyR) 的 `MusicParser.kt`
里 `pitchLevel` 出现 **0 次**。它只按 `songNotes` 按键，不需要知道调 ——
因为音高由游戏内乐器当前调性决定，不由谱面内容决定。

> 注：Specy 的表在第 6 档写 `Gb`，本项目内部写作 `F#`（等音，音高相同）。

## 语料旁证（文件名 ↔ 字段值 5/5）

| 文件 | 文件名标注 | `pitchLevel` | `PITCHES[pl]` |
|---|---|---|---|
| `Canon卡农_C大调_简易版.txt` | C 大调 | 0 | C |
| `Lemon(C调).txt` | C 调 | 0 | C |
| `星茶会（高音钢琴C调）.txt` | C 调 | 0 | C |
| `Pachelbel's Canon（D大调卡农）.txt` | D 大调 | 2 | D |
| `G大调莫扎特奏鸣曲K283 Mozart Sonata.txt` | G 大调 | **7** | **G** |

另有决定性旁证：`chopsticks duet high pitch` 与 `... low pitch` 两个版本
明明差一个八度，但 `pitchLevel` **都是 0** —— 证明它是「调」不是「音区」。

## 两处必须纠正的早期错误

### 错误 1：「`pitchLevel` 与音高无关」

早期版本用「`pitchLevel` 与实际音域的相关系数」检验，得 r≈0.04，据此判定它不表示音高。
这个推理有缺陷：**`pitchLevel` 影响的不是「用哪些键」，而是「键盘整体听起来是哪个调」**。
既然所有谱面都写成 C 大调形状，键位分布自然与它无关，相关系数为零是**预期结果**，
不能用来否证「它是调」。

### 错误 2：用「D 大调卡农黑键率为 0%」当论据

这是**循环论证**。谱面格式只能命名 15 个 C 大调按键 —— 实测 178 份语料出现的
键位索引集合恰好是 `[0..14]`，无越界值；Specy `game.json` 的 `canonicalNoteIds`
音级全是 C D E F G A B。**任何谱面都不可能写出黑键**，所以「黑键率 = 0%」对每份谱面都成立，
无法区分「写成 C 大调」还是「写成 D 大调」。

结论方向没错，论据已换成上面的源码证据。

## 自动定调（v1.5.0 默认）

```bash
python -m muscriptor2sky song.mid          # 默认 auto
python -m muscriptor2sky song.mid --key 7  # 手动指定（备用）
python -m muscriptor2sky song.mid --key c  # 强制 C 调（旧行为）
```

**为什么必须自动识别**：15 键只有白键。一首 B 大调的曲子里，B 大调音阶有 5 个音
是钢琴黑键，写不出来。而只要整曲移调 `t ≡ -K (mod 12)`，原曲音阶**恰好**
落成 C 大调形状 —— 零黑键。演奏时把乐器调到 K，音高就补回来了。

```
原曲：B 大调音阶   B  C# D# E  F# G# A#
移调 t = +1  ↓
谱面：C 大调音阶   C  D  E  F  G  A  B     ← 15 键，零黑键
头部：pitchLevel = 11 (B)                    ← 演奏时整台乐器升 11 半音
```

### 识别算法

1. **音级直方图**：统计 12 个音级各占多少权重。
   权重用**时值**，样本用**全部音符**。
2. **12 个大调各算覆盖率**：该调音阶覆盖的权重占总权重多少。
3. **并列裁决**：覆盖率几乎相同（差 <0.5 个百分点）时不算并列竞争，
   交给音乐先验 —— 末音==主音加成、主音自身权重、Krumhansl-Kessler 相关。

### 为什么用全部音符按时值加权

这一条容易和移调量的取舍搞混，但两者结论**相反**：

| 目标 | 用什么 | 原因 |
|---|---|---|
| 移调量（`pick_transpose`） | **只有旋律** | 低音本来就要八度折叠，参与决策会把移调拖偏（80.7%→72.9%） |
| 调性（`detect_key`） | **全部音符，按时值** | 伴奏的低音与五度同样携带调性信息，丢掉等于丢掉证据（95.51%→97.19%） |

注意**不要按力度加权**：SkyStudio 谱面格式没有力度字段，`vel` 恒为 1，
按 `dur*sqrt(vel)` 加权与按 `dur` 加权逐样本完全相同。

### 验证

178 份社区谱面 × 12 个调 = 2136 样本（真值由内容整体移调合成，不是读 `pitchLevel`）：

| 指标 | 结果 |
|---|---|
| 12 分类准确率 | **97.19%**（2076/2136） |
| 完全判对的谱面 | 172 / 178 |
| 5 份真实 MIDI | 5 / 5（B、Bb、Eb、D、G） |
| 判错样本的可弹率损害 | **0 个下降** |

最后一行最重要：判错的都是**真歧义**素材（五声/无调性），用另一个调来解，
落白键的比例一模一样 —— 弹得出来，只是理论上「调」不同。

残余错误全部落在 **Δ=±5 / ±7**（四度、五度关系调，如 C↔G、B↔F#），
这两个调只差一个音级，音级不全的曲子数学上不可区分；Δ=±1、±6 零错例。
**理论上界约 98.4%**。

## 三种输出模式

### 1. 自动定调（默认，推荐）

```bash
python -m muscriptor2sky song.mid
```

- 识别原曲大调 K，整曲移调 `t ≡ -K (mod 12)`
- 头部 `pitchLevel = K`
- 音级保真实测 **100%**；用 K 调乐器演奏即是原曲音高
- 前提：演奏时乐器需处于 K 调（见下方「仍未确认的部分」）

### 2. 强制 C 调（旧行为）

```bash
python -m muscriptor2sky song.mid --key c
```

- `pitchLevel = 0`，乐谱写成 C 大调形状
- 整曲被移调，**音高与原曲不同**（实测音级保真 0.0%）
- 好处：游戏默认 C 调乐器直接能弹
- 适合：只想听个概念、或希望用默认乐器演奏时

### 3. 手动定调（备用）

```bash
python -m muscriptor2sky song.mid --key 7
```

- 强制 K=7（G 调），不做识别
- 适用：自动识别不准，或你明确知道自己要哪个调
- `--pitch-level N` 是它的别名，旧脚本可继续用

### 4. 虚音输出（实验性）

```bash
python -m muscriptor2sky song.mid --virtual-notes
```

用两个白键同时按下产生的**差音**（difference tone）来凑弹不出的黑键。
详见 [虚音说明](虚音说明.md)。

⚠️ **实验性，实际听感大概率更差。** 差音比基音低 67~102 dB，会被完全掩蔽；
而且凑虚音所需的音程本身很刺耳。

## 与 `--transpose none` 的关系

`--transpose none` 表示一个半音都不挪。此时 `pitchLevel` **只能是 0** ——
若声明成别的调，演奏音高会比原曲高出 K 个半音。两者同时给会冲突，
CLI 会按「不移调」处理并打印提示。

## 想换音区（而不是换调）怎么办

**换音区和换调是两件事：**

- 想改变「用到的音高低」（比如整体低一个八度）→ 用 `--root`
- 想改变「演奏的调」→ 用 `--key`

```bash
python -m muscriptor2sky song.mid --root 72   # 从 C5 开始（更高）
python -m muscriptor2sky song.mid --root 57   # 从 A3 开始（更低）
```

## 仍未确认的部分

- **SkyStudio APP 自身是否还有别的定调机制**：本文依据的是共享谱面格式的
  开源实现（Sky Music Nightly / SkyAutoPlayer-BR），不等同于 SkyStudio APP 的实现。
  但两者共享同一份谱面格式，且 `pitchLevel` 的语义在开源侧已双向可逆、且不改键位，
  一致度很高。
- **未做真机播放验证。** 「`pitchLevel = 2` 让实际音高整体升 2 个半音」这一点
  来自源码 `2^(index/12)` 的升调实现，没有在游戏里实听确认。
  如果你愿意实测一两个档位告诉我，可以把这块补实。