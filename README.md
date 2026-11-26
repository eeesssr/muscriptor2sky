# muscriptor2sky 网页版

> **这个分支是自动生成的，请不要直接在这里修改。**
> 源码在 [`main`](https://github.com/eeesssr/muscriptor2sky) 分支的 `web/` 目录，
> 每次 `web/` 有改动，GitHub Actions 会自动把它发布到这里。
> 在这里提交的任何改动，下次部署都会被覆盖。

在线使用：**https://eeesssr.github.io/muscriptor2sky/**

---

## 这是什么

把 MIDI 文件转成光遇（Sky: Children of the Light）15 键琴谱的工具，
输出 SkyStudio 能直接读的 `.txt`。

**全程在浏览器里完成，文件不会上传到任何服务器。**
这不是宣传语，而是架构决定的：页面里不存在任何上传代码，
没有后端、没有 `fetch`、没有 `XMLHttpRequest`。断网也能用。

## 怎么用

1. 浏览器打开 https://eeesssr.github.io/muscriptor2sky/
2. 把 `.mid` 拖进虚线框（手机上是点一下选文件）
3. 点「转换」
4. 点「下载 .txt」

得到的 `.txt` 直接导入 SkyStudio 或各种光遇弹琴工具即可。

手机上还可以「添加到主屏幕」，装成 App 用（PWA，支持离线）。

## 目录说明

| 文件 | 说明 |
|---|---|
| `index.html` | 页面本体（HTML + CSS + JS 全在一个文件里，无外部依赖） |
| `sky-core.js` | 转换核心，是 `core.py` 的 1:1 JavaScript 移植 |
| `sw.js` | Service Worker，负责离线缓存 |
| `manifest.webmanifest` | PWA 清单 |
| `API.md` | 核心的接口契约 |
| `.nojekyll` | 关闭 Jekyll 处理，让静态文件原样发布 |

## 与命令行版的关系

网页版和命令行版跑的是**同一套算法**，输出**逐字节相同**。

这不是靠人工核对保证的，而是靠自动化的交叉校验：

- `tools/gen_fixtures.py` 用 Python 参考实现生成 12 个基准夹具、109 个用例，
  覆盖白键、黑键、音域越界、复音限制、同键合并、变速、无 tempo、
  极密十六分音符、空 MIDI 等分支
- `web/tests/core.test.js` 用 Node 内置 test runner 逐字节比对，237 项全部通过

所以你在网页上得到的谱面，和本地跑命令行得到的是完全一样的文件。

## 用命令行

需要批量处理或者写脚本时，用 [`main`](https://github.com/eeesssr/muscriptor2sky) 分支的命令行版：

```bash
git clone https://github.com/eeesssr/muscriptor2sky.git
cd muscriptor2sky
python -m muscriptor2sky song.mid -n "曲名" -a "作者" --verify
```

## 许可

[MIT](https://github.com/eeesssr/muscriptor2sky/blob/main/LICENSE)

本项目只做格式转换，不附带任何乐谱。转谱他人作品请自行取得授权。
