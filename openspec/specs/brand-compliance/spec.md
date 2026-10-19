# brand-compliance Specification

## Purpose
TBD - created by archiving change foundation. Update Purpose after archive.
## Requirements
### Requirement: 违禁词扫描门禁

`python3 scripts/scan-brand.py` 扫描固定范围：`core/`、`dist/`、`scripts/`、`install.sh`、`README.md`、`README_CN.md`、`CHANGELOG.md`（不扩到 docs/ 与 openspec/）。违禁词表（大小写不敏感；词类涵盖：参照项目名、归属组织与公司标识、内部渠道域名、中文角色系称呼、旧环境变量前缀及其任意前后缀变体）以转义编码形式存储于 `scripts/scan-brand.py` 作为唯一权威载体，文档不出现字面量。命中输出 `文件:行号:摘要` 并退出码 1；全部干净退出码 0；非文本/解码失败文件跳过并告警（design.md §5）。【MUST】

#### Scenario: 命中违禁词
- **WHEN** 扫描范围内任一文本文件的某行包含违禁词表中任一词汇（任意大小写形式）
- **THEN** 脚本以退出码 1 结束，输出命中文件的路径、行号与该行摘要

#### Scenario: 大小写与前后缀变体
- **WHEN** 文件中出现违禁词的大小写混合或带前后缀的变体（词表见 `scripts/scan-brand.py` 权威载体）
- **THEN** 同样命中并 exit 1

#### Scenario: 全部干净
- **WHEN** 扫描范围内所有文本文件零违禁词
- **THEN** 脚本以退出码 0 结束

#### Scenario: 二进制或无法解码的文件
- **WHEN** 扫描遇到非文本/解码失败文件（如图片）
- **THEN** 跳过该文件并输出告警，不视为命中也不中断扫描

### Requirement: 门禁接入构建与发布链路

品牌门禁通过 `build.py --check` 自动执行，且 `scripts/build-release.sh` 打包前强制先跑 `build.py --check`；门禁失败时不得产出 release zip（design.md §4/§10）。【MUST】

#### Scenario: 发布链路拦截
- **WHEN** 违禁词存在时运行 build-release.sh
- **THEN** 打包中止，不生成 budgetbuddy-<version>.zip

### Requirement: 本变更新增产物合规

本变更新增产物（proposal/design/specs/tasks，即 `openspec/changes/foundation/**`）中的参照项目指针一律使用 `REF:` 前缀 + 相对路径 + 通配 glob 形式（品牌词以 `*` 通配），不得出现参照项目根路径或品牌词；已确认的设计文档 `docs/plans/**` 豁免（其组件对等清单需引用参照项目组件名，且不属本变更产出，design.md §5 已给出豁免理由）；违禁词表定义载体行豁免见下一 Requirement（design.md 头部约定/§5）。【MUST】

#### Scenario: 检查本变更产物
- **WHEN** reviewer 审计 openspec/changes/foundation/**
- **THEN** 除词表定义载体行外，硬性词表词汇零出现；参照文件指针均为 `REF:<glob>` 形式，无参照项目根路径明文

#### Scenario: docs/plans 豁免
- **WHEN** docs/plans/ 已确认设计文档含参照项目组件名等品牌词引用
- **THEN** 不视为本变更品牌违规（豁免理由见 design.md §5），本变更不修改该目录

### Requirement: 违禁词表载体豁免

违禁词表必须以字面量定义的载体共三类：`scripts/scan-brand.py`（词表代码）、`design.md` §5 词表行、`specs/brand-compliance` 词表行；三类载体不因词表字面量本身判违规（design.md §12-A10）。机器扫描层面 scan-brand.py 执行时跳过自身文件（其位于扫描范围 `scripts/` 内）；openspec 产物审计明确豁免上述词表定义行。载体文件的其余内容仍正常扫描/审计。【MUST】

#### Scenario: 扫描器扫描自身
- **WHEN** 运行 scan-brand.py 扫描 scripts/ 目录
- **THEN** 脚本跳过自身文件路径，不因词表字面量命中而失败

#### Scenario: scripts 下其他文件含违禁词
- **WHEN** scripts/ 目录中 scan-brand.py 之外的任何文件（如 build.py）包含违禁词
- **THEN** 正常命中并 exit 1

#### Scenario: 词表定义行豁免
- **WHEN** 审计 design.md §5 与 specs/brand-compliance 的违禁词表定义行
- **THEN** 其中的违禁词字面量不判违规；同文件其余位置出现违禁词则仍判违规

