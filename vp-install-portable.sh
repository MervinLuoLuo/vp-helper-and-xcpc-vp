#!/bin/bash
# 让 vp-helper 在任何 Linux 发行版上可用 —— 不用 install.sh，也不碰系统文件。
#
# 用法（在仓库根目录执行）:
#   ./vp-install-portable.sh install      # 安装到 ~/.local/lib/vp-helper
#   ./vp-install-portable.sh env          # 打印需要 source 的环境变量
#   ./vp-install-portable.sh check        # 检查依赖和隔离装好的 vp 是否可用
#   ./vp-install-portable.sh uninstall    # 删除本次安装（含 ~/.config/vp 账号配置）
#
# 安装结果（全部在你的家目录下，不写 /usr、/opt、/etc）:
#   $VP_ROOT/venv                     项目 venv（vp + submit 依赖）
#   $VP_ROOT/app/vp_helper            程序源码
#   $VP_ROOT/app/third_party          提交脚本（整份复制，仓库原件不动）
#   $VP_ROOT/bin/vp, bin/submit       启动入口
#   $VP_ROOT/config/vp/config.json    账号配置（600）
#   $VP_ROOT/state/, cache/           运行状态与缓存
#
# 可选环境变量（在运行 install 前设置）:
#   VP_ROOT       安装根目录，默认 $HOME/.local/lib/vp-helper
#   VP_STATE_DIR  venv 之外的状态目录，默认 $VP_ROOT/state
#   VP_PYTHON     Python 解释器（路径或命令）。不设时: 3.12 → uv → 自带运行时
#   VP_START_FILE 如果安装成功，写一个 source 该文件即可导出环境变量
set -euo pipefail

SRC="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VP_ROOT="${VP_ROOT:-$HOME/.local/lib/vp-helper}"
VP_STATE_DIR="${VP_STATE_DIR:-$VP_ROOT/state}"
VP_BIN="$VP_ROOT/bin"
VENV="$VP_ROOT/venv"
WHEELS="$SRC/wheels"
GUI=""

# 找到"真正的用户家目录"（脚本可能以 sudo 运行）
find_home() {
    if [[ -n "${SUDO_USER:-}" && "$SUDO_USER" != root ]]; then
        getent passwd "$SUDO_USER" | cut -d: -f6
    else
        printf '%s' "$HOME"
    fi
}
USER_HOME="$(find_home)"

# PATH 里还没有 $VP_BIN 时（比如刚装完、当前 shell 没重新登录），给 vp 子进程补上，
# 否则 cli.py 用 shutil.which("submit") 找不到提交脚本。
ensure_path() {
    case ":$PATH:" in
        *":$VP_BIN:"*) ;;
        *) export PATH="$VP_BIN:$PATH" ;;
    esac
    # QOJ 的 submit 脚本要通过解释器找到 vp_helper 包；venv 的 site-packages 里虽然有
    # editable 安装（开发模式），下面这行保证任何拷贝方式都能 import。
    export PYTHONPATH="$VP_ROOT/app${PYTHONPATH:+:$PYTHONPATH}"
}

die()  { printf '\n%s\n' "错误: $*" >&2; exit 1; }
info() { printf '  %s\n' "$*"; }
step() { printf '\n==> %s\n' "$*"; }

