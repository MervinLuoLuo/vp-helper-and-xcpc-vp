# VP Helper

XCPC 虚拟参赛终端助手，支持 QOJ。上方显示成绩与完整提交记录，下方保留比赛目录中的普通 shell

同时融合 [xcpc-vp](https://github.com/coolarec/xcpc-vp) 浏览器回放前端（`web/`）：`vp` 开赛时会给出网页地址，由用户手动打开，真实判题结果自动同步到网页榜单

## 安装

支持任意 Linux 发行版（Arch、Debian/Ubuntu、Fedora、openSUSE、Alpine、Void、Gentoo 等）和 macOS。Python 3.12 由 [uv](https://astral.sh/uv) 自动下载，依赖从仓库的 `wheels/` 离线安装，装到 `~/.local/lib/vp-helper`，不需要 root。

### 前置

需要 `uv` 和 `tmux` 外部依赖，需要手动安装

```bash
git clone https://github.com/MervinLuoLuo/vp-helper-qoj-only.git
cd vp-helper-qoj-only
./vp-install-portable.sh install
```

安装后可在任意目录使用 `vp` 和 `submit`。

其他子命令：

```bash
./vp-install-portable.sh env       # 打印需要 source 的环境变量
./vp-install-portable.sh check     # 自检
./vp-install-portable.sh uninstall # 卸载（含 ~/.config/vp 账号配置）
```

安装脚本支持的环境变量：`VP_ROOT`（安装根目录）、`VP_STATE_DIR`、`VP_PYTHON`、`VP_USE_UV`、`VP_START_FILE`、`VP_ASK_COOKIE`。

运行时另有：`VP_XCPC`（设为 `0` 关闭浏览器回放）、`VP_XCPC_PORT`（默认 5174）。

## 使用

将 `ID` 替换为对应平台的数字比赛编号：

```text
vp qoj ID
```

例如：

```bash
vp qoj 3169
submit A.cpp
vp history
```

也支持 `vp CONTEST_URL`（QOJ 或 ucup 比赛链接）。计分范围限定为 ICPC；非 ICPC 赛制的比赛会在开赛前被拒绝。

首次使用需要配置账号：

```bash
vp login qoj
```

按提示依次输入 handle 和四个 Cookie（`__Host-UOJREMEMBER`、`__Host-UOJSESSID`、`cf_clearance`、`uoj_preferred_language`）

Cookie 是唯一的凭据来源，程序不会读取浏览器。配置保存在 `~/.config/vp/config.json`（设置 `XDG_CONFIG_HOME` 时为 `$XDG_CONFIG_HOME/vp/config.json`），权限为 600；也可以参考 `config.example.json` 手动填写。

Cookie 过期时，在浏览器里重新登录 QOJ，取出新的 `Cookie` 请求头值，然后 `vp login qoj` 重新填写。也可以直接编辑配置里的 `qoj.cookie`。

填写 `cookie` 时只复制请求中 `Cookie` 的值，省略 `Cookie:` 标签和其他请求头。

安装时会询问**比赛目录**，作为比赛文件夹和 VP 记录的保存目录 。路径存在 `~/.config/vp/config.json` 的 `work_directory`，例如：

```json
{ "work_directory": "~/contests", "qoj": { ... } }
```

改位置的方式：重跑 `install` 时输入新路径，或直接编辑 `work_directory`。也可以用 `VP_WORK_DIR=/path/to/dir ./vp-install-portable.sh install` 跳过交互。

未配置 `work_directory` 时 `vp` 会直接报错，不会静默写进某个默认目录。

每场比赛在这个目录下共用一个子文件夹，例如 `2024 ICPC Nanjing Reg`。再次进入保留已有代码和输入数据，更新提交配置与题面；各次 VP 的开始时间和成绩状态独立保存。`submit A.cpp` 在对应比赛目录内运行。

## 成绩与界面

- `vp` 准备题面与提交配置后，在现有账号上启动并验证原站 VP，以平台开始时间计时。
- QOJ 启动请求只发送一次；登记结果暂未返回时会短暂重查。请求超时也会先核对原站记录，确认成功后直接沿用原站开始时间。网站拒绝启动时显示它返回的提示；仍无法确认时，可再次运行同一场命令检查已有登记。
- 按正式参赛资格计算排名，排除打星队与其他 VP；解题数和罚时相同共享名次，最后 AC 用时只决定展示顺序。
- 奖项采用原赛明确配置。资格、规则或榜单完整性无法验证时，保留未知结果。
- `rank` 列保持在成绩表左侧，排名和奖项在同一格内分两行显示，例如上行 `=47`、下行 `Silver Prize`。
- 内置 submit 在服务器确认新提交编号后立即通知面板显示 `PENDING`，随后用平台判定替换；本人提交与榜单查询独立执行。
- QOJ 的 0 分提交会读取详情区的测试点判定，区分 WA、CE、RE 等结果；前面通过的测试点不会覆盖后面的失败。详情暂时无法读取时显示 `RESULT UNAVAILABLE`，按退避间隔重查，并继续更新其他提交。影响罚时的结果未确认时，罚时与排名暂不显示确定值。
- 提交记录按时间从新到旧完整展开，`practice` 标注紧贴判定。5 小时后的补题不计入比赛成绩，未通过显示橙色，通过显示紫色。
- 空白、标题与提交列表继承终端默认背景，支持终端自身的透明效果。
- 最终成绩保存到桌面的 `vp_history.csv`。
- `vp history` 增加 `gold`、`silver`、`bronze` 三列，显示原赛正式队终榜的金、银、铜线。每格上行是过题数/罚时，下行是名次界限，例如 `9/1200` 与 `(≤30)`；并列成绩使用相同分界，打星队不计入奖线。比赛完成后保存奖线，旧记录从本地 VP 状态和已核验的原赛缓存补齐。只有奖项名额时过题数/罚时显示 `—`，资格或数据缺失时整格显示 `—`。历史查询不联网，也不改写原有 CSV。

在上方面板用方向键、`PgUp` / `PgDn`、`Home` / `End` 或鼠标滚轮查看提交。`Ctrl+B`、`D` 脱离 tmux 后继续同步；再次运行同一场比赛命令可恢复。按 `q` 关闭评分面板。

## 赛时排名与统计

有待判提交时，在上一轮查询返回后约 2 秒再次查询本人判定；其余时间约 5 秒，网络故障时退避重试（5→10→20→40→60 秒封顶）。平台榜单约 30 秒重新核对；这些间隔不包含网络耗时。

QOJ 在 VP 进行中返回的账号榜单已经按当前时间截断，程序使用不携带登录凭据的独立会话读取公开完整终榜来校验回放。档案时间窗口或 QOJ 导入时间与原站 VP 有差异时，分别处理；只有统一时间偏移后的全部终榜结果一致，才接受时间对齐。本人计时和补题分界仍按 QOJ 原站的 VP 时长。导出记录中的管理员测试提交不属于参赛队伍，不计入回放。正式与打星队伍的每题结果仍须和原站终榜逐一一致，才会显示实时排名与统计。

- `submitted`：首次通过前的有效计分提交次数，含待判。
- `attempted`：有有效尝试的正式队伍数。
- `accepted`：通过的正式队伍数。

统计包含本人赛内提交，排除打星和赛后补题；编译错误按本场计分规则处理。封榜时公开统计隐藏冻结后的结果，rank 显示 `?`，当前 VP 的原站解封后恢复。缺少资格数据或完整事件记录时，面板显示具体原因；只有终榜时，赛时排名与统计保持 `—`。奖项只使用明确的原赛奖牌配置。

2026 年起的 CCPC 区域赛自动启用题号揭示：某题被 50 支不同的原赛队伍通过后，才在公开统计中显示题号，正式队和打星队一并计数，当前 VP 不参与这个阈值。排名、奖项和上面的三项公开统计仍按正式参赛资格计算。尚未揭示的题号及对应统计显示为 `?`，匿名列集中排列，避免从 A–M 的位置推断题号。本人每题成绩与提交记录仍按实际题号显示。到原站规定的封榜时刻，所有题号同时揭示，公开统计固定在封榜前，原站解封后恢复完整结果。

例如 `vp qoj 4582` 会识别为 `2026 CCPC Changchun Reg`，采用 5 小时赛长、4 小时封榜。比赛名称中的 `Site` 及中英文双语标题均可识别；其他人的较短 rated VP 时长不再覆盖公开比赛时长。QOJ 目前仍以传统 ICPC 规则运行该场原站 VP，题号揭示由本地面板模拟。

**省赛因为无法准确对应需要获取的榜单和可能导致某些神秘问题**

## 浏览器回放

`vp qoj ID` 在 tmux 会话建好后，会打印一个网页地址，**需要自己在浏览器里打开**。

这是**附加功能**：网页端不可用时终端面板一切照常，只打印一行提示。

只在全新会话时问；`Ctrl+B`、`D` 脱离后再进来不会重复询问。

提交通过 `/api/vp-xcpc` 同步：`vp` 在每次状态落盘时把终态提交写成一个文件，页面每 2 秒轮询该端点，去重后追加到手动提交记录。只推送已判定的结果：

| 平台判定 | 网页结果 |
|---|---|
| `CORRECT` | `AC` |
| `WRONG-ANSWER` | `WA` |
| `TIMELIMIT` | `TLE` |
| `MEMORY-LIMIT` | `MLE` |
| `RUN-ERROR` | `RTE` |
| `COMPILER-ERROR` | `CE` |
| `OUTPUT-LIMIT` / `NO-OUTPUT` | `OLE` / `NOUT` |

`PENDING`、`UNAVAILABLE`、`TOO-LATE` 不推送，避免把未定的结果记成 `WA`。

### 两种运行模式

`web/dist` 已随仓库提供，**默认用 Python 直接提供静态文件和同步端点，不需要 Node**。改前端时才需要 Node 22 和 pnpm 9：

```bash
cd web
pnpm install --frozen-lockfile
pnpm build:vp        # 产物写到 web/dist，装完即生效
```

开发时若 `web/dist` 不存在，会自动回退到 `pnpm dev:vp` 热更新模式。

关掉网页功能：

```bash
export VP_XCPC=0
```

改端口（网页地址和状态检查都会跟着变）：

```bash
export VP_XCPC_PORT=5180
```

## 数据与第三方组件

仓库和安装包不包含任何比赛数据。首次使用时自动获取，优先从 [SRK Collection](https://github.com/algoux/srk-collection) 读取原赛档案，未收录时回退到 [XCPCIO board-data](https://github.com/xcpcio/board-data)。

生成的数据保存在用户自己的 `~/.cache/vp/originals/`（设置 `XDG_CACHE_HOME` 时使用 `$XDG_CACHE_HOME/vp/originals/`），后续使用复用缓存。缓存可以删除，下次使用会重新获取；首次获取需要网络。不需要修改仓库或手动添加比赛 JSON 文件。无法取得完整可靠原赛数据的比赛，仍显示本人成绩和提交，并说明参考排名或统计缺失的原因。XCPCIO 的 MIT 许可证保留在 `third_party/xcpcio/LICENSE`。

SRK Collection 的档案按其 AGPL-3.0 许可证提供，来源和许可证保留在 `third_party/srk/`；仓库仅包含独立编写的档案读取器，不内置 SRK 比赛数据或组件代码。

提交器来自 [hikariyo 的 QOJ submit.py](https://gist.github.com/hikariyo/b3cec2e736d87be57d1e4faafb04f908)，固定版本、兼容补丁与现有许可证保存在 `third_party/qoj/`。Python 运行时的来源与校验值见 `runtimes/manifest.json`。

`web/` 中并入了 xcpc-vp 前端，它基于 [algoux/standard-ranklist](https://github.com/algoux/standard-ranklist)、[algoux/rankland-web](https://github.com/algoux/rankland-web) 与 [RankLand](https://rl.algoux.cn/) 榜单数据，许可证边界见 `web/README.md`。

本仓库仅包含运行程序、安装依赖和使用文档；比赛数据、测试代码、测试样例、账号配置及个人比赛文件不纳入仓库。
