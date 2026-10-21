#!/bin/bash
# BudgetBuddy install.sh — 四平台安装器（CodeBuddy + OpenCode + Claude Code + Codex）
# 依据: design.md §10 / §12-A3/A7/A9/A12 / specs/installer/spec.md
#
# 用法:
#   bash install.sh                                     交互式选择平台与作用域
#   bash install.sh --global                            全局安装（跳过作用域交互）
#   BUDGET_PLATFORM=opencode BUDGET_GLOBAL=1 bash install.sh   纯非交互
#
# 环境变量:
#   BUDGET_REPO_URL   下载源（默认 GitHub raw 占位地址，推送远端后修正）
#   BUDGET_VERSION    指定版本 tag（默认经 releases/latest 发现最新版）
#   BUDGET_PLATFORM   平台 codebuddy|opencode|claudecode|both|all（跳过平台交互；
#                     all=三平台全部安装【推荐】；both=codebuddy+opencode 历史兼容）
#   BUDGET_GLOBAL     0=项目 / 1=全局（设置即跳过作用域交互）
#
# 安全（specs/installer「下载包完整性校验」/「manifest 增量同步」）:
#   - 在线模式下载 release zip 后强制 SHA256 校验，失败即中止、不进入安装
#   - 增量同步以 dist/<platform>/.manifest.json 为唯一依据，清单外文件一律保留
#   - 安装成功后写 <安装根>/.budget-manifest.json 本地清单（升级差集清理
#     与卸载依据；卸载入口 budget setup uninstall，离线可用）

set -euo pipefail

# ─── 可配置项（顶部；BUDGET_REPO_URL 为占位地址，推送远端后修正，§15-Q1）──
BUDGET_REPO_URL="${BUDGET_REPO_URL:-https://github.com/fxdgg/BudgetBuddy}"
BUDGET_VERSION="${BUDGET_VERSION:-}"

# ─── 全局状态 ──────────────────────────────────────────────────────────────
BUDGET_INSTALL_PLATFORM="codebuddy"   # codebuddy | opencode | claudecode | codex | both | all
BUDGET_INSTALL_GLOBAL=0               # 1=全局
BUDGET_SCOPE_EXPLICIT=0               # BUDGET_GLOBAL 环境变量已显式设置
BUDGET_PYTHON="${BUDGET_PYTHON:-}"
SHA256_CMD=""
BUDGET_SRC_ROOT=""                    # dist/ 的父目录（仓库根或 zip 解压根）
BUDGET_TMP_DIR=""
SUMMARY_OUTPUT=""

# 同步统计（install_* 内重置；进程替换循环在当前 shell，计数可传播）
SYNC_ADDED=0
SYNC_UPDATED=0
SYNC_SKIPPED=0
CLEANED=0

# ─── 输出辅助 ──────────────────────────────────────────────────────────────
if [[ -t 1 ]]; then
    RED=$'\033[0;31m'
    GREEN=$'\033[0;32m'
    YELLOW=$'\033[1;33m'
    CYAN=$'\033[0;36m'
    NC=$'\033[0m'
else
    RED=""
    GREEN=""
    YELLOW=""
    CYAN=""
    NC=""
fi

print_info()    { echo -e "${CYAN}[i]${NC} $1"; }
print_success() { echo -e "${GREEN}[✓]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[!]${NC} $1"; }
print_error()   { echo -e "${RED}[✗]${NC} $1" >&2; exit 1; }

show_help() {
    cat << 'EOF'
用法: bash install.sh [选项]

选项:
  --global     全局安装（跳过作用域交互；平台交互仍可用 BUDGET_PLATFORM 跳过）
  --version    显示版本信息
  --help       显示此帮助信息

安装模式:
  无参数       交互式选择平台（CodeBuddy / OpenCode / Claude Code / Codex / 全部）与作用域（项目/全局）
  --global     直接全局安装（所有项目共享）
  纯非交互     BUDGET_PLATFORM + BUDGET_GLOBAL 环境变量（CI / 脚本调用）

环境变量（BUDGET_* 前缀）:
  BUDGET_REPO_URL   下载源（默认 GitHub raw 占位地址，可指向自建镜像）
  BUDGET_VERSION    指定版本 tag（默认经 releases/latest 发现最新版）
  BUDGET_PLATFORM   codebuddy | opencode | claudecode | codex | both | all（跳过平台交互）
                    all = 四平台全部安装（推荐）；both = codebuddy+opencode（历史兼容值）
  BUDGET_GLOBAL     0=项目安装 / 1=全局安装（设置即跳过作用域交互）

安装落点:
  CodeBuddy  项目 → .codebuddy/          全局 → ~/.codebuddy/
             + 命令包装器 ~/.local/bin/budget + hooks 注入 settings.json
  OpenCode   项目 → .opencode/           全局 → ~/.config/opencode/
             + 管理面统一 ~/.budgetbuddy/（setup.sh/lib/models/personas/docs）
             + AGENTS.fragment.md 幂等合并进 AGENTS.md
  Claude Code 项目 → .claude/            全局 → ~/.claude/
             + 管理面统一 ~/.budgetbuddy/（与 OpenCode 共享）
             + CLAUDE.fragment.md 幂等合并进 CLAUDE.md
             + hooks 注入 settings.json（三事件通知）
  Codex      项目 → .codex/skills/       全局 → ~/.codex/skills/
             + 管理面统一 ~/.budgetbuddy/（与其他平台共享）
             + AGENTS.fragment.md 轻量区块合并进项目根 / ~/.codex/AGENTS.md
             + config.toml 注入 [features] multi_agent = true（spawn 工具前提）
EOF
}

show_version() {
    local script_dir="" version=""
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd -P)" || script_dir=""
    if [[ -n "$script_dir" && -f "$script_dir/VERSION" ]]; then
        version="$(tr -d '[:space:]' < "$script_dir/VERSION")"
    fi
    if [[ -n "$version" ]]; then
        echo "BudgetBuddy installer（仓库版本 ${version}）"
    else
        echo "BudgetBuddy installer"
    fi
}

# ─── 工具探测 ──────────────────────────────────────────────────────────────
file_hash() {
    # stdout: 文件 SHA256 摘要（调用方确保文件存在）
    if [[ "$SHA256_CMD" == "sha256sum" ]]; then
        sha256sum "$1" | cut -d' ' -f1
    else
        shasum -a 256 "$1" | cut -d' ' -f1
    fi
}

# ─── 依赖检查（specs/installer「依赖检查与平台兼容」）──────────────────────
check_dependencies() {
    print_info "检查系统依赖..."
    # bash 3.2 兼容：不用数组（set -u 下空数组展开会报 unbound）
    local missing=""
    command -v curl &>/dev/null || missing="curl"
    command -v tar &>/dev/null || missing="${missing:+$missing }tar"
    # python3 / python 自动探测（Windows 通常为 python）
    if [[ -n "$BUDGET_PYTHON" ]] && command -v "$BUDGET_PYTHON" &>/dev/null; then
        :
    elif command -v python3 &>/dev/null; then
        BUDGET_PYTHON="python3"
    elif command -v python &>/dev/null; then
        BUDGET_PYTHON="python"
    else
        missing="${missing:+$missing }python3"
    fi
    # SHA256 校验工具（sha256sum / shasum -a 256 自动探测）
    if command -v sha256sum &>/dev/null; then
        SHA256_CMD="sha256sum"
    elif command -v shasum &>/dev/null; then
        SHA256_CMD="shasum -a 256"
    else
        missing="${missing:+$missing }sha256sum 或 shasum"
    fi
    if [[ -n "$missing" ]]; then
        print_error "缺少必要的依赖: ${missing}\n请安装后重试（Python 3: https://www.python.org/downloads/）"
    fi
    # Windows 环境提示 Git Bash / WSL（信息性提示，Git Bash 本身受支持）
    case "$(uname -s 2>/dev/null)" in
        MINGW*|MSYS*|CYGWIN*)
            print_warning "检测到 Windows 环境，建议使用 Git Bash 或 WSL 运行本脚本"
            ;;
    esac
    print_success "依赖检查通过（python: $BUDGET_PYTHON / sha256: ${SHA256_CMD}）"
}

# ─── 交互选择（specs/installer「交互与非交互模式」）────────────────────────
select_platform() {
    # BUDGET_PLATFORM 显式指定 → 纯非交互；非法值忽略并警告
    case "${BUDGET_PLATFORM:-}" in
        codebuddy|opencode|claudecode|codex|both|all)
            BUDGET_INSTALL_PLATFORM="$BUDGET_PLATFORM"
            return 0
            ;;
        "")
            ;;
        *)
            print_warning "BUDGET_PLATFORM 值非法（${BUDGET_PLATFORM}），已忽略"
            ;;
    esac
    echo ""
    echo -e "${CYAN}请选择安装平台:${NC}"
    echo "  1) CodeBuddy   — agents/commands/skills/rules/hooks → .codebuddy/（或 ~/.codebuddy/）"
    echo "  2) OpenCode    — agent/command/skill → opencode 目录 + 管理面 ~/.budgetbuddy/"
    echo "  3) Claude Code — agents/commands/skills/hooks → .claude/（或 ~/.claude/）+ 管理面 ~/.budgetbuddy/"
    echo "  4) Codex       — skills → .codex/skills/（或 ~/.codex/skills/）+ 管理面 ~/.budgetbuddy/ + config.toml multi_agent 注入"
    echo "  5) 全部        — 依次执行 CodeBuddy、OpenCode、Claude Code 与 Codex 安装"
    echo ""
    echo -n "请输入 (1/2/3/4/5，默认 1): "
    local choice=""
    # 交互从 /dev/tty 读取（curl|bash 管道安装也支持）；无 tty 走默认
    if read -r choice < /dev/tty 2>/dev/null; then
        case "$choice" in
            2) BUDGET_INSTALL_PLATFORM="opencode" ;;
            3) BUDGET_INSTALL_PLATFORM="claudecode" ;;
            4) BUDGET_INSTALL_PLATFORM="codex" ;;
            5) BUDGET_INSTALL_PLATFORM="all" ;;
            *) BUDGET_INSTALL_PLATFORM="codebuddy" ;;
        esac
    else
        print_warning "无交互终端（/dev/tty 不可用），默认安装 CodeBuddy 平台"
        BUDGET_INSTALL_PLATFORM="codebuddy"
    fi
    echo ""
}

