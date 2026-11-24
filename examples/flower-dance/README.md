# 示例：DJ OKAWARI - Flower Dance

一份完整的「MuScriptor 转谱 MIDI → 光遇琴谱」样例，可以用来验证工具行为。

## 文件

| 文件 | 说明 |
|---|---|
| `input.mid` | **MuScriptor 输出的原始 MIDI**（多轨，含打击乐） |
| `output.txt` | 用本工具转换出的光遇琴谱（SkyStudio 格式） |

## 复现命令

```bash
python -m muscriptor2sky examples/flower-dance/input.mid \
    -o examples/flower-dance/output.txt \
    -n "DJ OKAWARI - Flower Dance" \
    --verify
```

## 转换结果

```
输入: input.mid
音域: 15 键 C 大调 C(60) ~ C(84)
移调: +1 半音   bpm: 319   源音符: 2584   鼓(丢弃): 945
映射: 精确 1568 / 八度折叠 629 / 半音吸附 48 / 同键合并 339 / 超复音丢弃 0
输出音符: 2245
时间网格: 单位 1 拍 = 188 ms  [SkyStudio 兼容]
[格式自检] 编码 UTF-16LE(BOM) | 音符 2245 | 事件 1313 | 最大复音 6 | 时长 318.3s
[格式自检] 用到键位 [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14]
[格式自检] 通过，可直接被 APP 播放
```

## 为什么选这个例子

它覆盖了转换流程里的几个典型情况：

- **多轨输入**：MuScriptor 按音色分组输出多轨，其中打击乐在 channel 9，被自动丢弃（945 个音符）
- **需要移调**：原曲不在 C 大调，工具自动移调 +1 半音使最多音符落在白键
- **音域溢出**：629 个音符超出 C4–C6，做了八度折叠
- **黑键吸附**：48 个音符是黑键，被吸附到最近白键（同一个音级固定朝同一方向）
- **同键冲突**：339 次两个音抢同一个键，合并保留时值更长的
- **复音控制**：转换后最大复音 6，仍在可演奏范围内
- **时间网格**：这是最容易被忽略的一环，详见下面

## 重点：时间网格为什么是 188ms

SkyStudio 的播放延时算法是：

```
unit      = gcd(所有相邻 time 的间隔)
sleepUnit = duration / unit
实际延时   = sleepUnit * (60000 / bpm)
```

要让播放速度与原曲一致，必须满足 `gcd(times) == 60000 / bpm`。

这份例子里：

```
bpm  = 319.1489361702128
cell = 60000 / bpm = 188.0 ms
gcd(所有相邻 time 的间隔) = 188 ms     ← 恰好相等
```

所以 SkyStudio 播放速度偏差 **+0.00%**，时长 315.28s 与原曲一致。

> 注意 bpm 是个小数（319.1489…），不是整数。这没关系——
> 关键在于 `60000/bpm` 是整数（188），且所有时间戳都是它的整数倍。

实测时间戳（前 10 个）全部是 376 的整数倍，也就是 188 的 2 倍：

```
3008, 3384, 3760, 4136, 4512, 4888, 5264, 5640, 6016, 6392
间隔: 376, 376, 376, 376, 376, 376, 376, 376, 376
```

## 手工验证网格

```python
import json, math

s = json.loads(open("output.txt", "rb").read()[2:].decode("utf-16-le"))[0]
ts = sorted(set(n["time"] for n in s["songNotes"]))
g = 0
for a, b in zip(ts, ts[1:]):
    g = math.gcd(g, b - a)

cell = 60000.0 / s["bpm"]
print("cell =", cell, " gcd =", g, " 相等:", abs(cell - g) < 1.0)
# cell = 188.0  gcd = 188  相等: True
```

---

原曲版权归 DJ OKAWARI 所有。本目录仅提供**格式转换的技术样例**，
用于验证工具输出，不构成对原作品的授权或分发。