# ---------------------------------------------------------------------------
# 发行版识别（只用来给出提示，不决定安装方式）
# ---------------------------------------------------------------------------
detect_os() {
    local id="" id_like="" ver=""
    if [[ -r /etc/os-release ]]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        id="${ID:-}"
        id_like="${ID_LIKE:-}"
        ver="${PRETTY_NAME:-${NAME:-} ${VERSION_ID:-}}"
    fi
    OS_ID="$id"; OS_LIKE="$id_like"; OS_PRETTY="${ver:-unknown}"

    # 包管理器名（只用 -S 装 tmux 时提示）
    PKG=""
    if   command -v pacman  >/dev/null 2>&1; then PKG="pacman"
    elif command -v apt-get >/dev/null 2>&1; then PKG="apt"
    elif command -v dnf     >/dev/null 2>&1; then PKG="dnf"
    elif command -v zypper  >/dev/null 2>&1; then PKG="zypper"
    elif command -v apk     >/dev/null 2>&1; then PKG="apk"
    elif command -v xbps-install >/dev/null 2>&1; then PKG="xbps"
    elif command -v emerge  >/dev/null 2>&1; then PKG="emerge"
    fi

    # 判断是否滚动/非 Ubuntu，用来提示"运行时代码只校验 Linux，不校验发行版"
    case "$PKG" in
        pacman|apk|xbps) ROLLING=1 ;;
        *)              ROLLING=0 ;;
    esac
}

tmux_hint() {
    case "$PKG" in
        pacman)  echo "  sudo pacman -S --needed tmux" ;;
        apt)     echo "  sudo apt-get update && sudo apt-get install -y tmux" ;;
        dnf)     echo "  sudo dnf install -y tmux" ;;
        zypper)  echo "  sudo zypper install -y tmux" ;;
        apk)     echo "  sudo apk add tmux" ;;
        xbps)    echo "  sudo xbps-install -S tmux" ;;
        emerge)  echo "  sudo emerge -av app-misc/tmux" ;;
        *)       echo "  用你的包管理器装 tmux（如 nix-env -i tmux、在容器里用 apk add tmux）" ;;
    esac
}

# ---------------------------------------------------------------------------
# 解释器选择
# ---------------------------------------------------------------------------
pick_python() {
    # uv is the only source of Python: it downloads a portable 3.12 that works on
    # every distribution and on macOS, so nothing distro-specific is bundled.
    if [[ -n "${VP_PYTHON:-}" ]]; then
        local given=""
        if [[ -x "$VP_PYTHON" ]]; then
            given="$VP_PYTHON"
        elif command -v "$VP_PYTHON" >/dev/null 2>&1; then
            given="$(command -v "$VP_PYTHON")"
        fi
        if [[ -z "$given" ]]; then
            printf ''; VP_PYTHON_BAD="$VP_PYTHON"; return 1
        fi
        # Dependencies are cp312 wheels, so 3.13/3.14 cannot be installed.
        if "$given" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)' 2>/dev/null; then
            printf '%s' "$given"; return 0
        fi
        printf ''; VP_PYTHON_BAD="$VP_PYTHON"; return 1
    fi
    if command -v uv >/dev/null 2>&1; then
        printf '%s' "__UV__"; return 0
    fi
    printf ''; return 1
}

# uv 下载 Python 需要可写的缓存与 Python 安装目录
export_uv_dirs() {
    export UV_CACHE_DIR="${UV_CACHE_DIR:-$VP_ROOT/.uv-cache}"
    export UV_PYTHON_INSTALL_DIR="${UV_PYTHON_INSTALL_DIR:-$VP_ROOT/.uv-python}"
    mkdir -p "$UV_CACHE_DIR" "$UV_PYTHON_INSTALL_DIR"
}

create_venv() {
    local py="$1"
    rm -rf "$VENV"
    if [[ "$py" == "__UV__" ]]; then
        command -v uv >/dev/null 2>&1 \
            || die "找不到 uv。请先安装: curl -LsSf https://astral.sh/uv/install.sh | sh（或 brew install uv）"
        export_uv_dirs
        info "使用 uv 创建 venv（--python 3.12）"
        # uv 会先自己下载 Python 3.12；若失败，下面的提示会告诉你怎么换解释器
        if ! uv venv --python 3.12 "$VENV"; then
            die "uv 没能提供一个 Python 3.12。请检查网络，或设置 VP_PYTHON=/path/to/python3.12 重试"
        fi
    else
        info "使用解释器: $py"
        if "$py" -m venv "$VENV" 2>/dev/null \
           && "$VENV/bin/python" -c 'import venv, ensurepip' 2>/dev/null; then
            :
        else
            # 有些发行版把 ensurepip 拆到单独的包
            die "无法用 $py 创建 venv。请安装 venv/ensurepip，或不设 VP_PYTHON 让 uv 下载 Python 3.12"
        fi
    fi
    "$VENV/bin/python" -V
    "$VENV/bin/python" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)' \
        || die "venv 的 Python 不是 3.12（$("$VENV/bin/python" -V)），依赖 wheel 为 cp312，无法离线安装"
}

