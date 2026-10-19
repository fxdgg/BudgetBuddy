#!/bin/bash
# BudgetBuddy install.sh — 双平台安装器（CodeBuddy + OpenCode）
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
#   BUDGET_PLATFORM   平台 codebuddy|opencode|both（跳过平台交互）
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
BUDGET_INSTALL_PLATFORM="codebuddy"   # codebuddy | opencode | both
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
  无参数       交互式选择平台（CodeBuddy / OpenCode / 两者）与作用域（项目/全局）
  --global     直接全局安装（所有项目共享）
  纯非交互     BUDGET_PLATFORM + BUDGET_GLOBAL 环境变量（CI / 脚本调用）

环境变量（BUDGET_* 前缀）:
  BUDGET_REPO_URL   下载源（默认 GitHub raw 占位地址，可指向自建镜像）
  BUDGET_VERSION    指定版本 tag（默认经 releases/latest 发现最新版）
  BUDGET_PLATFORM   codebuddy | opencode | both（跳过平台交互）
  BUDGET_GLOBAL     0=项目安装 / 1=全局安装（设置即跳过作用域交互）

安装落点:
  CodeBuddy  项目 → .codebuddy/          全局 → ~/.codebuddy/
             + 命令包装器 ~/.local/bin/budget + hooks 注入 settings.json
  OpenCode   项目 → .opencode/           全局 → ~/.config/opencode/
             + 管理面统一 ~/.budgetbuddy/（setup.sh/lib/models/personas/docs）
             + AGENTS.fragment.md 幂等合并进 AGENTS.md
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
        codebuddy|opencode|both)
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
    echo "  1) CodeBuddy — agents/commands/skills/rules/hooks → .codebuddy/（或 ~/.codebuddy/）"
    echo "  2) OpenCode  — agent/command/skill → opencode 目录 + 管理面 ~/.budgetbuddy/"
    echo "  3) 两者      — 依次执行 CodeBuddy 与 OpenCode 安装"
    echo ""
    echo -n "请输入 (1/2/3，默认 1): "
    local choice=""
    # 交互从 /dev/tty 读取（curl|bash 管道安装也支持）；无 tty 走默认
    if read -r choice < /dev/tty 2>/dev/null; then
        case "$choice" in
            2) BUDGET_INSTALL_PLATFORM="opencode" ;;
            3) BUDGET_INSTALL_PLATFORM="both" ;;
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
        codebuddy) [[ -n "$script_dir" && -f "$script_dir/dist/codebuddy/.manifest.json" ]] || local_ok=false ;;
        opencode)  [[ -n "$script_dir" && -f "$script_dir/dist/opencode/.manifest.json" ]] || local_ok=false ;;
        both)
            [[ -n "$script_dir" && -f "$script_dir/dist/codebuddy/.manifest.json" ]] || local_ok=false
            [[ -n "$script_dir" && -f "$script_dir/dist/opencode/.manifest.json" ]] || local_ok=false
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
    # 用法: sync_manifest_tree <dist_root> <manifest_file> <dest_root> <filter>
    #   filter: all（全部条目）| struct（agent/command/skill 前缀）| mgmt（其余）
    # 增量同步（specs/installer「manifest 增量同步」）:
    #   目标哈希与清单一致 → 跳过；不一致 → 覆盖；目标不存在 → 复制；
    #   清单外文件不枚举（一律保留）。统计入 SYNC_ADDED/UPDATED/SKIPPED。
    local dist_root="$1"
    local manifest_file="$2"
    local dest_root="$3"
    local filter="$4"
    local list_file=""
    list_file="$(mktemp 2>/dev/null || mktemp -t budget-sync)" || print_error "临时文件创建失败"
    if ! manifest_lines "$manifest_file" > "$list_file"; then
        rm -f "$list_file"
        print_error "产物清单解析失败: $manifest_file"
    fi
    local sha rel src dst kind dst_hash
    while IFS=$'\t' read -r sha rel; do
        [[ -n "$rel" ]] || continue
        # 条目分类（opencode 平台结构 vs 管理面；AGENTS.fragment.md 走合并）
        case "$rel" in
            agent/*|command/*|skill/*) kind="struct" ;;
            AGENTS.fragment.md)         kind="fragment" ;;
            *)                          kind="mgmt" ;;
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
    # 用法: upgrade_diff_cleanup <local_manifest> <new_manifest> <old_field> <new_filter> <root>
    # 升级差集清理（A12②）：本地旧清单 <old_field> 键集 − 新 manifest 过滤后
    # 键集 → 逐项删除 <root>/<rel>（清单外用户自建文件不在旧清单内，不受影响）。
    # 解析失败降级为警告（清理尽力而为，不阻断安装主流程）。
    local local_manifest="$1"
    local new_manifest="$2"
    local old_field="$3"
    local new_filter="$4"
    local root="$5"
    [[ -f "$local_manifest" ]] || return 0
    local list_file=""
    list_file="$(mktemp 2>/dev/null || mktemp -t budget-diff)" || return 0
    if ! BUDGET_LOCAL_MANIFEST="$local_manifest" BUDGET_NEW_MANIFEST="$new_manifest" \
        BUDGET_OLD_FIELD="$old_field" BUDGET_NEW_FILTER="$new_filter" \
        "$BUDGET_PYTHON" << 'PYEOF' > "$list_file"
import json
import os


def load(path):
    try:
        with open(path, encoding='utf-8') as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


old = load(os.environ['BUDGET_LOCAL_MANIFEST']).get(os.environ['BUDGET_OLD_FIELD'], {})
new_files = load(os.environ['BUDGET_NEW_MANIFEST']).get('files', {})
flt = os.environ['BUDGET_NEW_FILTER']


def keep(rel):
    if flt == 'all':
        return True
    is_struct = rel.startswith('agent/') or rel.startswith('command/') or rel.startswith('skill/')
    if flt == 'struct':
        return is_struct
    if flt == 'mgmt':
        return not is_struct and rel != 'AGENTS.fragment.md'
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
    #   mode: all      → files = 全部条目（codebuddy；排除 AGENTS.fragment.md）
    #         opencode → files = 管理面条目 + platform_files = 平台结构条目
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


def is_struct(rel):
    return rel.startswith('agent/') or rel.startswith('command/') or rel.startswith('skill/')


mode = os.environ['BUDGET_MODE']
if mode == 'opencode':
    files = {}
    platform_files = {}
    for rel, sha in src.items():
        if rel == 'AGENTS.fragment.md':
            continue
        if is_struct(rel):
            platform_files[rel] = sha
        else:
            files[rel] = sha
    out = {'files': files, 'platform_files': platform_files}
else:
    out = {'files': dict(
        (rel, sha) for rel, sha in src.items() if rel != 'AGENTS.fragment.md')}

dest = os.environ['BUDGET_DEST']
dir_name = os.path.dirname(dest) or '.'
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
    # 4) 升级差集清理（管理面 files + 平台结构 platform_files 两根分别清理）
    CLEANED=0
    upgrade_diff_cleanup "$mgmt_root/.budget-manifest.json" "$manifest_file" "files" "mgmt" "$mgmt_root"
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
        codebuddy|both)
            echo "  CodeBuddy 会话内输入 /budget:start 启动工作流"
            ;;
    esac
    case "$BUDGET_INSTALL_PLATFORM" in
        opencode|both)
            echo "  OpenCode 会话内输入 /budget-start 启动工作流"
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
        codebuddy) install_codebuddy ;;
        opencode)  install_opencode ;;
        both)      install_codebuddy; install_opencode ;;
        *)         print_error "内部错误: 未知平台 $BUDGET_INSTALL_PLATFORM" ;;
    esac
    print_summary
}

trap 'print_error "安装过程被中断"' INT TERM

main "$@"
