#!/usr/bin/env bash
# BudgetBuddy release 打包脚本（design.md §10 / §12-A12）。
#
# 流程：
#   1. 读取仓库根 VERSION 文件（去除空白字符）；
#   2. 清理同名旧产物（提前到门禁之前：门禁失败 ⇒ 无本版本产物，语义完整）；
#   3. python3 scripts/build.py --check --strict —— 构建双平台产物 + 品牌门禁 +
#      P0 一致性 strict 化，失败即中止，不产出任何 zip（发布链路拦截）；
#   4. 打包 dist/ 与 VERSION → budgetbuddy-<version>.zip；
#   5. 生成同名 .sha256 校验文件（安装器下载后强制校验，供应链安全）。
#
# 产物生成在仓库根（release 产物不提交 git，由发布流程上传托管方）。
# 用法：bash scripts/build-release.sh

set -euo pipefail

# ---------------------------------------------------------------------------
# 输出辅助（前缀风格与 build.py / scan-brand.py 保持一致）
# ---------------------------------------------------------------------------
print_info() { printf '[release] %s\n' "$1"; }
print_success() { printf '[release] 完成: %s\n' "$1"; }
print_error() { printf '[release] 失败: %s\n' "$1" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 仓库根定位（脚本位于 scripts/ 下，仓库根为其上一级）
# ---------------------------------------------------------------------------
cd "$(dirname "${BASH_SOURCE[0]}")/.." || print_error '无法定位仓库根目录'

# ---------------------------------------------------------------------------
# 步骤 1：读取 VERSION（去除全部空白字符，兼容 CRLF 与尾随换行）
# ---------------------------------------------------------------------------
read_version() {
    if [[ ! -f VERSION ]]; then
        print_error '未找到 VERSION 文件（仓库根）'
    fi
    VERSION="$(tr -d '[:space:]' < VERSION)"
    if [[ -z "$VERSION" ]]; then
        print_error 'VERSION 文件内容为空'
    fi
    # 版本号仅允许字母/数字/点/连字符，防止异常内容进入 zip 文件名。
    if [[ ! "$VERSION" =~ ^[0-9A-Za-z][0-9A-Za-z.-]*$ ]]; then
        print_error "VERSION 内容含非法字符: ${VERSION}（仅允许字母/数字/点/连字符）"
    fi
    print_info "目标版本: ${VERSION}"
}

# ---------------------------------------------------------------------------
# 步骤 2：清理同名旧产物（提前到门禁之前：门禁失败 ⇒ 无本版本产物，语义完整；
# zip 对已存在文件为增量更新，须先删除避免陈旧条目与陈旧校验值）
# ---------------------------------------------------------------------------
clean_stale_artifacts() {
    ZIP_FILE="budgetbuddy-${VERSION}.zip"
    rm -f "$ZIP_FILE" "${ZIP_FILE}.sha256"
    print_info "已清理旧产物（如存在）: ${ZIP_FILE} 与 ${ZIP_FILE}.sha256"
}

# ---------------------------------------------------------------------------
# 步骤 3：构建 + 品牌门禁 + P0 一致性 strict 化（失败即中止，不产出任何 zip）
# ---------------------------------------------------------------------------
run_gate() {
    print_info '运行构建与品牌门禁: python3 scripts/build.py --check --strict'
    if ! python3 scripts/build.py --check --strict; then
        print_error '门禁未通过（build.py --check --strict 退出非 0），发布中止，未产出 zip'
    fi
    print_success '构建与品牌门禁通过（strict）'
}

# ---------------------------------------------------------------------------
# 步骤 4：打包 dist/ 与 VERSION → budgetbuddy-<version>.zip
# ---------------------------------------------------------------------------
build_zip() {
    if ! command -v zip >/dev/null 2>&1; then
        print_error '未找到 zip 命令，请安装 zip 后重试'
    fi
    ZIP_FILE="budgetbuddy-${VERSION}.zip"
    print_info "打包 dist/ 与 VERSION → ${ZIP_FILE}"
    zip -r -q "$ZIP_FILE" dist VERSION -x '*__pycache__*' '*.pyc' '*.DS_Store*'
    if [[ ! -f "$ZIP_FILE" ]]; then
        print_error "zip 产物未生成: ${ZIP_FILE}"
    fi
    print_success "zip 打包完成: ${ZIP_FILE}"
}

# ---------------------------------------------------------------------------
# 步骤 4：生成同名 .sha256 校验文件
# 优先 shasum（macOS 自带），回退 sha256sum（Linux 常见），两者皆无则报错。
# 输出为「<摘要>  <文件名>」标准格式，可被 shasum -c / sha256sum -c 直接校验。
# ---------------------------------------------------------------------------
gen_sha256() {
    SHA_FILE="${ZIP_FILE}.sha256"
    print_info "生成校验文件: ${SHA_FILE}"
    if command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$ZIP_FILE" > "$SHA_FILE"
    elif command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$ZIP_FILE" > "$SHA_FILE"
    else
        print_error '未找到 SHA256 计算工具（shasum / sha256sum 均未安装），无法生成校验文件'
    fi
    if [[ ! -s "$SHA_FILE" ]]; then
        print_error "校验文件生成异常（内容为空）: ${SHA_FILE}"
    fi
    print_success "校验文件生成完成: ${SHA_FILE}"
}

# ---------------------------------------------------------------------------
# 汇总输出（产物路径 + 字节数 + 校验值）
# ---------------------------------------------------------------------------
report() {
    local zip_size sha_size
    zip_size="$(wc -c < "$ZIP_FILE" | tr -d '[:space:]')"
    sha_size="$(wc -c < "$SHA_FILE" | tr -d '[:space:]')"
    printf '[release] 产物清单:\n'
    printf '  %s（%s 字节）\n' "$ZIP_FILE" "$zip_size"
    printf '  %s（%s 字节）\n' "$SHA_FILE" "$sha_size"
    printf '[release] SHA256: %s\n' "$(cut -d' ' -f1 "$SHA_FILE")"
}

main() {
    read_version
    clean_stale_artifacts
    run_gate
    build_zip
    gen_sha256
    report
}

main "$@"