install_deps() {
    local source="$SRC"
    [[ -d "$VP_ROOT/app" ]] && source="$VP_ROOT/app"
    # The vendored wheels are Linux x86_64 only. cffi and curl_cffi are native
    # extensions, so another platform has to resolve them from PyPI.
    local offline=1
    if [[ "$(uname -s)" != "Linux" || "$(uname -m)" != "x86_64" ]]; then
        offline=0
        info "非 Linux x86_64：改为从 PyPI 安装（需要网络）"
    fi
    # submit only needs bs4 and the standard library; the rest come from the
    # project's own pyproject.toml. Dropping unused native deps also keeps the
    # macOS path to pure wheels.
    local -a args=(-e "$source")
    if [[ "$offline" == 1 ]]; then
        args=(--no-index --find-links "$WHEELS" "${args[@]}")
    fi
    if ! "$VENV/bin/python" -m pip --version >/dev/null 2>&1; then
        # uv 创建的 venv 可能没有 pip，用 uv 装即可
        command -v uv >/dev/null 2>&1 || die "venv 中没有 pip，且找不到 uv"
        export_uv_dirs
        uv pip install --python "$VENV/bin/python" "${args[@]}"
        return
    fi
    "$VENV/bin/python" -m pip install --disable-pip-version-check "${args[@]}"
}

# ---------------------------------------------------------------------------
# 源码处理：复制（不动 git 工作区）、给提交脚本换 shebang、打 relocatable 补丁
# ---------------------------------------------------------------------------
# 把脚本第一行换成给定的 shebang。BSD 与 GNU 的 sed -i 参数形式不同，
# 直接重写文件可以跨平台，不依赖任何 sed 实现。
rewrite_shebang() {
    local file="$1" python="$2"
    local first
    IFS= read -r first < "$file" || true
    printf '#!%s\n' "$python" > "$file.new"
    tail -n +2 "$file" >> "$file.new"
    mv "$file.new" "$file"
}

stage_app() {
    rm -rf "$VP_ROOT/app"
    mkdir -p "$VP_ROOT/app"
    cp -a "$SRC/vp_helper" "$SRC/pyproject.toml" "$VP_ROOT/app/"
    cp -a "$SRC/third_party" "$VP_ROOT/app/third_party"
    # The merged xcpc-vp front end: vp serves its prebuilt dist without Node.
    mkdir -p "$VP_ROOT/app/web"
    if [[ -d "$SRC/web/dist" ]]; then
        cp -a "$SRC/web/dist" "$VP_ROOT/app/web/dist"
    else
        printf '  注意: 未找到 web/dist，vp 将回退到 pnpm dev（需要 Node）。\n'
    fi

    local f
    for f in "$VP_ROOT/app/third_party/qoj/submit"; do
        # 原脚本首行写死 /opt/vp-helper/current/venv/bin/python；改用本项目 venv。
        # 用 bash 重写而非 sed -i：BSD sed 要求 -i 带后缀参数，不同于 GNU sed。
        rewrite_shebang "$f" "$VENV/bin/python"
        chmod 755 "$f"
    done

    patch_app
}

