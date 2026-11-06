# VP Helper

XCPC 虚拟参赛终端助手，支持 QOJ。上方显示成绩与完整提交记录，下方保留比赛目录中的普通 shell。

仓库同时包含 xcpc-vp 浏览器回放前端（`web/`）：`vp` 开赛时会给出网页地址，由你手动打开，真实判题结果自动同步到网页榜单。

当前版本：0.1.15。

## 安装

支持任意 Linux 发行版（Arch、Debian/Ubuntu、Fedora、openSUSE、Alpine、Void、Gentoo 等）。随仓库提供 Linux x86_64 的独立 Python 3.12 运行时与依赖 wheels，安装到 `~/.local/lib/vp-helper`，不需要 root。

```bash
git clone https://github.com/thedyingkai/vp-helper.git
cd vp-helper
./vp-install-portable.sh install
```

安装后可在任意目录使用 `vp` 和 `submit`。Python 运行时与依赖可从仓库离线安装。

tmux 是唯一的系统依赖，安装器不会替你安装：

```bash
# Arch
sudo pacman -S tmux
# Debian / Ubuntu
sudo apt install tmux
# Fedora
sudo dnf install tmux
```

其他子命令：

```bash
./vp-install-portable.sh env       # 打印需要 source 的环境变量
./vp-install-portable.sh check     # 自检
./vp-install-portable.sh uninstall # 卸载（含 ~/.config/vp 账号配置）
```

安装器支持的环境变量：`VP_ROOT`（安装根目录）、`VP_STATE_DIR`、`VP_PYTHON`、`VP_USE_UV`、`VP_START_FILE`、`VP_ASK_COOKIE`。

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

按提示依次输入 handle 和四个 Cookie（`__Host-UOJREMEMBER`、`__Host-UOJSESSID`、`cf_clearance`、`uoj_preferred_language`），其中 `__Host-UOJSESSID` 必填。只复制 `=` 后面的值，不要带 `Cookie:` 前缀或 `Path=` 属性。

也可以先在 Firefox 登录 QOJ，再运行比赛命令。`vp` 和内置 `submit` 自动读取 Firefox 的登录状态，并通过网站导航中的登录用户核对账号；未填写 handle 时也可以从已验证的浏览器登录自动取得。配置保存在 `~/.config/vp/config.json`（设置 `XDG_CONFIG_HOME` 时为 `$XDG_CONFIG_HOME/vp/config.json`），权限为 600；也可以参考 `config.example.json` 填写。

自动读取支持 Firefox 的普通安装及 Ubuntu Snap 目录，读取该网站的持久 Cookie 和最新会话恢复记录；其他网站及容器、隐私会话不参与导入。程序只读取浏览器文件。验证通过后将登录数据保存到本地配置，账号不匹配或网络验证失败时保留原配置。GET 遇到登录过期会重新读取并验证一次；启动 VP 和提交代码的 POST 不自动重发。Firefox 尚未保存新会话时稍候再运行命令，或登录时勾选“记住我”。

登录过期时，在 Firefox 重新登录同一个账号，再运行原命令即可，无需复制 Cookie。多 Firefox 配置可在对应平台账号中指定 `firefox_profile` 为该 profile 的完整路径；sudo 启动时默认使用原普通用户的 Firefox。root 与普通用户的应用配置仍分别保存，root 使用 `/root/.config/vp/config.json`，普通用户使用自己的 `~/.config/vp/config.json`。

已有手动配置也可继续使用。要固定使用手动 Cookie，在账号中设置 `"cookie_source": "manual"`；填写 `cookie` 时只复制请求中 `Cookie` 的值，省略 `Cookie:` 标签和其他请求头。

每场比赛在桌面共用一个目录，例如 `2024 ICPC Nanjing Reg`。再次进入保留已有代码和输入数据，更新提交配置与题面；各次 VP 的开始时间和成绩状态独立保存。`submit A.cpp` 在对应比赛目录内运行。

请用同一个 Linux 用户运行 `vp` 和 `submit`；root 与普通用户的桌面目录和 VP 状态互相独立。QOJ 提交器会在当前目录、源码所在目录及其上级目录查找 `contest.json`，因此也支持从子目录提交或在别处指定源码路径。当前目录与源码绑定不同比赛、账号或题号时会要求切换到源码的比赛目录；同场同账号的配置以当前目录为准。找不到配置时给出恢复指引。重新运行同一场 `vp` 命令会补齐或刷新提交配置，沿用已经确认的原站开始时间。

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

QOJ 已完成真实账号联调，包括南京、香港和辽宁省赛的正式排名、奖项和提交记录。