select_scope() {
    # BUDGET_GLOBAL 显式设置（0/1）或 --global 标志 → 跳过交互
    if [[ "$BUDGET_SCOPE_EXPLICIT" == "1" || "$BUDGET_INSTALL_GLOBAL" == "1" ]]; then
        return 0
    fi
    echo ""
    echo -e "${CYAN}请选择安装作用域:${NC}"
    echo "  1) 项目安装 — 安装到当前目录（默认）"
    echo "  2) 全局安装 — 安装到用户主目录（所有项目共享）"
    echo ""
    echo -n "请输入 (1/2，默认 1): "
    local choice=""
    if read -r choice < /dev/tty 2>/dev/null; then
        if [[ "$choice" == "2" ]]; then
            BUDGET_INSTALL_GLOBAL=1
        fi
    else
        # 纯非交互环境（无 tty）默认项目安装（specs/installer）
        BUDGET_INSTALL_GLOBAL=0
    fi
    echo ""
}

# ─── 在线模式：版本定位与下载校验（specs/installer「版本定位与下载包完整性校验」）
resolve_latest_tag() {
    # 经 $BUDGET_REPO_URL/releases/latest（release 托管方 latest 固定别名）
    # 解析重定向后的 URL 提取最新版本 tag（design.md §10/A9）
    local effective_url=""
    effective_url="$(curl -fsSL -o /dev/null -w '%{url_effective}' \
        "$BUDGET_REPO_URL/releases/latest" 2>/dev/null)" \
        || print_error "无法获取最新版本信息（$BUDGET_REPO_URL/releases/latest）\n请检查网络连接，或设置 BUDGET_VERSION 指定版本"
    local tag="${effective_url##*/}"
    if [[ -z "$tag" || "$tag" == "latest" ]]; then
        print_error "无法从重定向 URL 解析版本 tag: $effective_url"
    fi
    echo "$tag"
}

download_release() {
    # 用法: download_release <tag>
    # 下载 zip + .sha256 → 强制 SHA256 校验（失败即中止，A12①）→ python 解压
    # （zip 解压走 python3 zipfile，避免 unzip 依赖）
    local tag="$1"
    local version="${tag#v}"
    local zip_name="budgetbuddy-${version}.zip"
    local zip_url="$BUDGET_REPO_URL/releases/download/$tag/$zip_name"
    local zip_file="$BUDGET_TMP_DIR/$zip_name"

    print_info "下载 $zip_url ..."
    if ! curl -fsSL --retry 3 --retry-delay 2 -o "$zip_file" "$zip_url"; then
        print_error "下载失败: $zip_url\n请检查网络连接或 BUDGET_REPO_URL 配置"
    fi
    print_info "下载校验文件 $zip_url.sha256 ..."
    if ! curl -fsSL --retry 3 --retry-delay 2 -o "${zip_file}.sha256" "${zip_url}.sha256"; then
        print_error "校验文件下载失败: ${zip_url}.sha256\nrelease 必须附带 .sha256 校验文件（缺失即中止，不进入安装）"
    fi
    # 强制 SHA256 校验（失败即中止，不复制任何文件到安装目录）
    local expected="" actual=""
    expected="$(cut -d' ' -f1 "${zip_file}.sha256" | tr -d '[:space:]')"
    actual="$(file_hash "$zip_file")"
    if [[ -z "$expected" || "$actual" != "$expected" ]]; then
        print_error "SHA256 校验失败，安装中止（文件可能已损坏，请重试）\n  期望: $expected\n  实际: $actual"
    fi
    print_success "SHA256 校验通过"

    local extract_dir="$BUDGET_TMP_DIR/extract"
    mkdir -p "$extract_dir"
    BUDGET_ZIP_FILE="$zip_file" BUDGET_EXTRACT_DIR="$extract_dir" \
        "$BUDGET_PYTHON" << 'PYEOF' || print_error "解压失败（zip 损坏或磁盘空间不足）"
import os
import sys
import zipfile

zip_file = os.environ['BUDGET_ZIP_FILE']
extract_dir = os.environ['BUDGET_EXTRACT_DIR']
try:
    with zipfile.ZipFile(zip_file) as archive:
        # 安全：拒绝绝对路径与 .. 越界条目（校验后才解压）
        for name in archive.namelist():
            parts = name.replace('\\', '/').split('/')
            if name.startswith('/') or '..' in parts:
                print('zip 条目路径越界，拒绝解压: %s' % name, file=sys.stderr)
                sys.exit(1)
        archive.extractall(extract_dir)
except zipfile.BadZipFile as exc:
    print('zip 格式错误: %s' % exc, file=sys.stderr)
    sys.exit(1)
PYEOF
    BUDGET_SRC_ROOT="$extract_dir"
}

# ─── 源定位（本地模式：仓库内直接运行且 dist/ 存在 → 跳过下载）───────────
resolve_source() {
    local script_dir=""
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd -P)" || script_dir=""
    local local_ok=true
    case "$BUDGET_INSTALL_PLATFORM" in
        codebuddy)  [[ -n "$script_dir" && -f "$script_dir/dist/codebuddy/.manifest.json" ]] || local_ok=false ;;
        opencode)   [[ -n "$script_dir" && -f "$script_dir/dist/opencode/.manifest.json" ]] || local_ok=false ;;
        claudecode) [[ -n "$script_dir" && -f "$script_dir/dist/claudecode/.manifest.json" ]] || local_ok=false ;;
        codex)      [[ -n "$script_dir" && -f "$script_dir/dist/codex/.manifest.json" ]] || local_ok=false ;;
        both)
            [[ -n "$script_dir" && -f "$script_dir/dist/codebuddy/.manifest.json" ]] || local_ok=false
            [[ -n "$script_dir" && -f "$script_dir/dist/opencode/.manifest.json" ]] || local_ok=false
            ;;
        all)
            [[ -n "$script_dir" && -f "$script_dir/dist/codebuddy/.manifest.json" ]] || local_ok=false
            [[ -n "$script_dir" && -f "$script_dir/dist/opencode/.manifest.json" ]] || local_ok=false
            [[ -n "$script_dir" && -f "$script_dir/dist/claudecode/.manifest.json" ]] || local_ok=false
            [[ -n "$script_dir" && -f "$script_dir/dist/codex/.manifest.json" ]] || local_ok=false
            ;;
    esac
    if [[ "$local_ok" == "true" ]]; then
        BUDGET_SRC_ROOT="$script_dir"
        print_info "本地模式：使用仓库产物 ${script_dir}/dist/（跳过下载）"
        return 0
    fi
    print_info "在线模式：从 $BUDGET_REPO_URL 获取 release"
    BUDGET_TMP_DIR="$(mktemp -d 2>/dev/null || mktemp -d -t budget-install)" \
        || print_error "临时目录创建失败"
    # 双引号立即展开固化路径（EXIT trap 触发时 local 变量已脱离作用域）
    trap 'rm -rf -- "$BUDGET_TMP_DIR"' EXIT
    local tag="$BUDGET_VERSION"
    if [[ -z "$tag" ]]; then
        tag="$(resolve_latest_tag)"
    fi
    print_info "目标版本: $tag"
    download_release "$tag"
}

# ─── manifest 工具（A7：dist/<platform>/.manifest.json 为唯一同步依据）─────
manifest_lines() {
    # 用法: manifest_lines <manifest_file>
    # stdout: "<sha256>\t<相对路径>" 行（按键排序）；解析失败 exit 1
    BUDGET_MANIFEST_FILE="$1" "$BUDGET_PYTHON" << 'PYEOF'
import json
import os
import sys

try:
    with open(os.environ['BUDGET_MANIFEST_FILE'], encoding='utf-8') as handle:
        data = json.load(handle)
except (OSError, ValueError) as exc:
    print('manifest 解析失败: %s' % exc, file=sys.stderr)
    sys.exit(1)
files = data.get('files', {})
if not isinstance(files, dict):
    print('manifest files 字段非对象', file=sys.stderr)
    sys.exit(1)
for rel in sorted(files):
    sha = files[rel]
    if not isinstance(rel, str) or not rel or not isinstance(sha, str) or not sha:
        continue
    parts = rel.replace('\\', '/').split('/')
    if rel.startswith('/') or '..' in parts:
        print('manifest 条目路径越界，已跳过: %s' % rel, file=sys.stderr)
        continue
    print('%s\t%s' % (sha, rel))
PYEOF
}