# 打一个可重复执行的补丁：去掉 cli.py 里两处对 /opt/vp-helper 的硬编码依赖。
# - configure_submit 里 bundled 判定改成 realpath 兼容，并自动创建 state 目录
# - bundled 目录从解析后的 submit 路径推导，而不是 /opt/vp-helper/current/third_party
patch_app() {
    local f="$VP_ROOT/app/vp_helper/cli.py"
    [[ -f "$f" ]] || die "找不到 $f"
    if grep -q 'found = Path(resolved).parent.parent' "$f"; then
        info "cli.py 已包含 relocatable 补丁，跳过"
        return
    fi
    "$VENV/bin/python" - "$f" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text(encoding="utf8")

old_bundled = ('    bundled = bool(script and Path(script).is_symlink() '
               'and Path(os.readlink(script)) == selected)\n')
new_bundled = ('    resolved = os.path.realpath(script) if script else ""\n'
               '    bundled = bool(script and Path(script).exists() and\n'
               '                   (resolved == os.path.realpath(selected)\n'
               '                    or os.path.basename(resolved) == "submit" and\n'
               '                    Path(resolved).parent.parent.name == "third_party"))\n')

old_tool = ('        tool = Path("/opt/vp-helper/current/third_party") / "qoj" / "submit"\n')
new_tool = ('        found = Path(resolved).parent.parent\n'
            '        tool = found / "qoj" / "submit"\n')

old_mkdir = '        temporary.unlink(missing_ok=True)\n'
new_mkdir = ('        selected.parent.mkdir(parents=True, exist_ok=True, mode=0o700)\n'
             '        temporary.unlink(missing_ok=True)\n')

missing = [name for name, old in (("bundled", old_bundled), ("third_party", old_tool), ("unlink", old_mkdir))
           if text.count(old) != 1]
if missing:
    raise SystemExit("cli.py 结构与预期不符（%s 未找到恰好一次），请检查上游版本" % ", ".join(missing))

text = (text.replace(old_bundled, new_bundled)
            .replace(old_tool, new_tool)
            .replace(old_mkdir, new_mkdir))
path.write_text(text, encoding="utf8")
PY
    info "已打 relocatable 补丁（/opt/vp-helper → $VP_ROOT/app）"
}

# vp 用 config_directory() = ${XDG_CONFIG_HOME:-~/.config}/vp 读取账号；安装器必须写到
# 同一个位置，否则 ask_cookie_source、handle、cookie 全部读不到。
config_file() {
    printf '%s' "$(cfg_root)/vp/config.json"
}
cfg_root() {
    if [[ -n "${XDG_CONFIG_HOME:-}" ]]; then
        printf '%s' "$XDG_CONFIG_HOME"
    else
        printf '%s' "$USER_HOME/.config"
    fi
}

migrate_config() {
    local legacy="$VP_ROOT/config/vp/config.json" cfg; cfg="$(config_file)"
    [[ -f "$legacy" && ! -f "$cfg" ]] || return 0
    mkdir -p "$(dirname "$cfg")"
    cp -a "$legacy" "$cfg"
    chmod 600 "$cfg"
    info "迁移配置: $legacy → $cfg"
}

# 询问比赛目录的保存位置。已配置时回车保留，VP_WORK_DIR 可跳过交互。
ask_work_dir() {
    local cfg; cfg="$(config_file)"
    local current=""
    if [[ -f "$cfg" ]]; then
        current="$("$VENV/bin/python" -c 'import json,sys;print(json.load(open(sys.argv[1],encoding="utf8")).get("work_directory",""))' "$cfg" 2>/dev/null || true)"
    fi
    if [[ -n "${VP_WORK_DIR:-}" ]]; then
        WORK_DIR="$VP_WORK_DIR"
    elif [[ -t 0 ]]; then
        local prompt="比赛目录保存位置"
        [[ -n "$current" ]] && prompt="$prompt [$current]"
        printf '  %s: ' "$prompt"
        read -r answer || answer=""
        WORK_DIR="${answer:-$current}"
    else
        WORK_DIR="$current"
    fi
    if [[ -z "$WORK_DIR" ]]; then
        printf '  需要一个目录来放比赛文件夹和 vp_history.csv。\n' >&2
        printf '  重新运行并输入路径，或设置 VP_WORK_DIR=/path/to/dir\n' >&2
        exit 1
    fi
    WORK_DIR="${WORK_DIR/#\~/$HOME}"
    mkdir -p "$WORK_DIR" || die "无法创建目录: $WORK_DIR"
    WORK_DIR="$(cd "$WORK_DIR" && pwd)"
    info "比赛目录: $WORK_DIR"
}

