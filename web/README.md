# xcpc-vp 前端（并入 vp-helper）

基于 RankLand 榜单数据的纯前端 XCPC 虚拟参赛工具。选择一场历史比赛后，在浏览器中按原始提交时间重放榜单。可以暂停、倍速、从指定时间开始，并加入自己的队伍记录判题结果。

这个目录已并入 [vp-helper](../README.md)，由 `vp` 自动启动并同步真实提交结果。独立运行方式仍然保留。

## 与 vp-helper 的集成

`vp qoj ID` 启动时会：

1. 按比赛标题在 RankLand 合集里匹配这场比赛；
2. 让本目录的构建产物在 `127.0.0.1:5174` 上可用；
3. 打印带 `contest`、`team`、`organization`、`at` 参数的地址，由你手动在浏览器打开（不调用系统打开器）；这一步发生在对 QOJ 发起开赛请求之前；
4. 把终端里已判定的提交写到 `$XDG_STATE_HOME/vp/xcpc-vp.json`，页面每 2 秒轮询 `/api/vp-xcpc` 取回并追加到手动提交记录。

`at` 用 QOJ 上该次 VP 的实际开始时间，网页计时和终端计时共用同一零点。

## 两种运行模式

- **构建模式（默认）**：`dist/` 已随仓库提供，由 `vp_helper/webui.py` 直接用 Python 提供静态文件和 `/api/vp-xcpc` 端点，不需要 Node。
- **源码模式**：`dist/` 不存在时，`vp` 回退到 `pnpm dev:vp` 热更新，需要 Node 22 和 pnpm 9。

改前端后必须重新构建，否则 `vp` 仍用旧的 `dist/`：

```bash
pnpm install --frozen-lockfile
pnpm build:vp
```

## 独立开发

```bash
pnpm install --frozen-lockfile
pnpm dev:vp
```

打开 `http://127.0.0.1:5174/`。

生产构建与预览：

```bash
pnpm build:vp
pnpm preview:vp
```

构建产物位于 `dist/`，是可直接部署的静态网站。

首页在线人数还需要部署根目录 `edge-functions/` 并启用 EdgeOne Blob，详见 [在线人数部署说明](docs/vp-presence.md)。只上传 `dist/` 时无法提供全站统计。

## 测试

```bash
pnpm exec vitest run --config vite.config.js
pnpm build:vp
```

测试覆盖重放边界、官方 ICPC 计分、CCPC 2026 揭题、分栏选赛、参数校验、比赛摘要和手动提交时间。

## URL 参数

```text
contest   比赛 ID
rule      auto、ICPC 或 CCPC26
speed     1、2、5、10、30、60
from      计时基准处的虚拟进度，单位为分钟
at        实际开始时间（ISO 时间，+08:00 中国时区，立即开始和预约开始均写入）
anchor    暂停、继续或变速时的现实计时基准（ISO 时间，+08:00，可省略，默认使用 at）
team      队伍名称
organization 学校 / 单位（可选）
feed      是否显示实时提交条，0 或 1
play      计时是否运行，0 或 1；预约时间未到时等待
count     CCPC 2026 通过队伍数阈值
ratio     CCPC 2026 通过比例阈值，百分比
```

额外罚时固定为 20 分钟，提交时间必须早于当前虚拟时间和比赛结束时间。计时不读取或写入 localStorage；刷新后由 URL 恢复。每次新开比赛都会写入新的实际开始时间，不会继承上一场的结束状态。手动提交按比赛和实际开始时间单独保存在浏览器本地。预约选择和显示统一使用北京时间（UTC+8），不受浏览器时区影响；无时区的 URL 时间也按北京时间解释。

## 数据与来源

- 榜单合集和 SRK 数据来自 [RankLand](https://rl.algoux.cn/collection/official)。
- 榜单渲染组件和评分工具来自 [algoux/standard-ranklist](https://github.com/algoux/standard-ranklist) 及其相关仓库。
- 页面结构和视觉基于 [algoux/rankland-web](https://github.com/algoux/rankland-web) 官方项目。
- 本项目是独立的虚拟参赛工具，不代表 RankLand 官方。

## 许可证说明

本仓库保留上游项目和第三方依赖的版权信息。

`@algoux/standard-ranklist`、渲染器和相关工具包包含 MIT 许可证文本；榜单数据来自 [algoux/srk-collection](https://github.com/algoux/srk-collection)，请按其许可证和数据说明使用。

`rankland-web` 上游源码的授权边界请以作者的明确许可为准。本仓库暂不为上游未明确授权的源码声明新的许可证。