## 赛时排名与统计

首次运行比赛命令时，程序根据平台 ID 读取比赛信息，自动获取该场原赛资格、榜单和提交记录。有完整原赛提交记录时，先用它重算终榜，与平台每支队伍的每题结果和罚时核对，再按 VP 当前时间每秒回放原赛成绩，计算当前排名与统计。QOJ 使用 SRK 或 XCPCIO 原赛记录。

有待判提交时，在上一轮查询返回后约 2 秒再次查询本人判定；其余时间约 5 秒，网络故障时退避重试（5→10→20→40→60 秒封顶）。平台榜单约 30 秒重新核对；这些间隔不包含网络耗时。

QOJ 在 VP 进行中返回的账号榜单已经按当前时间截断，程序使用不携带登录凭据的独立会话读取公开完整终榜来校验回放。档案时间窗口或 QOJ 导入时间与原站 VP 有差异时，分别处理；只有统一时间偏移后的全部终榜结果一致，才接受时间对齐。本人计时和补题分界仍按 QOJ 原站的 VP 时长。导出记录中的管理员测试提交不属于参赛队伍，不计入回放。正式与打星队伍的每题结果仍须和原站终榜逐一一致，才会显示实时排名与统计。

- `submitted`：首次通过前的有效计分提交次数，含待判。
- `attempted`：有有效尝试的正式队伍数。
- `accepted`：通过的正式队伍数。

统计包含本人赛内提交，排除打星和赛后补题；编译错误按本场计分规则处理。封榜时公开统计隐藏冻结后的结果，rank 显示 `?`，当前 VP 的原站解封后恢复。缺少资格数据或完整事件记录时，面板显示具体原因；只有终榜时，赛时排名与统计保持 `—`。奖项只使用明确的原赛奖牌配置。

2026 年起的 CCPC 区域赛自动启用题号揭示：某题被 50 支不同的原赛队伍通过后，才在公开统计中显示题号，正式队和打星队一并计数，当前 VP 不参与这个阈值。排名、奖项和上面的三项公开统计仍按正式参赛资格计算。尚未揭示的题号及对应统计显示为 `?`，匿名列集中排列，避免从 A–M 的位置推断题号。本人每题成绩与提交记录仍按实际题号显示。到原站规定的封榜时刻，所有题号同时揭示，公开统计固定在封榜前，原站解封后恢复完整结果。

例如 `vp qoj 4582` 会识别为 `2026 CCPC Changchun Reg`，采用 5 小时赛长、4 小时封榜。比赛名称中的 `Site` 及中英文双语标题均可识别；其他人的较短 rated VP 时长不再覆盖公开比赛时长。QOJ 目前仍以传统 ICPC 规则运行该场原站 VP，题号揭示由本地面板模拟。

省赛同样可以识别。例如 `vp qoj 2642` 的标题是「（2025）第六届辽宁省大学生程序设计竞赛 (沈阳)」，会被识别为 `2025 CCPC 辽宁 Pro`，并在桌面上创建同名目录。识别时按以下线索归类：标题里的 ICPC / CCPC 字样、「国际大学生程序设计竞赛」「中国大学生程序设计竞赛」等中文全称、34 个省级行政区名，以及 `Regional` / `Invitational` / `Provincial`、`区域` / `邀请` / `省赛` 等赛别词。东北地区合并赛需要标题写作「东北地区」「东北赛区」或「东北三省」，单独出现「东北」二字（如东北林业大学）不算。

这里有一个已知边界：像「辽宁省大学生程序设计竞赛」这种既没写 ICPC/CCPC、也没写「省赛」的标题，只能靠「省级行政区 + 大学生程序设计竞赛」推出是省赛。若某场比赛的标题是不带省份、不带系列词的纯英文或纯中文简写，仍会在开赛前报「无法识别年份、站点和赛别」。

## 浏览器回放（融合的 xcpc-vp）

`vp qoj ID` 在 tmux 会话建好后，会打印一个网页地址，**由你自己在浏览器里打开**。程序不调用任何系统打开器，因为 `xdg-open` 等工具在不同发行版、不同桌面会话和 `$DISPLAY` / `$WAYLAND_DISPLAY` 环境下行为不一致，经常静默失败。

这是**附加功能**：网页端不可用时终端面板一切照常，只打印一行提示。

**网页先于 QOJ 开赛**。整个流程会在程序向 QOJ 请求开启原生 VP 之前走完，所以等你打开网页时 `Starting and verifying native virtual participation…` 那一行还没出现：