write_config() {
    local cfg; cfg="$(config_file)"
    local dir; dir="$(dirname "$cfg")"
    mkdir -p "$dir" "$VP_STATE_DIR/vp" "$VP_ROOT/cache"
    chmod 700 "$dir" "$VP_STATE_DIR" "$VP_STATE_DIR/vp"
    if [[ -f "$cfg" ]]; then
        # 只补齐缺的键，不覆盖你已有的账号信息
        "$VENV/bin/python" - "$cfg" "$VP_BIN/submit" "$WORK_DIR" <<'PY'
import json, os, sys
from pathlib import Path

path = Path(sys.argv[1])
submit = sys.argv[2]
work_dir = sys.argv[3]
cfg = json.loads(path.read_text(encoding="utf8") or "{}")
changed = False
if cfg.get("work_directory") != work_dir:
    cfg["work_directory"] = work_dir
    changed = True
for key in ("qoj",):
    account = cfg.setdefault(key, {})
    defaults = {"handle": "", "cookie_source": "manual", "cookie": ""}
    defaults["submit_script"] = submit
    for name, value in defaults.items():
        if name not in account:
            account[name] = value
            changed = True
    # 已经配好登录的账号，不要覆盖它选的 submit；但如果没有 submit 就补上
cfg.setdefault("qoj", {}).setdefault("submit_script", submit)
if cfg["qoj"].get("submit_script") == "/usr/local/bin/submit":
    cfg["qoj"]["submit_script"] = submit
    changed = True
if changed:
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
os.chmod(path, 0o600)
PY
    else
        cat > "$cfg" <<EOF
{
  "work_directory": "$WORK_DIR",
  "qoj": {
    "handle": "",
    "cookie": "",
    "submit_script": "$VP_BIN/submit"
  }
}
EOF
        chmod 600 "$cfg"
    fi
    info "配置: $cfg"
}

link_entry() {
    mkdir -p "$VP_BIN"
    ln -sfn "$VENV/bin/vp"                        "$VP_BIN/vp"
    ln -sfn "$VP_ROOT/app/third_party/qoj/submit" "$VP_BIN/submit"
    # 约定：state 目录下 submit 软链到 bundled 脚本；state 用 XDG_STATE_HOME 重定向
    ln -sfn "$VP_ROOT/app/third_party/qoj/submit" "$VP_STATE_DIR/vp/submit"
}

# ---------------------------------------------------------------------------
# 子命令
# ---------------------------------------------------------------------------
cmd_env() {
    local start="${VP_START_FILE:-}"
    {
        echo "export VP_ROOT=\"$VP_ROOT\""
        echo "export PATH=\"$VP_BIN:\$PATH\""
        # 隔离状态/缓存；配置留在 vp 默认位置 $HOME/.config/vp，否则 vp 读不到账号
        echo "export XDG_STATE_HOME=\"$VP_STATE_DIR\""
        echo "export XDG_CACHE_HOME=\"$VP_ROOT/cache\""
    } >&2
    if [[ -n "$start" ]]; then
        mkdir -p "$(dirname "$start")"
        {
            echo "# 由 vp-install-portable.sh 生成；source 本文件即可使用 vp"
            echo "export VP_ROOT=\"$VP_ROOT\""
            echo "export PATH=\"$VP_BIN:\$PATH\""
            echo "export XDG_STATE_HOME=\"$VP_STATE_DIR\""
            echo "export XDG_CACHE_HOME=\"$VP_ROOT/cache\""
        } > "$start"
    fi
}