sync_manifest_tree() {
    # 用法: sync_manifest_tree <dist_root> <manifest_file> <dest_root> <filter> [struct_prefixes]
    #   filter: all（全部条目）| struct（平台结构前缀）| mgmt（其余）
    #   struct_prefixes: 平台结构目录前缀（空格分隔；默认 "agent command skill"
    #   单数 = opencode 形态；claudecode 传 "agents commands skills hooks"
    #   复数 + hooks；最多支持 4 个前缀）
    # 增量同步（specs/installer「manifest 增量同步」）:
    #   目标哈希与清单一致 → 跳过；不一致 → 覆盖；目标不存在 → 复制；
    #   清单外文件不枚举（一律保留）。统计入 SYNC_ADDED/UPDATED/SKIPPED。
    local dist_root="$1"
    local manifest_file="$2"
    local dest_root="$3"
    local filter="$4"
    local struct_prefixes="${5:-agent command skill}"
    local sp1="" sp2="" sp3="" sp4=""
    read -r sp1 sp2 sp3 sp4 <<< "$struct_prefixes" || true
    local list_file=""
    list_file="$(mktemp 2>/dev/null || mktemp -t budget-sync)" || print_error "临时文件创建失败"
    if ! manifest_lines "$manifest_file" > "$list_file"; then
        rm -f "$list_file"
        print_error "产物清单解析失败: $manifest_file"
    fi
    local sha rel src dst kind dst_hash
    while IFS=$'\t' read -r sha rel; do
        [[ -n "$rel" ]] || continue
        # 条目分类（平台结构 vs 管理面；*.fragment.md 统一走合并不复制——
        # AGENTS.fragment.md / CLAUDE.fragment.md 均命中）
        case "$rel" in
            *.fragment.md) kind="fragment" ;;
            *)
                kind="mgmt"
                if [[ -n "$sp1" && "$rel" == "$sp1"/* ]] \
                    || [[ -n "$sp2" && "$rel" == "$sp2"/* ]] \
                    || [[ -n "$sp3" && "$rel" == "$sp3"/* ]] \
                    || [[ -n "$sp4" && "$rel" == "$sp4"/* ]]; then
                    kind="struct"
                fi
                ;;
        esac
        case "$filter" in
            all)    ;;
            struct) [[ "$kind" == "struct" ]] || continue ;;
            mgmt)   [[ "$kind" == "mgmt" ]] || continue ;;
        esac
        src="$dist_root/$rel"
        dst="$dest_root/$rel"
        if [[ ! -f "$src" ]]; then
            print_warning "清单内源文件缺失，跳过: $src"
            continue
        fi
        mkdir -p "$(dirname "$dst")"
        if [[ ! -f "$dst" ]]; then
            cp -p "$src" "$dst"
            SYNC_ADDED=$((SYNC_ADDED + 1))
        else
            dst_hash="$(file_hash "$dst")"
            if [[ "$dst_hash" == "$sha" ]]; then
                SYNC_SKIPPED=$((SYNC_SKIPPED + 1))
            else
                cp -f -p "$src" "$dst"
                SYNC_UPDATED=$((SYNC_UPDATED + 1))
            fi
        fi
    done < "$list_file"
    rm -f "$list_file"
}

upgrade_diff_cleanup() {
    # 用法: upgrade_diff_cleanup <local_manifest> <new_manifest> <old_field> <new_filter> <root> [struct_prefixes]
    # 升级差集清理（A12②）：本地旧清单 <old_field> 键集 − 新 manifest 过滤后
    # 键集 → 逐项删除 <root>/<rel>（清单外用户自建文件不在旧清单内，不受影响）。
    # <old_field> 支持平台命名空间后缀（"platform_files:claudecode" → 仅取
    # "claudecode:" 前缀键并去前缀；无后缀 "platform_files" → 仅取无冒号的
    # opencode 历史格式键，其他平台命名空间条目不属本段）。struct_prefixes
    # 同 sync_manifest_tree（结构前缀按平台参数化）。
    # 解析失败降级为警告（清理尽力而为，不阻断安装主流程）。
    local local_manifest="$1"
    local new_manifest="$2"
    local old_field="$3"
    local new_filter="$4"
    local root="$5"
    local struct_prefixes="${6:-agent command skill}"
    [[ -f "$local_manifest" ]] || return 0
    local list_file=""
    list_file="$(mktemp 2>/dev/null || mktemp -t budget-diff)" || return 0
    if ! BUDGET_LOCAL_MANIFEST="$local_manifest" BUDGET_NEW_MANIFEST="$new_manifest" \
        BUDGET_OLD_FIELD="$old_field" BUDGET_NEW_FILTER="$new_filter" \
        BUDGET_STRUCT_PREFIXES="$struct_prefixes" \
        "$BUDGET_PYTHON" << 'PYEOF' > "$list_file"
import json
import os


def load(path):
    try:
        with open(path, encoding='utf-8') as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


# old_field 解析：字段名 + 可选平台命名空间（"platform_files:claudecode"）
field = os.environ['BUDGET_OLD_FIELD']
if ':' in field:
    field_name, ns_name = field.split(':', 1)
else:
    field_name, ns_name = field, ''
raw_old = load(os.environ['BUDGET_LOCAL_MANIFEST']).get(field_name, {})
if not isinstance(raw_old, dict):
    raw_old = {}
if field_name == 'platform_files' and ns_name:
    # 平台命名空间段：仅取 "<platform>:" 前缀键并去前缀（路径相对该平台结构根）
    prefix = ns_name + ':'
    old = dict((k[len(prefix):], v) for k, v in raw_old.items()
               if isinstance(k, str) and k.startswith(prefix))
elif field_name == 'platform_files':
    # 无命名空间（opencode 历史格式）：仅取无冒号键，其他平台前缀键不属本段
    old = dict((k, v) for k, v in raw_old.items()
               if isinstance(k, str) and ':' not in k)
else:
    old = dict((k, v) for k, v in raw_old.items() if isinstance(k, str))

new_files = load(os.environ['BUDGET_NEW_MANIFEST']).get('files', {})
flt = os.environ['BUDGET_NEW_FILTER']
prefixes = os.environ.get('BUDGET_STRUCT_PREFIXES', 'agent command skill').split()


def is_struct(rel):
    return any(rel.startswith(p + '/') for p in prefixes)


def keep(rel):
    if flt == 'all':
        return True
    if flt == 'struct':
        return is_struct(rel)
    if flt == 'mgmt':
        return not is_struct(rel) and not rel.endswith('.fragment.md')
    return True


new_keys = set(rel for rel in new_files if keep(rel))
for rel in sorted(set(old) - new_keys):
    parts = rel.replace('\\', '/').split('/')
    if rel.startswith('/') or '..' in parts or not rel:
        continue
    print(rel)
PYEOF
    then
        rm -f "$list_file"
        print_warning "本地清单解析失败，跳过差集清理: $local_manifest"
        return 0
    fi
    local rel=""
    while IFS= read -r rel; do
        [[ -n "$rel" ]] || continue
        if rm -f "$root/$rel" 2>/dev/null; then
            CLEANED=$((CLEANED + 1))
            # 空目录清理（仅直接父目录，非空静默跳过——用户自建文件保留时目录保留）
            rmdir "$(dirname "$root/$rel")" 2>/dev/null || true
        fi
    done < "$list_file"
    rm -f "$list_file"
}

write_local_manifest() {
    # 用法: write_local_manifest <dest> <src_manifest> <mode>
    #   mode: all        → files = 全部条目（codebuddy；排除 AGENTS.fragment.md）
    #         opencode   → files = 管理面条目 + platform_files = 平台结构条目（无前缀）
    #         claudecode → 同构拆分，platform_files 条目带 "claudecode:" 前缀
    #         codex      → 同构拆分，platform_files 条目带 "codex:" 前缀
    # platform_files 平铺带平台前缀命名空间（辅审 M4 合并写）：opencode 条目
    # 保持历史无前缀格式（单装产物字节级不变），claudecode/codex 条目带
    # "claudecode:"/"codex:" 前缀；各模式均合并写——保留其他平台条目（后装
    # 不覆盖先装），仅写入/更新本平台段。claudecode/codex 的 files 段亦合并写
    # （管理面与 opencode 共享 ~/.budgetbuddy/，两平台管理面产物存在差异文件，如
    # opencode 独有 docs/setup-notes.md——保留他平台条目，仅延续磁盘仍存
    # 在者）；opencode 的 files 段保持整段覆盖（历史行为不变）。
    # 本地清单格式与 lib/uninstall.sh 读取约定一致（{"files": {<相对路径>: <sha256>}}，
    # 路径相对安装根 ~/.budgetbuddy/；platform_files 为安装器升级差集清理的
    # 附加字段，uninstall 不读取——平台结构文件由其已知结构枚举兜底删除）。
    # 写入纪律：临时文件 + 原子 rename（清单最后写，中断后重跑安装即恢复）。
    BUDGET_DEST="$1" BUDGET_SRC_MANIFEST="$2" BUDGET_MODE="$3" \
        "$BUDGET_PYTHON" << 'PYEOF' || print_error "本地清单写入失败: $1"
import json
import os
import sys
import tempfile

try:
    with open(os.environ['BUDGET_SRC_MANIFEST'], encoding='utf-8') as handle:
        src = json.load(handle).get('files', {})
except (OSError, ValueError) as exc:
    print('manifest 读取失败: %s' % exc, file=sys.stderr)
    sys.exit(1)

dest = os.environ['BUDGET_DEST']
dir_name = os.path.dirname(dest) or '.'

# 已有本地清单（合并写基础；缺失/损坏视为空，不阻断写入）
existing = {}
if os.path.isfile(dest):
    try:
        with open(dest, encoding='utf-8') as handle:
            loaded = json.load(handle)
        if isinstance(loaded, dict):
            existing = loaded
    except (OSError, ValueError):
        existing = {}

FRAGMENTS = ('AGENTS.fragment.md', 'CLAUDE.fragment.md')


def is_struct(rel, prefixes):
    return any(rel.startswith(p + '/') for p in prefixes)


mode = os.environ['BUDGET_MODE']
if mode in ('opencode', 'claudecode', 'codex'):
    if mode == 'opencode':
        prefixes = ('agent', 'command', 'skill')
        own_ns = ''                # opencode 历史格式：无前缀（单装字节级不变）

        def is_own(key):
            return ':' not in key  # 本平台段 = 无冒号键；带前缀键属其他平台
    elif mode == 'claudecode':
        prefixes = ('agents', 'commands', 'skills', 'hooks')
        own_ns = 'claudecode:'

        def is_own(key):
            return key.startswith(own_ns)  # 本平台段 = claudecode: 前缀键
    else:
        # codex：结构前缀仅 skills/（dist/codex 平台结构 = skills 树，design D1）
        prefixes = ('skills',)
        own_ns = 'codex:'

        def is_own(key):
            return key.startswith(own_ns)  # 本平台段 = codex: 前缀键
    files = {}
    platform_files = {}
    raw_pf = existing.get('platform_files')
    if isinstance(raw_pf, dict):
        for key, sha in raw_pf.items():
            if isinstance(key, str) and isinstance(sha, str) and not is_own(key):
                platform_files[key] = sha
    for rel, sha in src.items():
        if rel in FRAGMENTS:
            continue
        if is_struct(rel, prefixes):
            platform_files[own_ns + rel] = sha
        else:
            files[rel] = sha
    if mode in ('claudecode', 'codex'):
        # files 合并写：保留其他平台管理面条目（仅延续磁盘仍存在者——
        # 差集清理已删除的陈旧条目不延续）
        old_files = existing.get('files')
        if isinstance(old_files, dict):
            for rel, sha in old_files.items():
                if (isinstance(rel, str) and isinstance(sha, str)
                        and rel not in files
                        and os.path.isfile(os.path.join(dir_name, rel))):
                    files[rel] = sha
    out = {'files': files, 'platform_files': platform_files}
else:
    out = {'files': dict(
        (rel, sha) for rel, sha in src.items() if rel != 'AGENTS.fragment.md')}

fd, tmp_path = tempfile.mkstemp(prefix='.budget-manifest-', suffix='.tmp', dir=dir_name)
try:
    with os.fdopen(fd, 'w', encoding='utf-8') as tmp:
        json.dump(out, tmp, indent=2, sort_keys=True, ensure_ascii=False)
        tmp.write('\n')
    os.replace(tmp_path, dest)
except Exception as exc:
    try:
        os.unlink(tmp_path)
    except OSError:
        pass
    print('本地清单写入失败: %s' % exc, file=sys.stderr)
    sys.exit(1)
PYEOF
}

local_manifest_other_platform() {
    # 用法: local_manifest_other_platform <manifest_file> <platform>
    # stdout: 1 = 本地清单 platform_files 含其他平台条目；0 = 否（清单
    # 缺失/损坏视为无）。命名空间约定同 write_local_manifest（opencode 无
    # 前缀——本平台段 = 无冒号键，带前缀键属他平台；其余平台如 claudecode
    # 本平台段 = "<platform>:" 前缀键）。用途：多平台共装 ~/.budgetbuddy/ 时
    # 跳过管理面差集清理（另一平台可能拥有本平台产物清单之外的管理面文件，
    # 如 opencode 独有 docs/setup-notes.md，误删即破坏他平台安装）。
    local manifest="$1" platform="$2"
    [[ -f "$manifest" ]] || { echo 0; return 0; }
    local result="0"
    result="$(BUDGET_MANIFEST_FILE="$manifest" BUDGET_PLATFORM="$platform" \
        "$BUDGET_PYTHON" << 'PYEOF' 2>/dev/null
import json
import os

found = 0
try:
    with open(os.environ['BUDGET_MANIFEST_FILE'], encoding='utf-8') as handle:
        data = json.load(handle)
    pf = data.get('platform_files') if isinstance(data, dict) else None
    platform = os.environ['BUDGET_PLATFORM']
    if isinstance(pf, dict):
        if platform == 'opencode':
            # opencode 历史格式：本平台段 = 无冒号键；带前缀键属他平台
            def is_other(key):
                return ':' in key
        else:
            prefix = platform + ':'

            def is_other(key):
                return not key.startswith(prefix)
        for key in pf:
            if isinstance(key, str) and is_other(key):
                found = 1
                break
except (OSError, ValueError):
    found = 0
print(found)
PYEOF
    )" || result="0"
    echo "$result"
}

# ─── AGENTS.md 标记区块幂等合并（specs/installer「AGENTS.md 标记区块幂等合并」）
merge_agents_md() {
    # 用法: merge_agents_md <fragment_file> <target_file>
    # 外层 <!-- BudgetBuddy:begin/end --> 区块整体替换（二级 budget-<rule> 标记
    # 随 fragment 内容整体更新）；区块外用户内容永不触碰；目标不存在时创建。
    # 写入纪律：临时文件 + 原子 rename。
    local fragment="$1"
    local target="$2"
    [[ -f "$fragment" ]] || print_error "AGENTS.fragment.md 缺失: $fragment"
    local status=""
    status="$(BUDGET_FRAGMENT="$fragment" BUDGET_TARGET="$target" \
        "$BUDGET_PYTHON" << 'PYEOF'
import os
import sys
import tempfile

BEGIN = '<!-- BudgetBuddy:begin -->'
END = '<!-- BudgetBuddy:end -->'

with open(os.environ['BUDGET_FRAGMENT'], encoding='utf-8') as handle:
    fragment = handle.read()
if BEGIN not in fragment or END not in fragment:
    print('AGENTS.fragment.md 缺少外层标记', file=sys.stderr)
    sys.exit(1)
if not fragment.endswith('\n'):
    fragment += '\n'

target = os.environ['BUDGET_TARGET']
content = ''
if os.path.isfile(target):
    try:
        with open(target, encoding='utf-8') as handle:
            content = handle.read()
    except (OSError, UnicodeDecodeError) as exc:
        print('目标 AGENTS.md 读取失败: %s' % exc, file=sys.stderr)
        sys.exit(1)

if BEGIN in content:
    if END not in content:
        print('目标 AGENTS.md 含 begin 标记但缺少 end 标记（文件可能损坏），中止合并', file=sys.stderr)
        sys.exit(1)
    begin_idx = content.index(BEGIN)
    end_idx = content.index(END) + len(END)
    if end_idx <= begin_idx:
        print('目标 AGENTS.md 标记顺序异常（end 先于 begin），中止合并', file=sys.stderr)
        sys.exit(1)
    # 吞掉 end 标记行的行尾换行（fragment 自带尾部换行），
    # 否则每次重装累积一个空行、破坏字节级幂等
    if fragment.endswith('\n') and content[end_idx:end_idx + 1] == '\n':
        end_idx += 1
    merged = content[:begin_idx] + fragment + content[end_idx:]
    status = 'replaced'
elif content:
    merged = content
    if not merged.endswith('\n'):
        merged += '\n'
    merged += '\n' + fragment
    status = 'appended'
else:
    merged = fragment
    status = 'created'

dir_name = os.path.dirname(target) or '.'
fd, tmp_path = tempfile.mkstemp(prefix='.agents-', suffix='.tmp', dir=dir_name)
try:
    with os.fdopen(fd, 'w', encoding='utf-8') as tmp:
        tmp.write(merged)
    os.replace(tmp_path, target)
except Exception as exc:
    try:
        os.unlink(tmp_path)
    except OSError:
        pass
    print('AGENTS.md 写入失败: %s' % exc, file=sys.stderr)
    sys.exit(1)
print(status)
PYEOF
)" || print_error "AGENTS.md 合并失败: $target"
    case "$status" in
        created)  print_success "已创建 AGENTS.md 并合并标记区块: $target" ;;
        replaced) print_info "AGENTS.md 标记区块已更新（区块外内容不变）: $target" ;;
        appended) print_success "已追加 BudgetBuddy 标记区块到 AGENTS.md: $target" ;;
    esac
}

# ─── codex config.toml multi_agent 注入（design.md D4 / add-codex-platform D4）──
inject_codex_config() {
    # 用法: inject_codex_config <config_file>
    # 目标 .codex/config.toml（项目）或 ~/.codex/config.toml（全局）——文本级
    # 四态幂等注入 [features] 段 multi_agent = true（spawn_agent/wait_agent/
    # close_agent 工具启用前提）：
    #   ① 段内已有 multi_agent = true（容忍 = 两侧空格变体）→ 跳过（零写入）
    #   ② 段内 multi_agent 键值非 true（用户显式关闭）→ 尊重用户配置不写入，
    #      告警 spawn 工具不可用
    #   ③ 段存在缺键 → 段末追加 multi_agent = true（用户其他键零触碰）
    #   ④ 无 [features] 段 → 文末追加段
    # 段头行首精确匹配 ^\[features\]$（容忍行尾注释，防 [features.xxx] 子串
    # 误判）；注入前备份 <config>.bak-budget（config 不存在则无备份——同
    # settings.json 先例：备份内容与当前一致跳过、当前已含本套件痕迹不覆盖
    # 原始恢复点）；原子写（临时文件 + rename）。失败降级警告不阻断安装。
    # 结果写入全局 CODEX_CONFIG_RESULT（injected|created|exists|respected|
    # failed）供安装摘要如实呈现。
    local config_file="$1"
    CODEX_CONFIG_RESULT="failed"
    local status=""
    status="$(BUDGET_CONFIG_FILE="$config_file" "$BUDGET_PYTHON" << 'PYEOF'
import os
import re
import sys
import tempfile

SECTION_RE = re.compile(r'^\[features\][ \t]*(?:#.*)?$')
SECTION_ANY_RE = re.compile(r'^\[')
KEY_TRUE_RE = re.compile(r'^multi_agent\s*=\s*true\s*$')
KEY_ANY_RE = re.compile(r'^multi_agent\s*=')

path = os.environ['BUDGET_CONFIG_FILE']
content = ''
if os.path.isfile(path):
    try:
        with open(path, encoding='utf-8') as handle:
            content = handle.read()
    except (OSError, UnicodeDecodeError) as exc:
        print('config.toml 读取失败: %s' % exc, file=sys.stderr)
        sys.exit(1)

lines = content.split('\n')


def atomic_write(target, text):
    dir_name = os.path.dirname(target) or '.'
    fd, tmp_path = tempfile.mkstemp(prefix='.codex-config-', suffix='.tmp',
                                    dir=dir_name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as tmp:
            tmp.write(text)
        os.replace(tmp_path, target)
    except Exception as exc:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        print('config.toml 写入失败: %s' % exc, file=sys.stderr)
        sys.exit(1)


def backup_original():
    # settings.json 先例语义：文件不存在无备份；备份与当前一致跳过；
    # 当前已含本套件痕迹（multi_agent 键）不覆盖原始恢复点
    if not os.path.isfile(path):
        return
    backup = path + '.bak-budget'
    if os.path.isfile(backup):
        try:
            with open(backup, encoding='utf-8') as handle:
                if handle.read() == content:
                    return
        except (OSError, UnicodeDecodeError):
            pass
        if KEY_ANY_RE.search(content):
            return
    atomic_write(backup, content)


# 定位 [features] 段（行首精确；段界 = 下一个段头行或 EOF）
section_idx = -1
for idx, line in enumerate(lines):
    if SECTION_RE.match(line):
        section_idx = idx
        break

if section_idx >= 0:
    end_idx = len(lines)
    for idx in range(section_idx + 1, len(lines)):
        if SECTION_ANY_RE.match(lines[idx]):
            end_idx = idx
            break
    key_idx = -1
    for idx in range(section_idx + 1, end_idx):
        if KEY_ANY_RE.match(lines[idx]):
            key_idx = idx
            break
    if key_idx >= 0:
        if KEY_TRUE_RE.match(lines[key_idx]):
            print('exists')
        else:
            # ② 用户显式非 true：尊重配置，零写入
            print('respected')
        sys.exit(0)
    # ③ 段存在缺键 → 段末（下一个段头前）插入
    insert_lines = ['multi_agent = true']
    backup_original()
    new_lines = lines[:end_idx] + insert_lines + lines[end_idx:]
    atomic_write(path, '\n'.join(new_lines))
    print('injected')
    sys.exit(0)

# ④ 无 [features] 段 → 文末追加（确保前文以换行收尾）
backup_original()
new_lines = list(lines)
while new_lines and new_lines[-1] == '':
    new_lines.pop()
new_lines += ['', '[features]', 'multi_agent = true', '']
atomic_write(path, '\n'.join(new_lines))
print('created')
PYEOF
    )" || status=""
    case "$status" in
        exists)
            CODEX_CONFIG_RESULT="exists"
            print_info "config.toml 已含 multi_agent = true，跳过注入: $config_file"
            ;;
        respected)
            CODEX_CONFIG_RESULT="respected"
            print_warning "config.toml [features] multi_agent 已被用户显式关闭，尊重用户配置不注入——spawn 工具（spawn_agent/wait_agent/close_agent）将不可用: $config_file"
            ;;
        injected)
            CODEX_CONFIG_RESULT="injected"
            print_success "已在 config.toml [features] 段内注入 multi_agent = true: $config_file"
            ;;
        created)
            CODEX_CONFIG_RESULT="created"
            print_success "已在 config.toml 文末追加 [features] 段 multi_agent = true: $config_file"
            ;;
        *)
            CODEX_CONFIG_RESULT="failed"
            print_warning "config.toml multi_agent 注入失败（可手动添加 [features] multi_agent = true）: $config_file"
            ;;
    esac
    return 0
}

# ─── codex AGENTS.md 既有区块异形态检测（add-codex-platform D4）───────────
_warn_codex_block_shape() {
    # 用法: _warn_codex_block_shape <agents_md>
    # 合并前检测既有 <!-- BudgetBuddy:begin/end --> 区块形态：区块行数 > 100
    # （opencode 全文形态特征——12 条规则全文合并）→ 告警「同项目混装两形态
    # 将相互替换」。轻量机制（不阻断合并），防静默覆盖：codex 轻量索引与
    # opencode 规则全文共用同一标记区块，后装整体替换先装。
    local target="$1"
    [[ -f "$target" ]] || return 0
    grep -q "<!-- BudgetBuddy:begin -->" "$target" 2>/dev/null || return 0
    local lines=""
    lines="$(awk '
        /<!-- BudgetBuddy:begin -->/ { counting = 1; next }
        /<!-- BudgetBuddy:end -->/   { counting = 0; next }
        counting { n++ }
        END { print n + 0 }
    ' "$target" 2>/dev/null)" || lines="0"
    [[ -n "$lines" && "$lines" -gt 100 ]] || return 0
    print_warning "检测到 OpenCode 全文区块（既有 BudgetBuddy 区块 ${lines} 行 > 100），同项目混装两形态将相互替换（Codex 轻量索引 / OpenCode 规则全文共用同一标记区块）: $target"
    return 0
}

# ─── 安装编排：包装器与 hooks 注入 ─────────────────────────────────────────
install_wrapper() {
    # 用法: install_wrapper <lib_dir>
    # source 安装形态的 lib/utils.sh 调 budget_install_wrapper（~/.local/bin/budget，
    # 与 setup init 同一实现，避免双份维护）。失败降级警告（不阻断安装）。
    local lib_dir="$1"
    if [[ ! -f "$lib_dir/utils.sh" ]]; then
        print_warning "utils.sh 缺失，跳过命令包装器写入（$lib_dir/utils.sh）"
        return 0
    fi
    # shellcheck disable=SC1090  # 动态路径 source
    if ! source "$lib_dir/utils.sh"; then
        print_warning "utils.sh 加载失败，跳过命令包装器写入"
        return 0
    fi
    if ! budget_install_wrapper; then
        print_warning "budget 命令包装器写入失败（$HOME/.local/bin/budget）"
        return 0
    fi
    print_success "budget 命令包装器已就绪: $HOME/.local/bin/budget"
    if ! echo "$PATH" | tr ':' '\n' | grep -qF "$HOME/.local/bin"; then
        print_warning "PATH 未包含 $HOME/.local/bin，重新打开终端后生效"
    fi
}

inject_hooks_codebuddy() {
    # 用法: inject_hooks_codebuddy <install_root> <global_flag>
    # 安装形态就位后调用 lib/hooks.sh 的 budget_inject_hooks（三事件 +
    # superpowers 插件启用，design.md §10/§12-A11）。子进程执行，不污染
    # install.sh 自身环境；子进程内 unset BUDGET_PLATFORM 防 detect_platform
    # 显式覆盖分支把项目级安装误判为全局。失败降级警告（可 budget setup init 补全）。
    local install_root="$1"
    local global_flag="$2"
    local lib_dir="$install_root/lib"
    local f
    for f in colors.sh platform.sh hooks.sh hooks_inject.py; do
        if [[ ! -f "$lib_dir/$f" ]]; then
            print_warning "hooks 注入模块缺失（$lib_dir/${f}），可稍后运行 budget setup init 补全"
            return 0
        fi
    done
    if BUDGET_GLOBAL="$global_flag" BUDGET_SETUP_DIR="$install_root" \
        BUDGET_LIB_DIR="$lib_dir" BUDGET_PYTHON="$BUDGET_PYTHON" \
        bash -c '
            unset BUDGET_PLATFORM
            source "$BUDGET_LIB_DIR/colors.sh"
            source "$BUDGET_LIB_DIR/platform.sh"
            source "$BUDGET_LIB_DIR/hooks.sh"
            detect_platform >/dev/null 2>&1 || true
            budget_inject_hooks
        '; then
        print_success "hooks 注入完成（settings.json 三事件 + superpowers 插件）"
    else
        print_warning "hooks 注入失败，可稍后运行 budget setup init 补全"
    fi
}

inject_hooks_claudecode() {
    # 用法: inject_hooks_claudecode <struct_root> <mgmt_root> <global_flag>
    # claudecode 版注入（design.md D4）：hooks 文件在平台结构根（.claude/ 或
    # ~/.claude/），注入编排模块在管理面（~/.budgetbuddy/lib/，A3 与 opencode
    # 共享）——两根分离，区别于 codebuddy 的同根形态。子进程执行（同
    # inject_hooks_codebuddy 先例：不污染 install.sh 自身环境；unset
    # BUDGET_PLATFORM 防探测显式覆盖分支误判作用域）。BUDGET_SETUP_DIR 指向
    # 结构根（hooks.sh 仅以该值定位 hook 脚本绝对路径：项目级走相对路径、
    # 全局走 ~/.claude/hooks/）。
    #
    # 共装误判修复（复审 F1/F2）：子进程不再 detect_platform 探测——
    # codebuddy 先装（all 模式必现）后再装 claudecode 时 .codebuddy/setup.sh
    # 已就位，探测序 codebuddy 优先 → 误判 kind=codebuddy，注入错写到
    # .codebuddy/settings.json 且 .claude/settings.json 不生成（安装器仍报
    # 假成功）。改为调用方已知形态直传（hooks.sh 契约：显式 settings_file
    # 跳过探测，调用方负责形态变量快照保证 hook_cmd 落点同形态）：
    #   - settings_file = <struct_root>/settings.json（项目级即 .claude/
    #     settings.json、全局即 ~/.claude/settings.json，由调用方计算）
    #   - 形态快照 BUDGET_PLATFORM_KIND=claudecode + SCOPE/ROOT（项目级
    #     root=$PWD → hook_cmd 走相对路径；全局 root 空 → BUDGET_SETUP_DIR
    #     绝对路径）
    # 子进程 stdout 末行回传 INJECT_RESULT=ok|failed 标记（F2：不以子进程
    # exit 0 判成功），按标记决定 success/warning 文案；失败降级警告不阻断
    # 安装（可 budget setup init 补全）。结果同步写入全局变量
    # CLAUDECODE_HOOKS_RESULT（ok|failed|skipped）供安装摘要如实呈现。
    local struct_root="$1"
    local mgmt_root="$2"
    local global_flag="$3"
    local lib_dir="$mgmt_root/lib"
    local f
    for f in colors.sh platform.sh hooks.sh hooks_inject.py; do
        if [[ ! -f "$lib_dir/$f" ]]; then
            print_warning "hooks 注入模块缺失（$lib_dir/${f}），可稍后运行 budget setup init 补全"
            CLAUDECODE_HOOKS_RESULT="skipped"
            return 0
        fi
    done
    if [[ ! -f "$struct_root/hooks/budget-notify-hook.py" ]]; then
        print_warning "hook 脚本缺失（$struct_root/hooks/budget-notify-hook.py），跳过 hooks 注入"
        CLAUDECODE_HOOKS_RESULT="skipped"
        return 0
    fi
    # 形态快照（调用方已知，不依赖探测）：项目级 scope=project + root=$PWD；
    # 全局 scope=global + root 空（hook_cmd 回退 BUDGET_SETUP_DIR 绝对路径）
    local settings_file="$struct_root/settings.json"
    local platform_scope="global" platform_root=""
    if [[ "$global_flag" != "1" ]]; then
        platform_scope="project"
        platform_root="$PWD"
    fi
    local output rc=0
    output="$(BUDGET_GLOBAL="$global_flag" BUDGET_SETUP_DIR="$struct_root" \
        BUDGET_LIB_DIR="$lib_dir" BUDGET_PYTHON="$BUDGET_PYTHON" \
        BUDGET_PLATFORM_KIND="claudecode" BUDGET_PLATFORM_SCOPE="$platform_scope" \
        BUDGET_PLATFORM_ROOT="$platform_root" BUDGET_SETTINGS_FILE="$settings_file" \
        bash -c '
            unset BUDGET_PLATFORM
            source "$BUDGET_LIB_DIR/colors.sh"
            source "$BUDGET_LIB_DIR/platform.sh"
            source "$BUDGET_LIB_DIR/hooks.sh"
            if budget_inject_hooks "$BUDGET_SETTINGS_FILE"; then
                echo "INJECT_RESULT=ok"
            else
                echo "INJECT_RESULT=failed"
            fi
        ')" || rc=$?
    # 透传子进程 stdout（末行 INJECT_RESULT 标记行除外；stderr 已直通终端）
    local marker
    marker="$(printf '%s\n' "$output" | tail -n 1)"
    if [[ -n "$output" ]]; then
        printf '%s\n' "$output" | sed '$d'
    fi
    if [[ "$rc" -ne 0 \
          || ( "$marker" != "INJECT_RESULT=ok" && "$marker" != "INJECT_RESULT=failed" ) ]]; then
        # 子进程异常崩溃/无标记行 → 按失败降级（不阻断安装）
        marker="INJECT_RESULT=failed"
    fi
    if [[ "$marker" == "INJECT_RESULT=ok" ]]; then
        print_success "hooks 注入完成（settings.json 三事件 Notification/PermissionRequest/SubagentStop）"
        CLAUDECODE_HOOKS_RESULT="ok"
    else
        print_warning "hooks 注入失败，可稍后运行 budget setup init 补全"
        CLAUDECODE_HOOKS_RESULT="failed"
    fi
    return 0
}

# ─── 平台安装流程 ──────────────────────────────────────────────────────────
install_codebuddy() {
    # codebuddy：dist/codebuddy/ 全部结构文件 → .codebuddy/（项目）或
    # ~/.codebuddy/（全局）+ 包装器 + hooks 注入（design.md §10）
    local dist_root="$BUDGET_SRC_ROOT/dist/codebuddy"
    local manifest_file="$dist_root/.manifest.json"
    [[ -f "$manifest_file" ]] || print_error "产物清单缺失: ${manifest_file}（请先运行 python3 scripts/build.py）"

    local install_root="" scope_label=""
    if [[ "$BUDGET_INSTALL_GLOBAL" == "1" ]]; then
        install_root="$HOME/.codebuddy"
        scope_label="全局"
        print_info "CodeBuddy 全局安装 → $install_root"
    else
        install_root="$PWD/.codebuddy"
        scope_label="项目级"
        print_info "CodeBuddy 项目安装 → $install_root"
    fi

    SYNC_ADDED=0; SYNC_UPDATED=0; SYNC_SKIPPED=0; CLEANED=0
    # 1) 增量同步（哈希一致跳过 / 不一致覆盖 / 清单外保留；中断重跑即恢复）
    sync_manifest_tree "$dist_root" "$manifest_file" "$install_root" "all"
    local total=$((SYNC_ADDED + SYNC_UPDATED + SYNC_SKIPPED))
    print_success "CodeBuddy 文件同步完成: 新增 $SYNC_ADDED / 更新 $SYNC_UPDATED / 跳过 ${SYNC_SKIPPED}（清单外文件一律保留）"
    # 2) 升级差集清理（本地旧清单 − 新 manifest；同步后执行，任意中断点均有可用安装）
    upgrade_diff_cleanup "$install_root/.budget-manifest.json" "$manifest_file" "files" "all" "$install_root"
    if [[ "$CLEANED" -gt 0 ]]; then
        print_info "升级差集清理: 已删除 $CLEANED 个旧版文件（清单外用户文件不受影响）"
    fi
    # 2.5) AutoRun 状态重放（agent-autorun design.md D4/D5：~/.budgetbuddy/
    #   auto-run.json 存在则 apply 全量对齐，把用户持久化选择重放回刚同步的
    #   agent 文件——lib/autorun.py 随步骤 1 的 sync_manifest_tree 同步就位。
    #   失败仅告警不阻断安装（可稍后运行 budget setup autorun list 检查）；
    #   形态变量显式快照（调用方已知形态，不依赖探测），保证 apply 只作用于
    #   本次 install_root。opencode/claudecode 分支无此钩子（不映射 auto-run））
    local autorun_scope="project" autorun_root="$install_root"
    if [[ "$BUDGET_INSTALL_GLOBAL" == "1" ]]; then
        autorun_scope="global"
        autorun_root=""
    fi
    if [[ -f "$HOME/.budgetbuddy/auto-run.json" ]]; then
        if [[ -f "$install_root/lib/autorun.py" ]] && \
            BUDGET_PLATFORM_KIND="codebuddy" BUDGET_PLATFORM_SCOPE="$autorun_scope" \
            BUDGET_PLATFORM_ROOT="$autorun_root" BUDGET_AGENTS_DIR="$install_root/agents" \
            "$BUDGET_PYTHON" "$install_root/lib/autorun.py" apply; then
            print_info "AutoRun 状态重放完成（~/.budgetbuddy/auto-run.json）"
        else
            print_warning "AutoRun 状态重放失败（$install_root/lib/autorun.py），可稍后运行 budget setup autorun list 检查状态"
        fi
    fi
    # 3) setup.sh 可执行
    chmod +x "$install_root/setup.sh" 2>/dev/null || true
    # 4) 本地清单（最后原子写；卸载按此清单删除，budget setup uninstall）
    write_local_manifest "$install_root/.budget-manifest.json" "$manifest_file" "all"
    print_success "本地安装清单已写入: $install_root/.budget-manifest.json"
    # 5) 命令包装器
    install_wrapper "$install_root/lib"
    # 6) hooks 注入（含 superpowers 插件启用）
    inject_hooks_codebuddy "$install_root" "$BUDGET_INSTALL_GLOBAL"

    SUMMARY_OUTPUT+="平台:      CodeBuddy（${scope_label}）"$'\n'
    SUMMARY_OUTPUT+="落点:      $install_root"$'\n'
    SUMMARY_OUTPUT+="文件:      $total 个（新增 $SYNC_ADDED / 更新 $SYNC_UPDATED / 跳过 ${SYNC_SKIPPED}）"$'\n'
    SUMMARY_OUTPUT+="命令:      $HOME/.local/bin/budget"$'\n'
    SUMMARY_OUTPUT+="hooks:     settings.json（Notification/PreToolUse/SubagentStop + superpowers）"$'\n'
    SUMMARY_OUTPUT+=""$'\n'
}

install_opencode() {
    # opencode：dist/opencode/{agent,command,skill} → 平台结构目录（项目
    # .opencode/ 或全局 ~/.config/opencode/）；管理面（setup.sh/lib/models/
    # personas/docs）统一装 ~/.budgetbuddy/（A3）；AGENTS.fragment.md 幂等
    # 合并进 AGENTS.md（项目根或 ~/.config/opencode/AGENTS.md）。
    local dist_root="$BUDGET_SRC_ROOT/dist/opencode"
    local manifest_file="$dist_root/.manifest.json"
    [[ -f "$manifest_file" ]] || print_error "产物清单缺失: ${manifest_file}（请先运行 python3 scripts/build.py）"

    local struct_root="" mgmt_root="" agents_md="" scope_label=""
    if [[ "$BUDGET_INSTALL_GLOBAL" == "1" ]]; then
        struct_root="$HOME/.config/opencode"
        agents_md="$struct_root/AGENTS.md"
        scope_label="全局"
        print_info "OpenCode 全局安装 → ${struct_root}（管理面 → $HOME/.budgetbuddy）"
    else
        struct_root="$PWD/.opencode"
        agents_md="$PWD/AGENTS.md"
        scope_label="项目级"
        print_info "OpenCode 项目安装 → ${struct_root}（管理面 → $HOME/.budgetbuddy）"
    fi
    mgmt_root="$HOME/.budgetbuddy"

    # 1) 平台结构同步（agent/command/skill）
    SYNC_ADDED=0; SYNC_UPDATED=0; SYNC_SKIPPED=0
    sync_manifest_tree "$dist_root" "$manifest_file" "$struct_root" "struct"
    local struct_added=$SYNC_ADDED struct_updated=$SYNC_UPDATED struct_skipped=$SYNC_SKIPPED
    # 2) 管理面同步（lib/setup.sh/models/personas/docs → ~/.budgetbuddy/）
    SYNC_ADDED=0; SYNC_UPDATED=0; SYNC_SKIPPED=0
    sync_manifest_tree "$dist_root" "$manifest_file" "$mgmt_root" "mgmt"
    print_success "OpenCode 文件同步完成: 结构 新增 $struct_added / 更新 $struct_updated / 跳过 ${struct_skipped}；管理面 新增 $SYNC_ADDED / 更新 $SYNC_UPDATED / 跳过 ${SYNC_SKIPPED}（清单外文件一律保留）"
    # 3) AGENTS.fragment.md 幂等合并（不复制文件，合并进 AGENTS.md）
    merge_agents_md "$dist_root/AGENTS.fragment.md" "$agents_md"
    # 4) 升级差集清理（管理面 files + 平台结构 platform_files 两根分别清理；
    #    多平台共装时管理面清理跳过——他平台管理面文件不在本平台产物清单内，
    #    与 claudecode 分支对称的防误删 guard，复审发现 3）
    CLEANED=0
    if [[ "$(local_manifest_other_platform "$mgmt_root/.budget-manifest.json" "opencode")" == "1" ]]; then
        print_info "检测到其他平台共装 ~/.budgetbuddy/，跳过管理面差集清理（避免误删他平台管理面文件）"
    else
        upgrade_diff_cleanup "$mgmt_root/.budget-manifest.json" "$manifest_file" "files" "mgmt" "$mgmt_root"
    fi
    upgrade_diff_cleanup "$mgmt_root/.budget-manifest.json" "$manifest_file" "platform_files" "struct" "$struct_root"
    if [[ "$CLEANED" -gt 0 ]]; then
        print_info "升级差集清理: 已删除 $CLEANED 个旧版文件（清单外用户文件不受影响）"
    fi
    # 5) setup.sh 可执行
    chmod +x "$mgmt_root/setup.sh" 2>/dev/null || true
    # 6) 本地清单（files=管理面[uninstall 读取约定] + platform_files=平台结构）
    write_local_manifest "$mgmt_root/.budget-manifest.json" "$manifest_file" "opencode"
    print_success "本地安装清单已写入: $mgmt_root/.budget-manifest.json"
    # 7) 命令包装器（budget CLI 对 OpenCode 形态同样可用，管理面在 ~/.budgetbuddy/）
    install_wrapper "$mgmt_root/lib"

    local total=$((struct_added + struct_updated + struct_skipped + SYNC_ADDED + SYNC_UPDATED + SYNC_SKIPPED))
    SUMMARY_OUTPUT+="平台:      OpenCode（${scope_label}）"$'\n'
    SUMMARY_OUTPUT+="落点:      ${struct_root}（结构） + ${mgmt_root}（管理面）"$'\n'
    SUMMARY_OUTPUT+="文件:      $total 个（新增 $((struct_added + SYNC_ADDED)) / 更新 $((struct_updated + SYNC_UPDATED)) / 跳过 $((struct_skipped + SYNC_SKIPPED))）"$'\n'
    SUMMARY_OUTPUT+="AGENTS.md: ${agents_md}（标记区块）"$'\n'
    SUMMARY_OUTPUT+="命令:      $HOME/.local/bin/budget"$'\n'
    SUMMARY_OUTPUT+=""$'\n'
}

install_claudecode() {
    # claudecode：dist/claudecode/{agents,commands,skills,hooks} → 平台结构
    # 目录（项目 .claude/ 或全局 ~/.claude/，复数目录前缀区别于 opencode 单数）；
    # 管理面（setup.sh/lib/models/personas/docs）统一装 ~/.budgetbuddy/（A3，
    # 与 opencode 共享，本地清单合并写）；CLAUDE.fragment.md 幂等合并进
    # CLAUDE.md（项目根或 ~/.claude/CLAUDE.md，复用 merge_agents_md）。
    # hooks 文件随结构分发后注入 settings.json 三事件（design.md D4，无
    # superpowers 插件机制）。
    local dist_root="$BUDGET_SRC_ROOT/dist/claudecode"
    local manifest_file="$dist_root/.manifest.json"
    [[ -f "$manifest_file" ]] || print_error "产物清单缺失: ${manifest_file}（请先运行 python3 scripts/build.py）"

    local struct_root="" mgmt_root="" claude_md="" scope_label=""
    if [[ "$BUDGET_INSTALL_GLOBAL" == "1" ]]; then
        struct_root="$HOME/.claude"
        claude_md="$HOME/.claude/CLAUDE.md"
        scope_label="全局"
        print_info "Claude Code 全局安装 → ${struct_root}（管理面 → $HOME/.budgetbuddy）"
    else
        struct_root="$PWD/.claude"
        claude_md="$PWD/CLAUDE.md"
        scope_label="项目级"
        print_info "Claude Code 项目安装 → ${struct_root}（管理面 → $HOME/.budgetbuddy）"
    fi
    mgmt_root="$HOME/.budgetbuddy"
    local struct_prefixes="agents commands skills hooks"

    # 1) 平台结构同步（agents/commands/skills 复数前缀）
    SYNC_ADDED=0; SYNC_UPDATED=0; SYNC_SKIPPED=0
    sync_manifest_tree "$dist_root" "$manifest_file" "$struct_root" "struct" "$struct_prefixes"
    local struct_added=$SYNC_ADDED struct_updated=$SYNC_UPDATED struct_skipped=$SYNC_SKIPPED
    # 2) 管理面同步（lib/setup.sh/models/personas/docs → ~/.budgetbuddy/）
    SYNC_ADDED=0; SYNC_UPDATED=0; SYNC_SKIPPED=0
    sync_manifest_tree "$dist_root" "$manifest_file" "$mgmt_root" "mgmt" "$struct_prefixes"
    print_success "Claude Code 文件同步完成: 结构 新增 $struct_added / 更新 $struct_updated / 跳过 ${struct_skipped}；管理面 新增 $SYNC_ADDED / 更新 $SYNC_UPDATED / 跳过 ${SYNC_SKIPPED}（清单外文件一律保留）"
    # 3) CLAUDE.fragment.md 幂等合并（不复制文件，合并进 CLAUDE.md）
    merge_agents_md "$dist_root/CLAUDE.fragment.md" "$claude_md"
    # 4) 升级差集清理（本平台段 platform_files:claudecode + 共享管理面 files；
    #    多平台共装时管理面清理跳过——他平台管理面文件不在本平台产物清单内）
    CLEANED=0
    if [[ "$(local_manifest_other_platform "$mgmt_root/.budget-manifest.json" "claudecode")" == "1" ]]; then
        print_info "检测到其他平台共装 ~/.budgetbuddy/，跳过管理面差集清理（避免误删他平台管理面文件）"
    else
        upgrade_diff_cleanup "$mgmt_root/.budget-manifest.json" "$manifest_file" "files" "mgmt" "$mgmt_root" "$struct_prefixes"
    fi
    upgrade_diff_cleanup "$mgmt_root/.budget-manifest.json" "$manifest_file" "platform_files:claudecode" "struct" "$struct_root" "$struct_prefixes"
    if [[ "$CLEANED" -gt 0 ]]; then
        print_info "升级差集清理: 已删除 $CLEANED 个旧版文件（清单外用户文件不受影响）"
    fi
    # 5) setup.sh 可执行
    chmod +x "$mgmt_root/setup.sh" 2>/dev/null || true
    # 6) 本地清单（合并写：files = 管理面 + platform_files = claudecode: 前缀段）
    write_local_manifest "$mgmt_root/.budget-manifest.json" "$manifest_file" "claudecode"
    print_success "本地安装清单已写入: $mgmt_root/.budget-manifest.json"
    # 7) 命令包装器（budget CLI 对 Claude Code 形态同样可用，管理面在 ~/.budgetbuddy/）
    install_wrapper "$mgmt_root/lib"
    # 8) hooks 注入（settings.json 三事件：Notification/PermissionRequest/
    #    SubagentStop；无 superpowers 插件机制，design.md D4）——形态快照 +
    #    显式 settings_file 直传（共装误判修复，详见 inject_hooks_claudecode
    #    注释）；摘要按 CLAUDECODE_HOOKS_RESULT 如实呈现（失败/跳过降级提示，
    #    不阻断安装）
    CLAUDECODE_HOOKS_RESULT="failed"
    inject_hooks_claudecode "$struct_root" "$mgmt_root" "$BUDGET_INSTALL_GLOBAL"
    local hooks_line="hooks:     ${struct_root}/settings.json（Notification/PermissionRequest/SubagentStop）"
    case "$CLAUDECODE_HOOKS_RESULT" in
        failed)
            hooks_line="hooks:     注入失败（可运行 budget setup init 补全）"
            ;;
        skipped)
            hooks_line="hooks:     未注入（模块或 hook 脚本缺失，可运行 budget setup init 补全）"
            ;;
    esac
    SUMMARY_OUTPUT+="$hooks_line"$'\n'

    local total=$((struct_added + struct_updated + struct_skipped + SYNC_ADDED + SYNC_UPDATED + SYNC_SKIPPED))
    SUMMARY_OUTPUT+="平台:      Claude Code（${scope_label}）"$'\n'
    SUMMARY_OUTPUT+="落点:      ${struct_root}（结构） + ${mgmt_root}（管理面）"$'\n'
    SUMMARY_OUTPUT+="文件:      $total 个（新增 $((struct_added + SYNC_ADDED)) / 更新 $((struct_updated + SYNC_UPDATED)) / 跳过 $((struct_skipped + SYNC_SKIPPED))）"$'\n'
    SUMMARY_OUTPUT+="CLAUDE.md: ${claude_md}（标记区块）"$'\n'
    SUMMARY_OUTPUT+="命令:      $HOME/.local/bin/budget"$'\n'
    SUMMARY_OUTPUT+=""$'\n'
}

install_codex() {
    # codex：dist/codex/skills/ → 平台结构目录（项目 .codex/skills/ 或全局
    # ~/.codex/skills/，结构前缀仅 skills/——skill 形态产物，design.md D1）；
    # 管理面（setup.sh/lib/models/personas/docs）统一装 ~/.budgetbuddy/（A3，
    # 与 opencode/claudecode 共享，本地清单合并写，codex: 前缀段）。
    # AGENTS.fragment.md 轻量区块合并进项目根 AGENTS.md 或 ~/.codex/AGENTS.md
    # （复用 merge_agents_md；~/.codex 目录不存在时创建；合并前异形态检测——
    # 既有区块为 opencode 全文形态时告警）；config.toml [features]
    # multi_agent = true 幂等注入（inject_codex_config 四态）。Codex 无 hooks
    # 机制（实验态不分发），无 settings 注入步骤。
    local dist_root="$BUDGET_SRC_ROOT/dist/codex"
    local manifest_file="$dist_root/.manifest.json"
    [[ -f "$manifest_file" ]] || print_error "产物清单缺失: ${manifest_file}（请先运行 python3 scripts/build.py）"

    local struct_root="" mgmt_root="" agents_md="" scope_label=""
    if [[ "$BUDGET_INSTALL_GLOBAL" == "1" ]]; then
        struct_root="$HOME/.codex"
        agents_md="$HOME/.codex/AGENTS.md"
        scope_label="全局"
        print_info "Codex 全局安装 → ${struct_root}（管理面 → $HOME/.budgetbuddy）"
    else
        struct_root="$PWD/.codex"
        agents_md="$PWD/AGENTS.md"
        scope_label="项目级"
        print_info "Codex 项目安装 → ${struct_root}（管理面 → $HOME/.budgetbuddy）"
    fi
    mgmt_root="$HOME/.budgetbuddy"
    local struct_prefixes="skills"

    # 1) 平台结构同步（skills/ 前缀；~/.codex 目录不存在时创建）
    mkdir -p "$struct_root"
    SYNC_ADDED=0; SYNC_UPDATED=0; SYNC_SKIPPED=0
    sync_manifest_tree "$dist_root" "$manifest_file" "$struct_root" "struct" "$struct_prefixes"
    local struct_added=$SYNC_ADDED struct_updated=$SYNC_UPDATED struct_skipped=$SYNC_SKIPPED
    # 2) 管理面同步（lib/setup.sh/models/personas/docs → ~/.budgetbuddy/）
    SYNC_ADDED=0; SYNC_UPDATED=0; SYNC_SKIPPED=0
    sync_manifest_tree "$dist_root" "$manifest_file" "$mgmt_root" "mgmt" "$struct_prefixes"
    print_success "Codex 文件同步完成: 结构 新增 $struct_added / 更新 $struct_updated / 跳过 ${struct_skipped}；管理面 新增 $SYNC_ADDED / 更新 $SYNC_UPDATED / 跳过 ${SYNC_SKIPPED}（清单外文件一律保留）"
    # 3) AGENTS.fragment.md 轻量区块合并（合并前异形态检测：opencode 全文
    #    形态告警，防静默覆盖）
    _warn_codex_block_shape "$agents_md"
    merge_agents_md "$dist_root/AGENTS.fragment.md" "$agents_md"
    # 4) config.toml multi_agent 注入（四态幂等；失败降级警告不阻断）
    CODEX_CONFIG_RESULT="failed"
    inject_codex_config "$struct_root/config.toml"
    # 5) 升级差集清理（本平台段 platform_files:codex + 共享管理面 files；
    #    多平台共装时管理面清理跳过——他平台管理面文件不在本平台产物清单内）
    CLEANED=0
    if [[ "$(local_manifest_other_platform "$mgmt_root/.budget-manifest.json" "codex")" == "1" ]]; then
        print_info "检测到其他平台共装 ~/.budgetbuddy/，跳过管理面差集清理（避免误删他平台管理面文件）"
    else
        upgrade_diff_cleanup "$mgmt_root/.budget-manifest.json" "$manifest_file" "files" "mgmt" "$mgmt_root" "$struct_prefixes"
    fi
    upgrade_diff_cleanup "$mgmt_root/.budget-manifest.json" "$manifest_file" "platform_files:codex" "struct" "$struct_root" "$struct_prefixes"
    if [[ "$CLEANED" -gt 0 ]]; then
        print_info "升级差集清理: 已删除 $CLEANED 个旧版文件（清单外用户文件不受影响）"
    fi
    # 6) setup.sh 可执行
    chmod +x "$mgmt_root/setup.sh" 2>/dev/null || true
    # 7) 本地清单（合并写：files = 管理面 + platform_files = codex: 前缀段）
    write_local_manifest "$mgmt_root/.budget-manifest.json" "$manifest_file" "codex"
    print_success "本地安装清单已写入: $mgmt_root/.budget-manifest.json"
    # 8) 命令包装器（budget CLI 对 Codex 形态同样可用，管理面在 ~/.budgetbuddy/）
    install_wrapper "$mgmt_root/lib"

    # 摘要 config 行按注入结果如实呈现（exists/injected/created 统一为已启用）
    local config_line="config:    ${struct_root}/config.toml（[features] multi_agent = true）"
    case "$CODEX_CONFIG_RESULT" in
        respected)
            config_line="config:    multi_agent 被用户显式关闭（spawn 工具不可用）: ${struct_root}/config.toml"
            ;;
        failed)
            config_line="config:    注入失败（可手动添加 [features] multi_agent = true）: ${struct_root}/config.toml"
            ;;
    esac

    local total=$((struct_added + struct_updated + struct_skipped + SYNC_ADDED + SYNC_UPDATED + SYNC_SKIPPED))
    SUMMARY_OUTPUT+="平台:      Codex（${scope_label}）"$'\n'
    SUMMARY_OUTPUT+="落点:      ${struct_root}（结构） + ${mgmt_root}（管理面）"$'\n'
    SUMMARY_OUTPUT+="文件:      $total 个（新增 $((struct_added + SYNC_ADDED)) / 更新 $((struct_updated + SYNC_UPDATED)) / 跳过 $((struct_skipped + SYNC_SKIPPED))）"$'\n'
    SUMMARY_OUTPUT+="AGENTS.md: ${agents_md}（轻量区块）"$'\n'
    SUMMARY_OUTPUT+="$config_line"$'\n'
    SUMMARY_OUTPUT+="命令:      $HOME/.local/bin/budget"$'\n'
    SUMMARY_OUTPUT+=""$'\n'
}

# ─── 安装摘要（specs/installer「交互选平台 + 安装摘要输出」）───────────────
print_summary() {
    echo ""
    echo -e "${GREEN}════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  BudgetBuddy 安装完成！${NC}"
    echo -e "${GREEN}════════════════════════════════════════════${NC}"
    echo ""
    printf '%s' "$SUMMARY_OUTPUT"
    echo "后续操作:"
    echo "  budget setup show          查看 Agent 模型配置"
    echo "  budget setup quickstart    快速上手向导"
    case "$BUDGET_INSTALL_PLATFORM" in
        codebuddy|both|all)
            echo "  CodeBuddy 会话内输入 /budget:start 启动工作流"
            ;;
    esac
    case "$BUDGET_INSTALL_PLATFORM" in
        opencode|both|all)
            echo "  OpenCode 会话内输入 /budget-start 启动工作流"
            ;;
    esac
    case "$BUDGET_INSTALL_PLATFORM" in
        claudecode|all)
            echo "  Claude Code 会话内输入 /budget:start 启动工作流"
            ;;
    esac
    case "$BUDGET_INSTALL_PLATFORM" in
        codex|all)
            echo "  Codex 会话内以自然语言触发 budget-workflow skill 启动工作流"
            ;;
    esac
    echo "  budget setup uninstall     卸载（按本地清单删除，清单外文件保留）"
    echo ""
}

# ─── 参数解析与入口 ────────────────────────────────────────────────────────
parse_args() {
    if [[ "${BUDGET_GLOBAL:-}" != "" ]]; then
        BUDGET_SCOPE_EXPLICIT=1
        if [[ "$BUDGET_GLOBAL" == "1" ]]; then
            BUDGET_INSTALL_GLOBAL=1
        fi
    fi
    local arg
    for arg in "$@"; do
        case "$arg" in
            --global)
                BUDGET_INSTALL_GLOBAL=1
                ;;
            --help|-h)
                show_help
                exit 0
                ;;
            --version|-v)
                show_version
                exit 0
                ;;
            *)
                print_error "未知参数: ${arg}（--help 查看用法）"
                ;;
        esac
    done
}

main() {
    parse_args "$@"
    select_platform
    select_scope
    check_dependencies
    resolve_source
    case "$BUDGET_INSTALL_PLATFORM" in
        codebuddy)  install_codebuddy ;;
        opencode)   install_opencode ;;
        claudecode) install_claudecode ;;
        codex)      install_codex ;;
        both)       install_codebuddy; install_opencode ;;
        all)        install_codebuddy; install_opencode; install_claudecode; install_codex ;;
        *)          print_error "内部错误: 未知平台 $BUDGET_INSTALL_PLATFORM" ;;
    esac
    print_summary
}

trap 'print_error "安装过程被中断"' INT TERM

main "$@"