1. 下载题面后，先问队伍名称和学校。填了才有网页榜上的自己的行；队名留空则跳过整个网页流程，终端面板照常工作。
2. 启动本地服务并打印页面地址，由你手动在浏览器打开。
3. 等你按回车确认网页已在运行，检查页面与同步接口，然后**才**向 QOJ 请求开启原生 VP。
4. QOJ 返回真实开始时间后，再打印一次带正确 `at` 的地址，让你刷新页面，使网页计时与评测机计时对齐。

只在全新会话时问；`Ctrl+B`、`D` 脱离后再进来不会重复询问。

状态提示全部使用英文，例如：

```text
xcpc-vp: page serving, feed answered (1 submissions mirrored)
```

开赛后：

```text
Native VP started at 2026-11-05T12:11:46+08:00.
Reload the replay so its clock matches the judge:
  http://127.0.0.1:5174/?contest=lncpc6th&...
```

为什么开赛前那次 `at` 是当前时刻：首场比赛在 QOJ 上还没有登记，只有提交 `regvir` 之后才产生开始时间。所以先按"现在"打开，开赛后再用真实时间重发地址。已登记的比赛（`Ctrl+B`、`D` 后重进）会直接读到原时间。

页面地址形如：

```text
http://127.0.0.1:5174/?contest=lncpc6th&team=队名&organization=学校&play=1&at=2026-11-15T09:00:00%2B08:00
```

`at` 使用 QOJ 上该次 VP 的实际开始时间，所以网页计时与终端计时共用同一个零点，同步过去的提交时间也落在同一秒。

比赛按标题自动匹配 RankLand 合集。匹配规则是同一系列、同一站点，且年份或届数一致，取字符重合最长的候选；仍并列时优先系列目录（如 `ccpc2025harbin`）而不是省赛目录（如 `jxccpc2nd`），两者指向同一份榜单。匹配不到时地址里不带 `contest` 参数，打开的是选赛页，由你手选，程序不猜。

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

SRK 档案按名称定位：区域赛查 `official/{ccpc,icpc}/{年}/`，省赛先查系列目录再查 `official/provincial/{省份拼音缩写}/`，然后逐个读取文件内的 `contest.title.zh-CN` 与平台标题比对。省份目录用两位拼音首字母，东北地区合并赛固定为 `northeast`。SRK 档案须明确标记正式参赛资格，且题目链接与当前 QOJ 比赛的全部题目 ID 一致；提交记录须逐题复算并与 QOJ 公开终榜匹配，才启用赛时回放。学校、队名、成员等身份信息完全一致且仅有一份非空记录的换账号空记录会被排除；存在多份实际参赛记录时保留校验失败提示。

省赛的 `zh-CN` 标题通常只写届数（如「第六届辽宁省大学生程序设计竞赛」），年份从档案自身的 `startAt` 读取。SRK 与 XCPCIO 的两类导出在罚时取整方式上不同：省级导出把每题解出时间分别向下取整到分钟，系列导出保留精确秒数；程序按档案自身声明的总分自动判定，不按路径硬编码。

生成的数据保存在用户自己的 `~/.cache/vp/originals/`（设置 `XDG_CACHE_HOME` 时使用 `$XDG_CACHE_HOME/vp/originals/`），后续使用复用缓存。缓存可以删除，下次使用会重新获取；首次获取需要网络。不需要修改仓库或手动添加比赛 JSON 文件。无法取得完整可靠原赛数据的比赛，仍显示本人成绩和提交，并说明参考排名或统计缺失的原因。XCPCIO 的 MIT 许可证保留在 `third_party/xcpcio/LICENSE`。

SRK Collection 的档案按其 AGPL-3.0 许可证提供，来源和许可证保留在 `third_party/srk/`；仓库仅包含独立编写的档案读取器，不内置 SRK 比赛数据或组件代码。

提交器来自 [hikariyo 的 QOJ submit.py](https://gist.github.com/hikariyo/b3cec2e736d87be57d1e4faafb04f908)，固定版本、兼容补丁与现有许可证保存在 `third_party/qoj/`。Python 运行时的来源与校验值见 `runtimes/manifest.json`。

`web/` 中并入了 xcpc-vp 前端，它基于 [algoux/standard-ranklist](https://github.com/algoux/standard-ranklist)、[algoux/rankland-web](https://github.com/algoux/rankland-web) 与 [RankLand](https://rl.algoux.cn/) 榜单数据，许可证边界见 `web/README.md`。

本仓库仅包含运行程序、安装依赖和使用文档；比赛数据、测试代码、测试样例、账号配置及个人比赛文件不纳入仓库。