cmd_install() {
    local py=""
    printf '发行版: %s (%s；包管理器 %s)\n' "$OS_PRETTY" "${OS_ID:-?}" "${PKG:-未识别}"
    [[ "$ROLLING" == 1 ]] && info "非 Ubuntu 系，可以继续：程序只校验 Linux，不校验发行版"

    step "检查 tmux"
    if command -v tmux >/dev/null 2>&1; then
        info "tmux: $(tmux -V)"
    else
        printf '  tmux 未安装。它是系统包，脚本不会替你装，请手动执行:\n'
        tmux_hint
        die "请先安装 tmux，然后重新运行: $0 install"
    fi

    step "准备目录"
    mkdir -p "$VP_ROOT" "$VP_BIN" "$VP_STATE_DIR/vp" "$VP_ROOT/cache"
    chmod 700 "$VP_ROOT" "$VP_STATE_DIR" "$VP_STATE_DIR/vp" 2>/dev/null || true
    info "$VP_ROOT"

    step "选择 Python 3.12"
    py="$(pick_python)" || true
    if [[ -z "$py" ]]; then
        if [[ -n "${VP_PYTHON_BAD:-}" ]]; then
            printf 'VP_PYTHON=%s 不是 Python 3.12（依赖 wheel 是 cp312，3.13/3.14 不兼容）。\n' "$VP_PYTHON_BAD" >&2
        fi
        cat >&2 <<EOF
找不到可用的 Python 3.12（依赖 wheel 是 cp312，3.13/3.14 不兼容）。
可选做法（任选一种后重跑）:
  - 安装 3.12:  Debian/Ubuntu sudo apt install python3.12 python3.12-venv
                Fedora        sudo dnf install python3.12
                Arch          sudo pacman -S python312  (需要 AUR/发行版提供)
  - 安装 uv 后重跑（uv 会自动下载 3.12）:  curl -LsSf https://astral.sh/uv/install.sh | sh
  - 已有 3.12 时直接指定:  VP_PYTHON=/path/to/python3.12 $0 install
EOF
        exit 1
    fi

    step "创建 venv"
    create_venv "$py"

    step "复制源码并为提交脚本换 shebang"
    stage_app

    step "离线安装依赖（${WHEELS}）"
    install_deps

    step "写入入口与配置"
    link_entry
    migrate_config
    step "比赛目录"
    ask_work_dir
    write_config

    step "验证"
    ensure_path
    "$VP_BIN/vp" --help
    "$VP_BIN/submit" --help
    cmd_env

    cat <<EOF

安装完成。为了让当前 shell 生效，执行:

  export PATH="$VP_BIN:\$PATH"
  export XDG_STATE_HOME="$VP_STATE_DIR"
  export XDG_CACHE_HOME="$VP_ROOT/cache"

想永久生效，把这 3 行加到 ~/.bashrc 或 ~/.zshrc（或用 VP_START_FILE 再跑一次 install）。

下一步:
  1. 在浏览器登录 QOJ，取 Cookie 填到:
       $(config_file)
     （handle 必填；Cookie 只复制 "=" 后面的值，不要带 Cookie: 前缀）
  2. 验证:  vp qoj <比赛ID>

注意:
  - 比赛目录: ${WORK_DIR}（存在 config.json 的 work_directory）
    要改位置: 重跑 install 并输入新路径，或直接编辑 work_directory。
  - 卸载:  $0 uninstall   （同时删除程序、状态、缓存和账号配置 ~/.config/vp）
EOF
}

cmd_check() {
    local ok=0 root="$VP_ROOT"
    step "环境"
    info "发行版: $OS_PRETTY"
    printf '  %-22s %s\n' "kernel" "$(uname -sr)"
    printf '  %-22s %s\n' "arch" "$(uname -m)"
    printf '  %-22s %s\n' "VP_ROOT" "$root"
    printf '  %-22s %s\n' "state dir" "$VP_STATE_DIR"

    step "外部依赖"
    if command -v tmux >/dev/null 2>&1; then
        printf '  ✔ %-20s %s\n' tmux "$(command -v tmux)"
    else
        printf '  ✘ %-20s 缺失，安装方式:\n' tmux; tmux_hint; ok=1
    fi

    step "比赛目录"
    local work
    work="$("$root/venv/bin/python" -c 'from vp_helper.storage import desktop; print(desktop())' 2>&1 || true)"
    if [[ "$work" == /* && -d "$work" && -w "$work" ]]; then
        printf '  ✔ %-20s %s\n' "work dir" "$work"
    else
        printf '  ✘ %-20s %s\n' "work dir" "$work"
        printf '     重跑 install 并输入一个可写目录\n'
        ok=1
    fi

    step "安装文件"
    for f in "$root/venv/bin/vp" "$root/app/third_party/qoj/submit" \
             "$root/config/vp/config.json"; do
        if [[ -e "$f" ]]; then printf '  ✔ %s\n' "$f"; else printf '  ✘ %s\n' "$f"; ok=1; fi
    done

    step "解释器与依赖"
    if [[ -x "$root/venv/bin/python" ]]; then
        printf '  %-22s ' "python"; "$root/venv/bin/python" -V
        "$root/venv/bin/python" - <<'PY'
import importlib, sys
mods = ("vp_helper.cli", "vp_helper.qoj", "requests", "bs4", "rich",
        "curl_cffi", "selectolax", "robobrowser", "lxml", "prettytable")
bad = [m for m in mods if not importlib.util.find_spec(m)]
print("  ✔ 依赖完整" if not bad else "  ✘ 缺少: " + ", ".join(bad))
sys.exit(1 if bad else 0)
PY
        [[ $? -ne 0 ]] && ok=1
    else
        printf '  ✘ 没有 venv，请先 install\n'; ok=1
    fi

    step "提交脚本 shebang"
    local shebang; shebang="$(head -n1 "$root/app/third_party/qoj/submit" 2>/dev/null || true)"
    if [[ -x "$root/venv/bin/python" && "$shebang" == "#!$root/venv/bin/python" ]]; then
        printf '  ✔ %s\n' "$shebang"
    else
        printf '  ✘ shebang 不是 %s（实际 %s）\n' "$root/venv/bin/python" "$shebang"; ok=1
    fi

    step "relocatable 补丁"
    if grep -q 'found = Path(resolved).parent.parent' "$root/app/vp_helper/cli.py" 2>/dev/null; then
        printf '  ✔ cli.py 不依赖 /opt/vp-helper\n'
    else
        printf '  ✘ cli.py 仍指向 /opt/vp-helper\n'; ok=1
    fi

    step "实际运行 vp"
    if [[ -x "$root/venv/bin/vp" ]]; then
        ensure_path
        if (cd /tmp && "$root/venv/bin/vp" --help >/dev/null 2>&1); then
            printf '  ✔ vp --help 正常\n'
        else
            printf '  ✘ vp --help 失败\n'; ok=1
        fi
        if (cd /tmp && "$root/app/third_party/qoj/submit" --help >/dev/null 2>&1); then
            printf '  ✔ submit --help 正常\n'
        else
            printf '  ✘ submit --help 失败\n'; ok=1
        fi
    fi

    step "网络（可选，仅判断能否访问比赛站点）"
    for host in qoj.ac api.github.com raw.githubusercontent.com; do
        # 可达即算通过，不看状态码：qoj.ac 对普通 TLS 指纹回 403 属预期（curl_cffi 才能过）
        if curl -s -o /dev/null -m 8 "https://$host/" 2>/dev/null; then
            printf '  ✔ %-26s 可达\n' "$host"
        else
            printf '  ⚠ %-26s 不可达/超时（403 也算通过；Cloudflare 站点对裸 curl 回 403 属正常）\n' "$host"
        fi
    done

    echo
    if [[ "$ok" == 0 ]]; then echo "结论: 安装完整，可以使用。"; else echo "结论: 存在需要处理的问题（见上方 ✘）。"; fi
    return "$ok"
}

cmd_uninstall() {
    local cfg_dir legacy_cfg cache_dir
    cfg_dir="$(cfg_root)/vp"
    legacy_cfg="$USER_HOME/.config/vp"
    cache_dir="${XDG_CACHE_HOME:-$VP_ROOT/cache}"

    # 配置目录同样是安装产物：不保留，否则重装会带着旧账号和过期 cookie 继续跑。
    local targets=() t
    for t in "$VP_BIN/vp" "$VP_BIN/submit"; do [[ -e "$t" ]] && targets+=("$t"); done
    for t in "$VP_ROOT" "$VP_STATE_DIR" "$cfg_dir" "$cache_dir" "$legacy_cfg"; do
        # 去重：XDG 未设置时 cfg_dir 与 legacy_cfg 相同；state/cache 常在 VP_ROOT 下。
        [[ -e "$t" ]] || continue
        local dup=0 seen
        for seen in "${targets[@]}"; do [[ "$seen" == "$t" ]] && dup=1 && break; done
        (( dup )) || targets+=("$t")
    done

    printf '将删除:\n'
    for t in "${targets[@]}"; do printf '  %s\n' "$t"; done
    [[ ${#targets[@]} -eq 0 ]] && printf '  (没有找到任何安装文件)\n'
    printf '保留: 比赛目录（config.json 的 work_directory）与其中的 vp_history.csv\n'
    if [[ -d "$cfg_dir" || -d "$legacy_cfg" ]]; then
        printf '注意: 账号配置（handle / cookie）也会被删除，无法恢复。\n'
    fi
    printf '继续? [y/N] '
    local answer; read -r answer || true
    if [[ "$answer" != "y" && "$answer" != "Y" ]]; then
        echo '已取消，未做任何修改。'
        return 0
    fi

    # 先删入口链接，再删目录；只操作上面确认存在的路径。
    rm -f "$VP_BIN/vp" "$VP_BIN/submit"
    rmdir "$VP_BIN" 2>/dev/null || true
    for t in "$VP_ROOT" "$VP_STATE_DIR" "$cfg_dir" "$cache_dir" "$legacy_cfg"; do
        [[ -e "$t" ]] && rm -rf "$t"
    done

    local left=0
    for t in "$VP_ROOT" "$cfg_dir" "$legacy_cfg"; do
        if [[ -e "$t" ]]; then printf '警告: 仍存在 %s\n' "$t" >&2; left=1; fi
    done
    if (( left )); then
        echo '卸载未完全成功，请检查上方警告。' >&2
        return 1
    fi
    echo '已卸载：程序、状态、缓存与账号配置均已删除。'
}

# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
detect_os
command="${1:-}"
case "$command" in
    install)
        [[ "$(id -u)" == 0 && -z "${SUDO_USER:-}" ]] && info "以 root 运行，将安装到 $VP_ROOT"
        cmd_install
        ;;
    env)        cmd_env ;;
    check)      cmd_check ;;
    uninstall)  cmd_uninstall ;;
    ""|-h|--help|help)
        cat <<EOF
用法: $0 <命令>

  install     安装到 \${VP_ROOT}（默认 ~/.local/lib/vp-helper）；需要 tmux 已安装
  env         打印需要 source 的环境变量
  check       检查依赖、安装完整性与连通性
  uninstall   删除本次安装，包括账号配置（~/.config/vp 或 \$XDG_CONFIG_HOME/vp）

可调环境变量: VP_ROOT  VP_STATE_DIR  VP_PYTHON  VP_START_FILE
EOF
        ;;
    *) echo "未知命令: ${command}（可选 install/env/check/uninstall）" >&2; exit 2 ;;
esac
