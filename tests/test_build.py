#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build 构建系统单测（design.md §4/§12-A5/A7 + specs/build-pipeline）。

覆盖固定用例清单（tasks.md 1.1）：
① 引号内冒号；② 值后行内注释；③ 空字符串 ""；④ 块式 list 项为 map；
⑤ 锚点/多行字符串/YAML tag 报不支持错误；⑥ 两次构建 manifest diff 为空；
⑦ 校验失败 dist 保持构建前原样（原子性）；⑧ 空 core 冒烟 exit 0；
⑨ agents 存在但 models 缺失 → 产物无 model 字段并告警。

违禁词样本一律运行时字符串拼接构造（tests/ 在扫描范围外，双保险约束）。
"""

from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / 'scripts'
BUILD_SCRIPT = SCRIPTS_DIR / 'build.py'
PLATFORM_YAML_DIR = Path(__file__).resolve().parent.parent / 'core' / 'platform'
REPO_ROOT = Path(__file__).resolve().parent.parent
REAL_MODELS_JSON = REPO_ROOT / 'core' / 'models' / 'budget-models.json'

sys.path.insert(0, str(SCRIPTS_DIR))
import build  # noqa: E402  pylint: disable=wrong-import-position

# 违禁词样本（运行时拼接构造，见模块 docstring）。
SAMPLE_FORBIDDEN = 'beg' + 'gar'

# §6 十角色表：(name, model_role, tools, edit_allow, bash_allow, max_turns)。
AGENT_TABLE = [
    ('architect', 'architect',
     ['read', 'write', 'edit', 'bash', 'grep', 'glob', 'webfetch', 'websearch'],
     ['openspec/**', 'docs/**'], ['git *', 'openspec *'], 80),
    ('coder-lite', 'coder_lite',
     ['read', 'write', 'edit', 'bash', 'grep', 'glob'],
     ['*'], ['*'], 35),
    ('coder-standard', 'coder_standard',
     ['read', 'write', 'edit', 'bash', 'grep', 'glob'],
     ['*'], ['*'], 50),
    ('coder-senior', 'coder_senior',
     ['read', 'write', 'edit', 'bash', 'grep', 'glob', 'webfetch', 'websearch'],
     ['*'], ['*'], 70),
    ('reviewer', 'reviewer',
     ['read', 'bash', 'grep', 'glob'],
     [], ['git *'], 40),
    ('reviewer-b', 'reviewer_b',
     ['read', 'bash', 'grep', 'glob'],
     [], ['git *'], 40),
    ('tester', 'tester',
     ['read', 'bash', 'grep', 'glob'],
     [], ['*'], 40),
    ('recorder', 'recorder',
     ['read', 'write', 'edit', 'bash', 'grep', 'glob'],
     ['openspec/**', 'docs/**'], ['git *'], 30),
    ('director', 'director',
     ['read', 'grep', 'glob'],
     [], [], 15),
    ('goal-evaluator', 'goal_evaluator',
     ['read', 'grep', 'glob'],
     [], [], 8),
]


def make_agent_md(row, body='你是 {{TASK_TOOL}} 执行者，负责示例任务。\n'):
    """按 §6 角色表行生成最小合法 agent 中立源文件。"""
    name, model_role, tools, edit_allow, bash_allow, max_turns = row
    lines = [
        '---',
        f'name: {name}',
        f'description: {name} 角色示例，用于构建管线验证。',
        f'model_role: {model_role}',
        'tools: [' + ', '.join(tools) + ']',
        'permissions:',
        '  edit_allow: ' + json.dumps(edit_allow),
        '  bash_allow: ' + json.dumps(bash_allow),
        f'max_turns: {max_turns}',
        '---',
        body,
    ]
    return '\n'.join(lines)


def write_agents(root, body='你是 {{TASK_TOOL}} 执行者，负责示例任务。\n'):
    """在临时仓库写入全部十个角色 agent 文件。"""
    for row in AGENT_TABLE:
        target = root / 'core' / 'agents' / f'{row[0]}.md'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(make_agent_md(row, body), encoding='utf-8')


def make_models_json():
    """生成测试用 budget-models.json 数据（完整结构，通过构建期结构校验）。

    目录条目 id 形如 cb-<role 连字符形式>（与真实目录 ID 形态一致，无下划线）；
    codebuddy 预设值即该 ID，opencode 预设值为 deepseek/<id>（provider ∈ 白名单
    且 model 部分在目录中，条目 platform 含双平台）；provider_map 将 demo 组
    映射到 deepseek provider（与 opencode 预设前缀一致）。
    """
    roles = [row[1] for row in AGENT_TABLE]
    role_ids = {role: f'cb-{role.replace("_", "-")}' for role in roles}
    entries = [
        {
            'id': role_ids[role],
            'tier': 'mid',
            'cost': 'x1.00',
            'tags': ['general'],
            'platform': ['codebuddy', 'opencode'],
        }
        for role in roles
    ]
    return {
        '_meta': {
            'description': '测试模型目录',
            'updated_at': '2026-01-01',
            'update_command': 'budget setup models',
        },
        'aliases': {'demo': role_ids['architect']},
        'roles': roles,
        'models': {'paid': {'demo': entries}, 'free': {}},
        'provider_map': {'demo': 'deepseek'},
        'platforms': {
            'codebuddy': {'presets': {
                preset: dict(role_ids)
                for preset in ('economic', 'balanced', 'quality')}},
            'opencode': {'presets': {
                preset: {role: f'deepseek/{model_id}' for role, model_id in role_ids.items()}
                for preset in ('economic', 'balanced', 'quality')}},
        },
    }


def write_full_models(root):
    """在临时仓库写入完整 budget-models.json（make_models_json 数据，按键排序）。"""
    target = root / 'core' / 'models' / 'budget-models.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(make_models_json(), indent=2, sort_keys=True, ensure_ascii=False) + '\n',
        encoding='utf-8')


def run_build(root, *args):
    """以子进程运行构建脚本（--root 指向临时仓库）。"""
    return subprocess.run(
        [sys.executable, str(BUILD_SCRIPT), '--root', str(root), *args],
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=False,
    )


def snapshot_tree(base):
    """快照目录树：{相对路径: sha256}（与 manifest files 结构一致）。"""
    result = {}
    if not base.is_dir():
        return result
    for path in sorted(base.rglob('*')):
        if path.is_file():
            rel = path.relative_to(base).as_posix()
            result[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


class YamlSubsetParserTests(unittest.TestCase):
    """YAML 子集解析器固定用例（tasks.md 1.1 清单 ①-⑤ + 边界）。"""

    def test_quoted_value_with_colon(self):
        """① 引号内冒号：值形如 "/{group}:{name}"。"""
        data = build.parse_yaml('command:\n  invoke: "/{group}:{name}"\n')
        self.assertEqual(data, {'command': {'invoke': '/{group}:{name}'}})

    def test_inline_comment_after_value(self):
        """② 值后行内注释：注释剥离，值不受影响。"""
        data = build.parse_yaml('platform: codebuddy  # 平台标识\n')
        self.assertEqual(data, {'platform': 'codebuddy'})

    def test_empty_string_value(self):
        """③ 空字符串 ""。"""
        data = build.parse_yaml('hook: ""\n')
        self.assertEqual(data, {'hook': ''})

    def test_block_list_of_maps(self):
        """④ 块式 list 项为 map（extra_outputs 形态）。"""
        text = (
            'extra_outputs:\n'
            '  - kind: agents_fragment\n'
            '    source: "rules/**"\n'
            '    dest: "AGENTS.fragment.md"\n'
            '    markers: ["<!-- BudgetBuddy:begin -->", "<!-- BudgetBuddy:end -->"]\n'
        )
        data = build.parse_yaml(text)
        self.assertEqual(data, {'extra_outputs': [{
            'kind': 'agents_fragment',
            'source': 'rules/**',
            'dest': 'AGENTS.fragment.md',
            'markers': ['<!-- BudgetBuddy:begin -->', '<!-- BudgetBuddy:end -->'],
        }]})

    def test_block_list_of_scalars(self):
        """块式 list 标量项。"""
        data = build.parse_yaml('drop:\n  - model_role\n  - permissions\n')
        self.assertEqual(data, {'drop': ['model_role', 'permissions']})

    def test_anchor_rejected(self):
        """⑤ 锚点不支持：报错含行号与原因。"""
        with self.assertRaises(build.YamlParseError) as ctx:
            build.parse_yaml('key: &anchor value\n')
        self.assertIn('锚点', str(ctx.exception))
        self.assertIn('第 1 行', str(ctx.exception))

    def test_alias_rejected(self):
        """⑤ 别名引用不支持。"""
        with self.assertRaises(build.YamlParseError) as ctx:
            build.parse_yaml('key: *alias\n')
        self.assertIn('别名', str(ctx.exception))

    def test_tag_rejected(self):
        """⑤ YAML tag 不支持。"""
        with self.assertRaises(build.YamlParseError) as ctx:
            build.parse_yaml('key: !!str value\n')
        self.assertIn('tag', str(ctx.exception))

    def test_multiline_string_rejected(self):
        """⑤ 多行字符串标记（| 与 > 系列）不支持。"""
        for marker in ('|', '>', '|-', '>-'):
            with self.assertRaises(build.YamlParseError):
                build.parse_yaml(f'key: {marker}\n')

    def test_flow_list(self):
        """行内流式 list（裸项与引号项）。"""
        data = build.parse_yaml('drop: [model_role, permissions]\n')
        self.assertEqual(data, {'drop': ['model_role', 'permissions']})
        data = build.parse_yaml('edit_allow: ["openspec/**", "docs/**"]\n')
        self.assertEqual(data, {'edit_allow': ['openspec/**', 'docs/**']})

    def test_empty_flow_list(self):
        """空流式 list（[] 显式全禁止形态）。"""
        data = build.parse_yaml('edit_allow: []\n')
        self.assertEqual(data, {'edit_allow': []})

    def test_flow_map(self):
        """行内流式 map。"""
        data = build.parse_yaml('rule: { edit_all: "acceptEdits", edit_restricted: "plan" }\n')
        self.assertEqual(data, {'rule': {'edit_all': 'acceptEdits', 'edit_restricted': 'plan'}})

    def test_nested_maps(self):
        """两空格缩进嵌套 map（含 docs 显式 map）。"""
        text = 'routing:\n  agent: "agents/{name}.md"\n  docs:\n    PERSONAS.md: "docs/PERSONAS.md"\n'
        data = build.parse_yaml(text)
        self.assertEqual(data, {'routing': {
            'agent': 'agents/{name}.md',
            'docs': {'PERSONAS.md': 'docs/PERSONAS.md'},
        }})

    def test_null_value(self):
        """null 值（routing.docs 不分发条目）。"""
        data = build.parse_yaml('docs:\n  opencode-setup-notes.md: null\n')
        self.assertIsNone(data['docs']['opencode-setup-notes.md'])

    def test_hash_inside_quotes_not_comment(self):
        """引号内的 # 不剥离为注释。"""
        data = build.parse_yaml('a: "x#y"\n')
        self.assertEqual(data, {'a': 'x#y'})

    def test_int_scalar(self):
        """整数标量（max_turns）。"""
        data = build.parse_yaml('max_turns: 80\n')
        self.assertEqual(data, {'max_turns': 80})

    def test_comment_only_line_ignored(self):
        """整行注释（含缩进注释）跳过。"""
        data = build.parse_yaml('# 注释\nkey: value\n   # 缩进注释\n')
        self.assertEqual(data, {'key': 'value'})

    def test_tab_indent_rejected(self):
        """tab 缩进不支持。"""
        with self.assertRaises(build.YamlParseError):
            build.parse_yaml('key:\n\tsub: 1\n')

    def test_duplicate_key_rejected(self):
        """重复键报错。"""
        with self.assertRaises(build.YamlParseError):
            build.parse_yaml('a: 1\na: 2\n')

    def test_real_codebuddy_yaml_parses(self):
        """真实 codebuddy.yaml 全字段正确加载（锁定 DSL 实际语法形态）。"""
        text = (PLATFORM_YAML_DIR / 'codebuddy.yaml').read_text(encoding='utf-8')
        data = build.parse_yaml(text)
        self.assertEqual(data['platform'], 'codebuddy')
        self.assertEqual(data['output'], 'dist/codebuddy')
        self.assertEqual(data['routing']['agent'], 'agents/{name}.md')
        self.assertIsNone(data['routing']['docs']['opencode-setup-notes.md'])
        self.assertEqual(data['routing']['docs']['PERSONAS.md'], 'docs/PERSONAS.md')
        self.assertEqual(data['agent_frontmatter']['emit']['tools'], '{tools|pascal}')
        self.assertEqual(data['agent_frontmatter']['emit']['max_turns'], '{max_turns}')
        self.assertEqual(data['agent_frontmatter']['permission_mode_rule'],
                         {'edit_all': 'acceptEdits', 'edit_restricted': 'plan'})
        self.assertEqual(data['body_variables']['TASK_TOOL'], 'Agent')
        self.assertEqual(data['body_variables']['PROJECT_DOC'], '')

    def test_real_opencode_yaml_parses(self):
        """真实 opencode.yaml 全字段正确加载（含 extra_outputs 块式 list-of-map）。"""
        text = (PLATFORM_YAML_DIR / 'opencode.yaml').read_text(encoding='utf-8')
        data = build.parse_yaml(text)
        self.assertEqual(data['platform'], 'opencode')
        self.assertEqual(data['routing']['agent'], 'agent/{name}.md')
        self.assertEqual(data['routing']['command'], 'command/{group}-{name}.md')
        self.assertEqual(data['routing']['hook'], '')
        self.assertEqual(data['routing']['rule'], 'AGENTS.fragment.md')
        self.assertEqual(data['routing']['docs']['opencode-setup-notes.md'], 'docs/setup-notes.md')
        self.assertEqual(data['agent_frontmatter']['emit']['mode'], 'subagent')
        self.assertEqual(data['agent_frontmatter']['emit']['permission'], '{permission_map}')
        self.assertEqual(data['body_variables']['TASK_TOOL'], 'task')
        self.assertEqual(data['body_variables']['SKILL_NS'], '')
        self.assertEqual(data['extra_outputs'], [{
            'kind': 'agents_fragment',
            'source': 'rules/**',
            'dest': 'AGENTS.fragment.md',
            'markers': ['<!-- BudgetBuddy:begin -->', '<!-- BudgetBuddy:end -->'],
        }])


class DslValidationTests(unittest.TestCase):
    """DSL schema 校验（§3.5）。"""

    def test_missing_routing_key(self):
        """DSL 缺 routing 键：BuildError 指出缺失字段（验收标准用例）。"""
        with self.assertRaises(build.BuildError) as ctx:
            build.validate_dsl({'platform': 'x', 'output': 'dist/x'}, 'test.yaml')
        self.assertIn('routing', str(ctx.exception))

    def test_missing_routing_subkey(self):
        """routing 缺 agent 子键：报错指出 routing 与 agent。"""
        dsl = build.parse_yaml((PLATFORM_YAML_DIR / 'codebuddy.yaml').read_text(encoding='utf-8'))
        del dsl['routing']['agent']
        with self.assertRaises(build.BuildError) as ctx:
            build.validate_dsl(dsl, 'test.yaml')
        self.assertIn('routing', str(ctx.exception))
        self.assertIn('agent', str(ctx.exception))

    def test_real_yamls_valid(self):
        """真实两份 yaml 均通过 DSL schema 校验。"""
        for name in ('codebuddy.yaml', 'opencode.yaml'):
            dsl = build.parse_yaml((PLATFORM_YAML_DIR / name).read_text(encoding='utf-8'))
            result = build.validate_dsl(dsl, name)
            self.assertIs(result, dsl)


class DslPathEscapeTests(unittest.TestCase):
    """P2-1 路径模板统一防逃逸：全部路由值拒绝 .. 片段与绝对路径。"""

    @staticmethod
    def load_dsl(name):
        """加载真实平台 yaml 为基准 DSL。"""
        return build.parse_yaml((PLATFORM_YAML_DIR / name).read_text(encoding='utf-8'))

    def test_routing_dotdot_rejected(self):
        """routing 八类值含 ../ → BuildError（报错含字段名与值）。"""
        dsl = self.load_dsl('codebuddy.yaml')
        dsl['routing']['agent'] = 'agents/../{name}.md'
        with self.assertRaises(build.BuildError) as ctx:
            build.validate_dsl(dsl, 'test.yaml')
        self.assertIn('routing.agent', str(ctx.exception))
        self.assertIn('..', str(ctx.exception))

    def test_routing_absolute_path_rejected(self):
        """routing 值以 / 开头（绝对路径）→ BuildError。"""
        dsl = self.load_dsl('codebuddy.yaml')
        dsl['routing']['skill'] = '/skills/{skill}/'
        with self.assertRaises(build.BuildError) as ctx:
            build.validate_dsl(dsl, 'test.yaml')
        self.assertIn('routing.skill', str(ctx.exception))
        self.assertIn('绝对路径', str(ctx.exception))

    def test_docs_dest_escape_rejected(self):
        """routing.docs 目标路径含 .. → BuildError。"""
        dsl = self.load_dsl('codebuddy.yaml')
        dsl['routing']['docs']['PERSONAS.md'] = 'docs/../PERSONAS.md'
        with self.assertRaises(build.BuildError) as ctx:
            build.validate_dsl(dsl, 'test.yaml')
        self.assertIn('routing.docs', str(ctx.exception))

    def test_extra_outputs_escape_rejected(self):
        """extra_outputs dest 含 .. 与 source 绝对路径 → BuildError。"""
        dsl = self.load_dsl('opencode.yaml')
        # kind 改为非 agents_fragment 以绕过 routing.rule 一致性检查（聚焦路径检查）。
        dsl['extra_outputs'][0]['kind'] = 'other'
        dsl['extra_outputs'][0]['dest'] = '../AGENTS.fragment.md'
        with self.assertRaises(build.BuildError) as ctx:
            build.validate_dsl(dsl, 'test.yaml')
        self.assertIn('extra_outputs[0].dest', str(ctx.exception))
        dsl['extra_outputs'][0]['dest'] = 'AGENTS.fragment.md'
        dsl['extra_outputs'][0]['source'] = '/rules/**'
        with self.assertRaises(build.BuildError) as ctx:
            build.validate_dsl(dsl, 'test.yaml')
        self.assertIn('extra_outputs[0].source', str(ctx.exception))

    def test_legal_routing_values_unaffected(self):
        """合法值不受影响：真实两份 yaml 与占位符深层模板均通过。"""
        for name in ('codebuddy.yaml', 'opencode.yaml'):
            build.validate_dsl(self.load_dsl(name), name)
        dsl = self.load_dsl('codebuddy.yaml')
        dsl['routing']['agent'] = 'agents/deep/{name}.md'
        build.validate_dsl(dsl, 'test.yaml')


class EmitWhitelistTests(unittest.TestCase):
    """P2-2 emit 表达式白名单：形如 {xxx} 的表达式必须 ∈ 已知占位符集合。"""

    @staticmethod
    def load_dsl(name):
        """加载真实平台 yaml 为基准 DSL。"""
        return build.parse_yaml((PLATFORM_YAML_DIR / name).read_text(encoding='utf-8'))

    def test_tools_placeholder_without_pascal_rejected(self):
        """{tools}（裸形态）→ BuildError（design §3.5 emit 域仅 {tools|pascal}，
        无裸 {tools}；越权表达式会经 rewrite_agent 字面量分支静默输出错误产物）。"""
        dsl = self.load_dsl('codebuddy.yaml')
        dsl['agent_frontmatter']['emit']['tools'] = '{tools}'
        with self.assertRaises(build.BuildError) as ctx:
            build.validate_dsl(dsl, 'test.yaml')
        self.assertIn('{tools}', str(ctx.exception))
        self.assertIn('占位符', str(ctx.exception))

    def test_routing_placeholder_in_emit_rejected(self):
        """{skill}（routing 域占位符混入 emit）→ BuildError（域收敛）。"""
        dsl = self.load_dsl('codebuddy.yaml')
        dsl['agent_frontmatter']['emit']['tools'] = '{skill}'
        with self.assertRaises(build.BuildError) as ctx:
            build.validate_dsl(dsl, 'test.yaml')
        self.assertIn('{skill}', str(ctx.exception))
        self.assertIn('占位符', str(ctx.exception))

    def test_typo_placeholder_rejected(self):
        """{toolz}（拼写错误）→ BuildError（防静默字面量输出）。"""
        dsl = self.load_dsl('codebuddy.yaml')
        dsl['agent_frontmatter']['emit']['tools'] = '{toolz}'
        with self.assertRaises(build.BuildError) as ctx:
            build.validate_dsl(dsl, 'test.yaml')
        self.assertIn('toolz', str(ctx.exception))
        self.assertIn('占位符', str(ctx.exception))

    def test_literal_expression_unaffected(self):
        """字面量表达式（如 subagent）不受白名单影响。"""
        dsl = self.load_dsl('opencode.yaml')
        dsl['agent_frontmatter']['emit']['mode'] = 'subagent'
        build.validate_dsl(dsl, 'test.yaml')


class RoutingPlaceholderTests(unittest.TestCase):
    """P2-1 routing 模板占位符域校验：{xxx} 必须 ∈ {name}/{skill}/{group}/{path}。"""

    @staticmethod
    def load_dsl(name):
        """加载真实平台 yaml 为基准 DSL。"""
        return build.parse_yaml((PLATFORM_YAML_DIR / name).read_text(encoding='utf-8'))

    def test_routing_typo_placeholder_rejected(self):
        """agents/{nmae}.md（拼写错误）→ BuildError（防静默落位字面量路径）。"""
        dsl = self.load_dsl('codebuddy.yaml')
        dsl['routing']['agent'] = 'agents/{nmae}.md'
        with self.assertRaises(build.BuildError) as ctx:
            build.validate_dsl(dsl, 'test.yaml')
        self.assertIn('nmae', str(ctx.exception))
        self.assertIn('routing.agent', str(ctx.exception))
        self.assertIn('占位符', str(ctx.exception))

    def test_routing_emit_expression_leaked_rejected(self):
        """routing 值使用 emit 域表达式（{tools}）→ BuildError（域不混用）。"""
        dsl = self.load_dsl('codebuddy.yaml')
        dsl['routing']['agent'] = 'agents/{tools}.md'
        with self.assertRaises(build.BuildError) as ctx:
            build.validate_dsl(dsl, 'test.yaml')
        self.assertIn('{tools}', str(ctx.exception))

    def test_docs_dest_placeholder_rejected(self):
        """routing.docs 目标路径含未知占位符 → BuildError。"""
        dsl = self.load_dsl('codebuddy.yaml')
        dsl['routing']['docs']['PERSONAS.md'] = 'docs/{nmae}.md'
        with self.assertRaises(build.BuildError) as ctx:
            build.validate_dsl(dsl, 'test.yaml')
        self.assertIn('routing.docs', str(ctx.exception))

    def test_hook_placeholder_rejected(self):
        """routing.hook 含未知占位符 → BuildError。"""
        dsl = self.load_dsl('codebuddy.yaml')
        dsl['routing']['hook'] = 'hooks/{hok}.py'
        with self.assertRaises(build.BuildError) as ctx:
            build.validate_dsl(dsl, 'test.yaml')
        self.assertIn('routing.hook', str(ctx.exception))

    def test_legal_routing_placeholders_pass(self):
        """合法占位符（含 design §3.5 定义但当前未使用的 {path}）不误伤。"""
        dsl = self.load_dsl('codebuddy.yaml')
        dsl['routing']['agent'] = 'agents/{path}/{name}.md'
        build.validate_dsl(dsl, 'test.yaml')


class FrontmatterValidationTests(unittest.TestCase):
    """frontmatter 加载与中立源校验（§3.1）。"""

    VALID_FM = {
        'name': 'architect',
        'description': '架构师。',
        'model_role': 'architect',
        'tools': ['read', 'write'],
        'permissions': {'edit_allow': ['openspec/**'], 'bash_allow': ['git *']},
        'max_turns': 80,
    }

    def test_load_frontmatter_ok(self):
        text = '---\nname: architect\ndescription: 架构。\n---\n\n正文内容。\n'
        fm, body = build.load_frontmatter(text, 'a.md')
        self.assertEqual(fm, {'name': 'architect', 'description': '架构。'})
        self.assertIn('正文内容', body)

    def test_load_frontmatter_missing_start(self):
        with self.assertRaises(build.BuildError):
            build.load_frontmatter('name: x\n', 'a.md')

    def test_load_frontmatter_unclosed(self):
        with self.assertRaises(build.BuildError):
            build.load_frontmatter('---\nname: x\n', 'a.md')

    def test_validate_agent_ok(self):
        build.validate_agent(self.VALID_FM, '正文。', 'architect', 'a.md', None)

    def test_validate_agent_name_mismatch(self):
        with self.assertRaises(build.BuildError) as ctx:
            build.validate_agent(self.VALID_FM, '正文。', 'other', 'a.md', None)
        self.assertIn('不一致', str(ctx.exception))

    def test_validate_agent_missing_field(self):
        fm = dict(self.VALID_FM)
        del fm['model_role']
        with self.assertRaises(build.BuildError) as ctx:
            build.validate_agent(fm, '正文。', 'architect', 'a.md', None)
        self.assertIn('model_role', str(ctx.exception))

    def test_validate_agent_tool_not_whitelisted(self):
        fm = dict(self.VALID_FM, tools=['read', 'hack'])
        with self.assertRaises(build.BuildError) as ctx:
            build.validate_agent(fm, '正文。', 'architect', 'a.md', None)
        self.assertIn('hack', str(ctx.exception))

    def test_validate_agent_mixed_permission_state(self):
        """["*"] 与具体条目混合判非法。"""
        fm = dict(self.VALID_FM)
        fm['permissions'] = {'edit_allow': ['*', 'docs/**'], 'bash_allow': ['*']}
        with self.assertRaises(build.BuildError) as ctx:
            build.validate_agent(fm, '正文。', 'architect', 'a.md', None)
        self.assertIn('三态', str(ctx.exception))

    def test_validate_agent_permission_not_list(self):
        """非列表形态判非法。"""
        fm = dict(self.VALID_FM)
        fm['permissions'] = {'edit_allow': 'docs/**', 'bash_allow': ['*']}
        with self.assertRaises(build.BuildError):
            build.validate_agent(fm, '正文。', 'architect', 'a.md', None)

    def test_validate_agent_empty_lists_valid(self):
        """[] 为合法显式全禁止形态（reviewer 只读形态）。"""
        fm = dict(self.VALID_FM, tools=['read', 'bash', 'grep', 'glob'])
        fm['permissions'] = {'edit_allow': [], 'bash_allow': ['git *']}
        build.validate_agent(fm, '正文。', 'architect', 'a.md', None)

    def test_validate_agent_bash_contradiction(self):
        """bash_allow 为 [] 但 tools 含 bash：语义不一致。"""
        fm = dict(self.VALID_FM, tools=['read', 'bash'])
        fm['permissions'] = {'edit_allow': ['*'], 'bash_allow': []}
        with self.assertRaises(build.BuildError) as ctx:
            build.validate_agent(fm, '正文。', 'architect', 'a.md', None)
        self.assertIn('语义不一致', str(ctx.exception))

    def test_validate_agent_edit_contradiction(self):
        """edit_allow 为 [] 但 tools 含 write：语义不一致。"""
        fm = dict(self.VALID_FM, tools=['read', 'write'])
        fm['permissions'] = {'edit_allow': [], 'bash_allow': ['*']}
        with self.assertRaises(build.BuildError):
            build.validate_agent(fm, '正文。', 'architect', 'a.md', None)

    def test_validate_agent_bad_model_role(self):
        with self.assertRaises(build.BuildError) as ctx:
            build.validate_agent(self.VALID_FM, '正文。', 'architect', 'a.md', ['other_role'])
        self.assertIn('model_role', str(ctx.exception))

    def test_validate_agent_bad_max_turns(self):
        for bad in (0, -1, '80', 1.5, True):
            fm = dict(self.VALID_FM, max_turns=bad)
            with self.assertRaises(build.BuildError):
                build.validate_agent(fm, '正文。', 'architect', 'a.md', None)

    def test_validate_agent_empty_body(self):
        with self.assertRaises(build.BuildError) as ctx:
            build.validate_agent(self.VALID_FM, '   \n', 'architect', 'a.md', None)
        self.assertIn('非空正文', str(ctx.exception))

    def test_validate_command_ok(self):
        fm = {'name': 'Budget: Start', 'description': '启动。', 'argument-hint': '<描述>'}
        build.validate_command(fm, '正文。', 'c.md')

    def test_validate_command_missing_name(self):
        fm = {'description': '启动。'}
        with self.assertRaises(build.BuildError) as ctx:
            build.validate_command(fm, '正文。', 'c.md')
        self.assertIn('name', str(ctx.exception))

    def test_validate_command_missing_description(self):
        fm = {'name': 'Budget: Start'}
        with self.assertRaises(build.BuildError):
            build.validate_command(fm, '正文。', 'c.md')

    def test_validate_command_bad_group(self):
        fm = {'name': 'Foo: Bar', 'description': 'x'}
        with self.assertRaises(build.BuildError) as ctx:
            build.validate_command(fm, '正文。', 'c.md')
        self.assertIn('Foo', str(ctx.exception))


class PermissionMappingTests(unittest.TestCase):
    """权限与 frontmatter 双平台映射（§3.2 specs 各 Scenario）。"""

    def make_fm(self, edit_allow, bash_allow, tools=None):
        return {
            'name': 'demo',
            'description': '演示。',
            'model_role': 'architect',
            'tools': tools or ['read', 'write', 'edit', 'bash'],
            'permissions': {'edit_allow': edit_allow, 'bash_allow': bash_allow},
        }

    def test_edit_all_acceptedits_and_allow(self):
        """edit 全放开：CodeBuddy → acceptEdits；OpenCode → {"*": "allow"}。"""
        fm = self.make_fm(['*'], ['*'])
        rule = {'edit_all': 'acceptEdits', 'edit_restricted': 'plan'}
        self.assertEqual(build.compute_permission_mode(fm, rule, 'a.md'), 'acceptEdits')
        self.assertEqual(build.compute_permission_map(fm, 'a.md'),
                         {'edit': {'*': 'allow'}, 'bash': {'*': 'allow'}})

    def test_edit_missing_defaults_all(self):
        """edit_allow 缺省（无 permissions）同全放开处理。"""
        fm = self.make_fm(['*'], ['*'])
        del fm['permissions']
        rule = {'edit_all': 'acceptEdits', 'edit_restricted': 'plan'}
        self.assertEqual(build.compute_permission_mode(fm, rule, 'a.md'), 'acceptEdits')
        self.assertEqual(build.compute_permission_map(fm, 'a.md'),
                         {'edit': {'*': 'allow'}, 'bash': {'*': 'allow'}})

    def test_readonly_agent(self):
        """只读 agent：CodeBuddy → plan；OpenCode edit 仅 {"*": "deny"}。"""
        fm = self.make_fm([], ['git *'], tools=['read', 'bash'])
        rule = {'edit_all': 'acceptEdits', 'edit_restricted': 'plan'}
        self.assertEqual(build.compute_permission_mode(fm, rule, 'a.md'), 'plan')
        self.assertEqual(build.compute_permission_map(fm, 'a.md'),
                         {'edit': {'*': 'deny'}, 'bash': {'*': 'ask', 'git *': 'allow'}})

    def test_bash_denied_agent(self):
        """禁 bash agent：OpenCode bash 仅 {"*": "deny"}（不落入 ask 分支）。"""
        fm = self.make_fm([], [], tools=['read'])
        self.assertEqual(build.compute_permission_map(fm, 'a.md'),
                         {'edit': {'*': 'deny'}, 'bash': {'*': 'deny'}})

    def test_restricted_edit_agent(self):
        """受限编辑 agent：OpenCode edit 含 deny 基线 + 逐 glob allow。"""
        fm = self.make_fm(['openspec/**', 'docs/**'], ['git *', 'openspec *'])
        mapping = build.compute_permission_map(fm, 'a.md')
        self.assertEqual(mapping['edit'], {
            '*': 'deny', 'openspec/**': 'allow', 'docs/**': 'allow'})
        self.assertEqual(mapping['bash'], {
            '*': 'ask', 'git *': 'allow', 'openspec *': 'allow'})

    def test_rewrite_agent_codebuddy(self):
        """CodeBuddy 产物 frontmatter：tools PascalCase + model 烘焙。"""
        dsl = build.parse_yaml(
            (PLATFORM_YAML_DIR / 'codebuddy.yaml').read_text(encoding='utf-8'))
        fm = self.make_fm(['*'], ['*'])
        fm['max_turns'] = 80
        models = {'platforms': {'codebuddy': {'presets': {'balanced': {'architect': 'cb-arch'}}}}}
        output = build.rewrite_agent(fm, '\n正文。\n', dsl, 'codebuddy', models, 'a.md')
        self.assertTrue(output.startswith('---\n'))
        self.assertIn('name: demo\n', output)
        self.assertIn('model: cb-arch\n', output)
        self.assertIn('tools: [Read, Write, Edit, Bash]\n', output)
        self.assertIn('permissionMode: acceptEdits\n', output)
        self.assertIn('max_turns: 80\n', output)
        self.assertNotIn('model_role', output)
        self.assertNotIn('permissions', output)
        self.assertIn('正文。', output)

    def test_rewrite_agent_opencode(self):
        """OpenCode 产物 frontmatter：mode 字面量 + permission map + tools 省略。"""
        dsl = build.parse_yaml(
            (PLATFORM_YAML_DIR / 'opencode.yaml').read_text(encoding='utf-8'))
        fm = self.make_fm(['openspec/**'], ['git *'])
        models = {'platforms': {'opencode': {'presets': {'balanced': {'architect': 'prov/arch'}}}}}
        output = build.rewrite_agent(fm, '\n正文。\n', dsl, 'opencode', models, 'a.md')
        self.assertIn('mode: subagent\n', output)
        self.assertIn('model: prov/arch\n', output)
        self.assertIn('permission:\n  edit:\n    "*": "deny"\n    "openspec/**": "allow"\n', output)
        self.assertIn('  bash:\n    "*": "ask"\n    "git *": "allow"\n', output)
        self.assertNotIn('tools', output)
        self.assertNotIn('permissionMode', output)

    def test_rewrite_agent_no_max_turns_omitted(self):
        """max_turns 仅源存在时输出。"""
        dsl = build.parse_yaml(
            (PLATFORM_YAML_DIR / 'codebuddy.yaml').read_text(encoding='utf-8'))
        fm = self.make_fm(['*'], ['*'])
        models = {'platforms': {'codebuddy': {'presets': {'balanced': {'architect': 'cb-arch'}}}}}
        output = build.rewrite_agent(fm, '\n正文。\n', dsl, 'codebuddy', models, 'a.md')
        self.assertNotIn('max_turns', output)

    def test_rewrite_agent_model_missing_role_fails(self):
        """model_role 无 balanced 映射：构建失败。"""
        dsl = build.parse_yaml(
            (PLATFORM_YAML_DIR / 'codebuddy.yaml').read_text(encoding='utf-8'))
        fm = self.make_fm(['*'], ['*'])
        with self.assertRaises(build.BuildError):
            build.rewrite_agent(fm, '\n正文。\n', dsl, 'codebuddy', {}, 'a.md')

    def test_rewrite_command_codebuddy(self):
        """命令映射：CodeBuddy 三字段直出。"""
        dsl = build.parse_yaml(
            (PLATFORM_YAML_DIR / 'codebuddy.yaml').read_text(encoding='utf-8'))
        fm = {'name': 'Budget: Start', 'description': '启动。', 'argument-hint': '<描述>'}
        output = build.rewrite_command(fm, '\n正文。\n', dsl)
        self.assertIn('name: "Budget: Start"\n', output)
        self.assertIn('description: 启动。\n', output)
        self.assertIn('argument-hint: <描述>\n', output)

    def test_rewrite_command_opencode(self):
        """命令映射：OpenCode 仅 description（name/argument-hint 丢弃）。"""
        dsl = build.parse_yaml(
            (PLATFORM_YAML_DIR / 'opencode.yaml').read_text(encoding='utf-8'))
        fm = {'name': 'Budget: Start', 'description': '启动。', 'argument-hint': '<描述>'}
        output = build.rewrite_command(fm, '\n正文。\n', dsl)
        self.assertIn('description: 启动。\n', output)
        self.assertNotIn('name', output)
        self.assertNotIn('argument-hint', output)


class VariableReplacementTests(unittest.TestCase):
    """正文模板变量白名单替换（§3.3 specs Scenario）。"""

    def test_known_variables_replaced(self):
        text = '使用 {{TASK_TOOL}} 工具，前缀 {{SKILL_NS}}。'
        result = build.replace_variables(
            text, {'TASK_TOOL': 'Agent', 'SKILL_NS': 'superpowers:'}, 'a.md')
        self.assertEqual(result, '使用 Agent 工具，前缀 superpowers:。')

    def test_unknown_variable_kept_with_warning(self):
        text = '未知 {{UNKNOWN_VAR}} 变量。'
        result = build.replace_variables(text, {'TASK_TOOL': 'Agent'}, 'a.md')
        self.assertEqual(result, text)

    def test_empty_value_replaces(self):
        """空字符串取值（SKILL_NS: ""）替换后消失。"""
        text = '前缀{{SKILL_NS}}技能。'
        result = build.replace_variables(text, {'SKILL_NS': ''}, 'a.md')
        self.assertEqual(result, '前缀技能。')

    def test_non_variable_braces_untouched(self):
        """非 {{VAR}} 形态的花括号不受影响。"""
        text = '{single} 与 {{{not_var}}} 与 {{1abc}}'
        result = build.replace_variables(text, {'TASK_TOOL': 'Agent'}, 'a.md')
        self.assertEqual(result, text)


class ModelsValidationTests(unittest.TestCase):
    """budget-models.json 构建期结构校验（§7，T8a）。"""

    def test_valid_data_passes(self):
        """完整合法数据通过校验（make_models_json 基准）。"""
        data = make_models_json()
        self.assertIs(build.validate_models_data(data, 'm.json'), data)

    def test_real_models_json_valid(self):
        """真实 core/models/budget-models.json 通过构建期结构校验。"""
        data = json.loads(REAL_MODELS_JSON.read_text(encoding='utf-8'))
        build.validate_models_data(data, str(REAL_MODELS_JSON))

    def test_missing_top_key_fails(self):
        """缺顶层键（如 roles）→ BuildError 指出缺失键（spec Scenario 结构校验）。"""
        data = make_models_json()
        del data['roles']
        with self.assertRaises(build.BuildError) as ctx:
            build.validate_models_data(data, 'm.json')
        self.assertIn('roles', str(ctx.exception))

    def test_roles_mismatch_fails(self):
        """roles 与十角色集合不一致 → BuildError。"""
        data = make_models_json()
        data['roles'] = data['roles'][:9]
        with self.assertRaises(build.BuildError) as ctx:
            build.validate_models_data(data, 'm.json')
        self.assertIn('roles', str(ctx.exception))

    def test_missing_meta_field_fails(self):
        """_meta 缺 update_command → BuildError。"""
        data = make_models_json()
        del data['_meta']['update_command']
        with self.assertRaises(build.BuildError) as ctx:
            build.validate_models_data(data, 'm.json')
        self.assertIn('update_command', str(ctx.exception))

    def test_preset_missing_role_fails(self):
        """预设档缺角色键 → BuildError（spec Scenario 双平台预设齐全）。"""
        data = make_models_json()
        del data['platforms']['codebuddy']['presets']['balanced']['architect']
        with self.assertRaises(build.BuildError) as ctx:
            build.validate_models_data(data, 'm.json')
        self.assertIn('十角色键', str(ctx.exception))

    def test_preset_missing_tier_fails(self):
        """缺某档预设 → BuildError。"""
        data = make_models_json()
        del data['platforms']['opencode']['presets']['quality']
        with self.assertRaises(build.BuildError) as ctx:
            build.validate_models_data(data, 'm.json')
        self.assertIn('quality', str(ctx.exception))

    def test_codebuddy_preset_id_not_in_catalog_fails(self):
        """codebuddy 预设值不在目录 → BuildError（值为该平台合法模型 ID）。"""
        data = make_models_json()
        data['platforms']['codebuddy']['presets']['balanced']['architect'] = 'ghost-model'
        with self.assertRaises(build.BuildError) as ctx:
            build.validate_models_data(data, 'm.json')
        self.assertIn('不在模型目录', str(ctx.exception))

    def test_codebuddy_preset_platform_mismatch_fails(self):
        """codebuddy 预设值的 platform 不含 codebuddy → BuildError。"""
        data = make_models_json()
        data['models']['paid']['demo'][0]['platform'] = ['opencode']
        with self.assertRaises(build.BuildError) as ctx:
            build.validate_models_data(data, 'm.json')
        self.assertIn('不含 codebuddy', str(ctx.exception))

    def test_opencode_preset_bad_format_fails(self):
        """opencode 预设值非 provider/model 格式 → BuildError。"""
        data = make_models_json()
        data['platforms']['opencode']['presets']['balanced']['architect'] = 'no-slash'
        with self.assertRaises(build.BuildError) as ctx:
            build.validate_models_data(data, 'm.json')
        self.assertIn('provider/model', str(ctx.exception))

    def test_opencode_preset_bad_provider_fails(self):
        """opencode 预设 provider 不在白名单 → BuildError。"""
        data = make_models_json()
        data['platforms']['opencode']['presets']['balanced']['architect'] = (
            'ghostprov/cb-architect')
        with self.assertRaises(build.BuildError) as ctx:
            build.validate_models_data(data, 'm.json')
        self.assertIn('provider', str(ctx.exception))

    def test_opencode_preset_model_not_in_catalog_fails(self):
        """opencode 预设 model 部分不在目录 → BuildError。"""
        data = make_models_json()
        data['platforms']['opencode']['presets']['balanced']['architect'] = (
            'deepseek/ghost-model')
        with self.assertRaises(build.BuildError) as ctx:
            build.validate_models_data(data, 'm.json')
        self.assertIn('不在模型目录', str(ctx.exception))

    def test_duplicate_model_id_fails(self):
        """目录模型 ID 重复 → BuildError（含首见位置定位）。"""
        data = make_models_json()
        data['models']['paid']['demo'].append(dict(data['models']['paid']['demo'][0]))
        with self.assertRaises(build.BuildError) as ctx:
            build.validate_models_data(data, 'm.json')
        self.assertIn('重复', str(ctx.exception))

    def test_bad_cost_fails(self):
        """cost 非 x0.05 形态 → BuildError。"""
        data = make_models_json()
        data['models']['paid']['demo'][0]['cost'] = '0.05'
        with self.assertRaises(build.BuildError) as ctx:
            build.validate_models_data(data, 'm.json')
        self.assertIn('cost', str(ctx.exception))

    def test_bad_tier_fails(self):
        """tier 非法枚举 → BuildError。"""
        data = make_models_json()
        data['models']['paid']['demo'][0]['tier'] = 'premium'
        with self.assertRaises(build.BuildError) as ctx:
            build.validate_models_data(data, 'm.json')
        self.assertIn('tier', str(ctx.exception))

    def test_bad_platform_enum_fails(self):
        """条目 platform 含非法枚举（cli）→ BuildError。"""
        data = make_models_json()
        data['models']['paid']['demo'][0]['platform'] = ['cli', 'codebuddy']
        with self.assertRaises(build.BuildError) as ctx:
            build.validate_models_data(data, 'm.json')
        self.assertIn('platform', str(ctx.exception))

    def test_missing_models_section_fails(self):
        """models 缺 free 分组 → BuildError。"""
        data = make_models_json()
        del data['models']['free']
        with self.assertRaises(build.BuildError) as ctx:
            build.validate_models_data(data, 'm.json')
        self.assertIn('free', str(ctx.exception))

    def test_bad_unconfirmed_ids_fails(self):
        """_meta.unconfirmed_opencode_ids 非字符串数组 → BuildError。"""
        data = make_models_json()
        data['_meta']['unconfirmed_opencode_ids'] = 'anthropic/claude-opus-4.7'
        with self.assertRaises(build.BuildError) as ctx:
            build.validate_models_data(data, 'm.json')
        self.assertIn('unconfirmed_opencode_ids', str(ctx.exception))

    def test_provider_map_missing_fails(self):
        """provider_map 整体缺失 → BuildError（本项目数据必含，T10a 解析依赖）。"""
        data = make_models_json()
        del data['provider_map']
        with self.assertRaises(build.BuildError) as ctx:
            build.validate_models_data(data, 'm.json')
        self.assertIn('provider_map', str(ctx.exception))

    def test_provider_map_missing_group_fails(self):
        """provider_map 缺厂商组（free 侧新组未映射）→ BuildError。"""
        data = make_models_json()
        data['models']['free']['gift'] = [{
            'id': 'cb-gift', 'tier': 'free', 'cost': 'x0.00',
            'tags': ['general'], 'platform': ['codebuddy', 'opencode'],
        }]
        with self.assertRaises(build.BuildError) as ctx:
            build.validate_models_data(data, 'm.json')
        self.assertIn('gift', str(ctx.exception))

    def test_provider_map_complete_passes(self):
        """provider_map 覆盖 paid/free 全部组名 → 校验通过。"""
        data = make_models_json()
        data['models']['free']['gift'] = [{
            'id': 'cb-gift', 'tier': 'free', 'cost': 'x0.00',
            'tags': ['general'], 'platform': ['codebuddy', 'opencode'],
        }]
        data['provider_map']['gift'] = 'opencode'
        self.assertIs(build.validate_models_data(data, 'm.json'), data)

    def test_provider_map_bad_value_fails(self):
        """provider_map 值非非空字符串 → BuildError。"""
        data = make_models_json()
        data['provider_map']['demo'] = ''
        with self.assertRaises(build.BuildError) as ctx:
            build.validate_models_data(data, 'm.json')
        self.assertIn('provider_map.demo', str(ctx.exception))

    def test_invalid_models_json_fails_build(self):
        """管线级：结构非法的 budget-models.json → 构建失败（exit 1）。"""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        core = root / 'core'
        for name in ('codebuddy.yaml', 'opencode.yaml'):
            dest = core / 'platform' / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(PLATFORM_YAML_DIR / name, dest)
        data = make_models_json()
        del data['roles']
        (core / 'models').mkdir(parents=True, exist_ok=True)
        (core / 'models' / 'budget-models.json').write_text(
            json.dumps(data), encoding='utf-8')
        proc = run_build(root)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('roles', proc.stderr)


class ModelSelectionRenderTests(unittest.TestCase):
    """MODEL_SELECTION 渲染管线（A6/T8a）：三占位符、白名单独立、确定性。"""

    TEMPLATE = '# 模型选择\n\n{{models_table}}\n\n{{preset_table}}\n\n{{platform_note}}\n'

    def test_render_replaces_all_placeholders(self):
        """三占位符全部替换，输出无 {{ 残留（双平台）。"""
        data = make_models_json()
        for platform in ('codebuddy', 'opencode'):
            result = build.render_model_selection(
                self.TEMPLATE, data, platform, 'docs/MODEL_SELECTION.md')
            self.assertNotIn('{{', result)
            self.assertIn('| 厂商 |', result)
            self.assertIn('cb-architect', result)
            self.assertIn('| 角色 |', result)
            self.assertIn('deepseek/cb-architect', result)

    def test_render_unknown_placeholder_kept(self):
        """未知占位符保留原样（白名单独立于 §3.3 六变量，未知名不替换）。"""
        template = '{{models_table}}\n{{unknown_block}}\n{{TASK_TOOL}}\n'
        data = make_models_json()
        result = build.render_model_selection(template, data, 'codebuddy', 'd.md')
        self.assertNotIn('{{models_table}}', result)
        self.assertIn('{{unknown_block}}', result)
        self.assertIn('{{TASK_TOOL}}', result)

    def test_render_platform_note_differs_by_platform(self):
        """platform_note 按平台生成（codebuddy/opencode 内容不同）。"""
        data = make_models_json()
        cb = build.render_model_selection('{{platform_note}}\n', data, 'codebuddy', 'd.md')
        oc = build.render_model_selection('{{platform_note}}\n', data, 'opencode', 'd.md')
        self.assertIn('CodeBuddy 原生模型 ID', cb)
        self.assertIn('provider/model', oc)
        self.assertNotEqual(cb, oc)

    def test_render_opencode_unconfirmed_listed(self):
        """opencode 平台说明列出待确认 ID（数据驱动，spec Scenario 待确认标注）。"""
        data = make_models_json()
        data['_meta']['unconfirmed_opencode_ids'] = ['anthropic/claude-opus-4.7']
        result = build.render_model_selection('{{platform_note}}\n', data, 'opencode', 'd.md')
        self.assertIn('anthropic/claude-opus-4.7', result)
        self.assertIn('待确认', result)

    def test_render_codebuddy_note_no_unconfirmed(self):
        """codebuddy 平台说明不含待确认清单。"""
        data = make_models_json()
        data['_meta']['unconfirmed_opencode_ids'] = ['anthropic/claude-opus-4.7']
        result = build.render_model_selection('{{platform_note}}\n', data, 'codebuddy', 'd.md')
        self.assertNotIn('待确认', result)

    def test_render_deterministic(self):
        """确定性：同一数据两次渲染逐字节一致。"""
        data = make_models_json()
        first = build.render_model_selection(self.TEMPLATE, data, 'codebuddy', 'd.md')
        second = build.render_model_selection(self.TEMPLATE, data, 'codebuddy', 'd.md')
        self.assertEqual(first, second)

    def test_render_models_table_vendor_order(self):
        """厂商组固定顺序：_VENDOR_ORDER 内按序，其余按字母序追加。"""
        data = make_models_json()
        data['models']['paid']['zeta'] = [{
            'id': 'z-1', 'tier': 'mid', 'cost': 'x1.00',
            'tags': ['g'], 'platform': ['codebuddy']}]
        table = build._render_models_table(data)  # pylint: disable=protected-access
        self.assertLess(table.index('| demo |'), table.index('| zeta |'))

    def test_render_preset_table_role_order(self):
        """预设表角色按 roles 序输出（与数据 roles 一致）。"""
        data = make_models_json()
        table = build._render_preset_table(data)  # pylint: disable=protected-access
        lines = [line for line in table.splitlines() if line.startswith('| architect |')]
        self.assertEqual(len(lines), 1)
        first_role_line = next(
            line for line in table.splitlines()
            if line.startswith(f'| {data["roles"][0]} |'))
        self.assertIn('cb-architect', first_role_line)

    def test_render_models_table_escapes_pipe(self):
        """note 含管道符时转义，避免破坏表格列。"""
        data = make_models_json()
        data['models']['paid']['demo'][0]['note'] = 'a|b'
        table = build._render_models_table(data)  # pylint: disable=protected-access
        self.assertIn('a\\|b', table)


class BuildPipelineTests(unittest.TestCase):
    """构建流程：原子性、幂等、降级、路由落位（specs/build-pipeline 各 Scenario）。"""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.core = self.root / 'core'
        # 复制真实 platform yaml 到临时仓库。
        for name in ('codebuddy.yaml', 'opencode.yaml'):
            dest = self.core / 'platform' / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(PLATFORM_YAML_DIR / name, dest)
        # 骨架目录（空 core 场景）。
        for category in ('agents', 'skills', 'commands', 'rules',
                         'models', 'personas', 'lib', 'docs', 'hooks'):
            (self.core / category).mkdir(parents=True, exist_ok=True)

    def write_file(self, relpath, text):
        target = self.root / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8')

    # ----- ⑧ 空 core 冒烟（specs Scenario「空 core 冒烟」） -----

    def test_empty_core_smoke_exit_zero(self):
        """⑧ 空 core 冒烟：exit 0，双平台产物与 manifest 生成，无完备性失败。"""
        proc = run_build(self.root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for platform in ('codebuddy', 'opencode'):
            manifest_path = self.root / 'dist' / platform / '.manifest.json'
            self.assertTrue(manifest_path.is_file(), platform)
            data = json.loads(manifest_path.read_text(encoding='utf-8'))
            self.assertIsInstance(data['files'], dict)

    # ----- ⑥ 两次构建 manifest diff 为空（specs Scenario「重复构建幂等」） -----

    def test_repeated_build_manifest_diff_empty(self):
        """⑥ 幂等：两次构建 manifest 完全一致；产物逐字节一致。"""
        write_agents(self.root)
        proc = run_build(self.root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        snapshot_first = snapshot_tree(self.root / 'dist')
        manifest_first = (self.root / 'dist' / 'codebuddy' / '.manifest.json').read_text(
            encoding='utf-8')
        manifest_first_oc = (self.root / 'dist' / 'opencode' / '.manifest.json').read_text(
            encoding='utf-8')
        proc = run_build(self.root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        snapshot_second = snapshot_tree(self.root / 'dist')
        self.assertEqual(snapshot_first, snapshot_second)
        self.assertEqual(
            manifest_first,
            (self.root / 'dist' / 'codebuddy' / '.manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(
            manifest_first_oc,
            (self.root / 'dist' / 'opencode' / '.manifest.json').read_text(encoding='utf-8'))

    # ----- ⑦ 校验失败保持原样（specs Scenario「校验失败保持原样」） -----

    def test_validation_failure_keeps_dist_intact(self):
        """⑦ 原子性：校验失败 exit 非零，dist 保持构建前原样，无 .new/.old 残留。"""
        write_agents(self.root)
        proc = run_build(self.root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        before = snapshot_tree(self.root / 'dist')
        # 注入违规 agent（name 与文件主名不一致）。
        self.write_file('core/agents/broken.md', make_agent_md(AGENT_TABLE[0]).replace(
            'name: architect', 'name: mismatch', 1))
        proc = run_build(self.root)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('不一致', proc.stderr)
        after = snapshot_tree(self.root / 'dist')
        self.assertEqual(before, after)
        self.assertFalse((self.root / 'dist' / 'codebuddy.new').exists())
        self.assertFalse((self.root / 'dist' / 'codebuddy.old').exists())
        self.assertFalse((self.root / 'dist' / 'opencode.new').exists())
        self.assertFalse((self.root / 'dist' / 'opencode.old').exists())

    def test_dsl_failure_on_first_build_no_dist(self):
        """首建即校验失败：dist 不产生半成品目录。"""
        dsl_text = (PLATFORM_YAML_DIR / 'codebuddy.yaml').read_text(encoding='utf-8')
        # 缺 routing 键：删除 routing.agent 行。
        broken = '\n'.join(
            line for line in dsl_text.splitlines() if 'agent:   ' not in line)
        self.write_file('core/platform/codebuddy.yaml', broken + '\n')
        proc = run_build(self.root)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('routing', proc.stderr)
        self.assertFalse((self.root / 'dist' / 'codebuddy').exists())

    # ----- ⑨ models 缺失烘焙降级（specs Scenario「models 缺失烘焙降级」） -----

    def test_agents_without_models_no_model_field(self):
        """⑨ agents 存在但 models 缺失：产物无 model 字段，告警，exit 0。"""
        write_agents(self.root)
        proc = run_build(self.root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('budget-models.json 缺失', proc.stderr)
        cb_agent = self.root / 'dist' / 'codebuddy' / 'agents' / 'architect.md'
        oc_agent = self.root / 'dist' / 'opencode' / 'agent' / 'architect.md'
        self.assertTrue(cb_agent.is_file())
        self.assertTrue(oc_agent.is_file())
        cb_text = cb_agent.read_text(encoding='utf-8')
        oc_text = oc_agent.read_text(encoding='utf-8')
        self.assertNotIn('model:', cb_text)
        self.assertNotIn('model:', oc_text)
        # MODEL_SELECTION 不产出（模板渲染跳过）。

    # ----- 全量数据就位场景 -----

    def test_full_data_build_and_routing(self):
        """全量数据：双平台路由落位、变量替换、manifest 覆盖全部产物。"""
        write_agents(self.root)
        write_full_models(self.root)
        # 命令。
        self.write_file('core/commands/budget/start.md',
                        '---\nname: "Budget: Start"\ndescription: 启动工作流。\n'
                        'argument-hint: "<需求描述>"\n---\n使用 {{TASK_TOOL}} 启动。\n')
        self.write_file('core/commands/opsx/apply.md',
                        '---\nname: "Opsx: Apply"\ndescription: 应用变更。\n---\n正文。\n')
        # skill。
        self.write_file('core/skills/budget-workflow/SKILL.md',
                        '# 工作流\n\n调用 {{TASK_TOOL}} 与 {{SKILL_NS}}\n')
        # rules。
        self.write_file('core/rules/budget-leader-no-code.md', 'P0：编排者不直接写代码。\n')
        self.write_file('core/rules/budget-coder-guard.md', 'P0：护栏约束。\n')
        # lib 与 personas 与 docs。
        self.write_file('core/lib/utils.sh', 'echo utils\n')
        (self.core / 'personas' / 'personas.json').write_text(
            json.dumps({'_meta': {}, 'themes': {}}), encoding='utf-8')
        self.write_file('core/docs/PERSONAS.md', '# Personas 说明\n')
        # hooks（仅 codebuddy 分发）。
        self.write_file('core/hooks/budget-notify-hook.py', '#!/usr/bin/env python3\n')

        proc = run_build(self.root)
        self.assertEqual(proc.returncode, 0, proc.stderr)

        # CodeBuddy 落位。
        cb = self.root / 'dist' / 'codebuddy'
        self.assertTrue((cb / 'agents' / 'architect.md').is_file())
        self.assertTrue((cb / 'commands' / 'budget' / 'start.md').is_file())
        self.assertTrue((cb / 'commands' / 'opsx' / 'apply.md').is_file())
        self.assertTrue((cb / 'skills' / 'budget-workflow' / 'SKILL.md').is_file())
        self.assertTrue((cb / 'rules' / 'budget-leader-no-code.mdc').is_file())
        self.assertTrue((cb / 'lib' / 'utils.sh').is_file())
        self.assertTrue((cb / 'personas.json').is_file())
        self.assertTrue((cb / 'docs' / 'PERSONAS.md').is_file())
        self.assertTrue((cb / 'hooks' / 'budget-notify-hook.py').is_file())
        self.assertTrue((cb / 'budget-models.json').is_file())

        # OpenCode 落位。
        oc = self.root / 'dist' / 'opencode'
        self.assertTrue((oc / 'agent' / 'architect.md').is_file())
        self.assertTrue((oc / 'command' / 'budget-start.md').is_file())
        self.assertTrue((oc / 'command' / 'opsx-apply.md').is_file())
        self.assertTrue((oc / 'skill' / 'budget-workflow' / 'SKILL.md').is_file())
        self.assertTrue((oc / 'AGENTS.fragment.md').is_file())
        self.assertFalse((oc / 'hook').exists())
        fragment = (oc / 'AGENTS.fragment.md').read_text(encoding='utf-8')
        self.assertIn('<!-- BudgetBuddy:begin -->', fragment)
        self.assertIn('<!-- BudgetBuddy:end -->', fragment)
        self.assertIn('budget-leader-no-code:begin', fragment)
        self.assertIn('budget-coder-guard:begin', fragment)

        # 变量替换与模型烘焙。
        cb_arch = (cb / 'agents' / 'architect.md').read_text(encoding='utf-8')
        self.assertIn('model: cb-architect\n', cb_arch)
        self.assertIn('permissionMode: plan\n', cb_arch)
        self.assertNotIn('{{TASK_TOOL}}', cb_arch)
        oc_arch = (oc / 'agent' / 'architect.md').read_text(encoding='utf-8')
        self.assertIn('model: deepseek/cb-architect\n', oc_arch)
        self.assertNotIn('{{TASK_TOOL}}', oc_arch)
        cb_skill = (cb / 'skills' / 'budget-workflow' / 'SKILL.md').read_text(encoding='utf-8')
        self.assertIn('调用 Agent 与 superpowers:', cb_skill)
        oc_skill = (oc / 'skill' / 'budget-workflow' / 'SKILL.md').read_text(encoding='utf-8')
        self.assertIn('调用 task 与', oc_skill)
        self.assertNotIn('{{SKILL_NS}}', oc_skill)

        # 命令 frontmatter 映射。
        cb_cmd = (cb / 'commands' / 'budget' / 'start.md').read_text(encoding='utf-8')
        self.assertIn('name: "Budget: Start"', cb_cmd)
        oc_cmd = (oc / 'command' / 'budget-start.md').read_text(encoding='utf-8')
        self.assertNotIn('name:', oc_cmd)
        self.assertNotIn('argument-hint', oc_cmd)

        # manifest 覆盖全部产物（除自身）。
        for platform in ('codebuddy', 'opencode'):
            dist_dir = self.root / 'dist' / platform
            manifest = json.loads(
                (dist_dir / '.manifest.json').read_text(encoding='utf-8'))
            listed = set(manifest['files'])
            on_disk = {p.relative_to(dist_dir).as_posix()
                       for p in dist_dir.rglob('*') if p.is_file()} - {'.manifest.json'}
            self.assertEqual(listed, on_disk, platform)
            for rel, digest in manifest['files'].items():
                actual = hashlib.sha256((dist_dir / rel).read_bytes()).hexdigest()
                self.assertEqual(actual, digest, rel)

    def test_pycache_pyc_dsstore_excluded_from_dist_and_manifest(self):
        """P2-2 __pycache__/.pyc/.DS_Store 不入 dist 与 manifest（§12-A8）。"""
        write_agents(self.root)
        pycache = self.core / 'lib' / '__pycache__'
        pycache.mkdir(parents=True, exist_ok=True)
        (pycache / 'utils.cpython-312.pyc').write_bytes(b'\x00pyc')
        (self.core / 'lib' / 'stale.pyc').write_bytes(b'\x00stale')
        (self.core / 'lib' / '.DS_Store').write_bytes(b'\x00ds')
        self.write_file('core/lib/utils.sh', 'echo utils\n')
        proc = run_build(self.root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for platform in ('codebuddy', 'opencode'):
            dist_dir = self.root / 'dist' / platform
            self.assertFalse((dist_dir / 'lib' / '__pycache__').exists(), platform)
            self.assertFalse((dist_dir / 'lib' / 'stale.pyc').exists(), platform)
            self.assertFalse((dist_dir / 'lib' / '.DS_Store').exists(), platform)
            self.assertTrue((dist_dir / 'lib' / 'utils.sh').is_file(), platform)
            manifest = json.loads(
                (dist_dir / '.manifest.json').read_text(encoding='utf-8'))
            self.assertIn('lib/utils.sh', manifest['files'], platform)
            for noise in ('lib/__pycache__/utils.cpython-312.pyc',
                          'lib/stale.pyc', 'lib/.DS_Store'):
                self.assertNotIn(noise, manifest['files'], platform)

    def test_platform_selective_build(self):
        """--platform opencode：仅重建 opencode，codebuddy 保持不变。"""
        write_agents(self.root)
        proc = run_build(self.root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        cb_before = snapshot_tree(self.root / 'dist' / 'codebuddy')
        self.write_file('core/agents/extra_marker.md', '')
        (self.root / 'core' / 'agents' / 'extra_marker.md').unlink()  # 无副作用占位
        proc = run_build(self.root, '--platform', 'opencode')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        cb_after = snapshot_tree(self.root / 'dist' / 'codebuddy')
        self.assertEqual(cb_before, cb_after)

    def test_docs_null_not_distributed(self):
        """routing.docs null 条目：该平台不产出对应文件。"""
        self.write_file('core/docs/opencode-setup-notes.md', '# OpenCode 说明\n')
        self.write_file('core/docs/PERSONAS.md', '# Personas\n')
        proc = run_build(self.root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse((self.root / 'dist' / 'codebuddy' / 'docs' / 'opencode-setup-notes.md').exists())
        self.assertTrue((self.root / 'dist' / 'codebuddy' / 'docs' / 'PERSONAS.md').is_file())
        self.assertTrue((self.root / 'dist' / 'opencode' / 'docs' / 'setup-notes.md').is_file())

    def test_docs_undeclared_file_fails(self):
        """core/docs 文件未在 routing.docs 声明：构建失败（无文件名特判）。"""
        self.write_file('core/docs/unknown.md', '# 未声明\n')
        proc = run_build(self.root)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('routing.docs', proc.stderr)

    def test_template_doc_render_hook_skipped_without_models(self):
        """模板 docs 在数据缺失时降级跳过（D §4；渲染管线已实现，数据缺失仍跳过）。"""
        self.write_file('core/docs/MODEL_SELECTION.template.md',
                        '# 模型选择\n\n{{models_table}}\n')
        proc = run_build(self.root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('渲染跳过', proc.stderr)
        self.assertIn('budget-models.json 缺失', proc.stderr)
        self.assertFalse(
            (self.root / 'dist' / 'codebuddy' / 'docs' / 'MODEL_SELECTION.md').exists())

    # ----- T8a：MODEL_SELECTION 渲染与 model 烘焙端到端 -----

    def test_model_selection_rendered_when_models_present(self):
        """T8a：models + 模板就位 → 双平台 MODEL_SELECTION.md 渲染产出，无 {{ 残留。"""
        write_agents(self.root)
        write_full_models(self.root)
        self.write_file(
            'core/docs/MODEL_SELECTION.template.md',
            '# 模型选择\n\n{{models_table}}\n\n{{preset_table}}\n\n{{platform_note}}\n')
        proc = run_build(self.root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for platform, agent_dir in (('codebuddy', 'docs'), ('opencode', 'docs')):
            doc = self.root / 'dist' / platform / agent_dir / 'MODEL_SELECTION.md'
            self.assertTrue(doc.is_file(), platform)
            text = doc.read_text(encoding='utf-8')
            self.assertNotIn('{{', text)
            self.assertIn('| 厂商 |', text)
            self.assertIn('| 角色 |', text)
        # 模板本身不平移进产物（§3.5）。
        for platform in ('codebuddy', 'opencode'):
            self.assertFalse(
                (self.root / 'dist' / platform / 'docs' / 'MODEL_SELECTION.template.md').exists())
        # models 缺失降级告警不再出现（T1a 起的告警在本任务后消失）。
        self.assertNotIn('budget-models.json 缺失', proc.stderr)

    def test_baked_model_values_in_balanced_preset(self):
        """T8a 烘焙验证：agent 产物 model 字段非空且值 = balanced 预设对应 ID（双平台）。"""
        write_agents(self.root)
        write_full_models(self.root)
        proc = run_build(self.root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        models = make_models_json()
        for row in AGENT_TABLE:
            name, role = row[0], row[1]
            cb_text = (self.root / 'dist' / 'codebuddy' / 'agents' / f'{name}.md').read_text(
                encoding='utf-8')
            oc_text = (self.root / 'dist' / 'opencode' / 'agent' / f'{name}.md').read_text(
                encoding='utf-8')
            cb_expected = models['platforms']['codebuddy']['presets']['balanced'][role]
            oc_expected = models['platforms']['opencode']['presets']['balanced'][role]
            self.assertIn(f'model: {cb_expected}\n', cb_text, name)
            self.assertIn(f'model: {oc_expected}\n', oc_text, name)
            # 烘焙值 ∈ 预设表（三档值集）。
            cb_all = {models['platforms']['codebuddy']['presets'][p][role] for p in
                      ('economic', 'balanced', 'quality')}
            oc_all = {models['platforms']['opencode']['presets'][p][role] for p in
                      ('economic', 'balanced', 'quality')}
            self.assertIn(cb_expected, cb_all)
            self.assertIn(oc_expected, oc_all)

    def test_strict_p0_warning_fails(self):
        """--strict：P0 一致性告警升级为失败。"""
        write_agents(self.root)
        # 构造不一致：rules 三个 P0 条目 + SKILL 内联章节条目不同。
        self.write_file('core/rules/budget-leader-no-code.md', 'P0 规则一：编排者不直接写代码。\n')
        self.write_file('core/rules/budget-coder-guard.md', 'P0 规则二：护栏约束执行。\n')
        self.write_file('core/rules/budget-workflow-enforcement.md', 'P0 规则三：流程强制执行。\n')
        self.write_file(
            'core/skills/budget-workflow/SKILL.md',
            '# 工作流\n\n## 强制执行规则（P0）\n\n'
            '- 完全不相关的甲乙丙丁条目内容差异极大\n'
            '- 另一条毫不相干的描述文字戊己庚辛\n'
            '- 第三条同样毫无交集的说明壬癸子丑\n')

        proc = run_build(self.root)
        self.assertEqual(proc.returncode, 0)
        self.assertIn('P0 一致性', proc.stderr)

        proc = run_build(self.root, '--strict')
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('--strict', proc.stderr)

    def test_strict_p0_consistent_passes(self):
        """--strict 且 P0 一致：构建通过（关键词双向包含率达标）。"""
        write_agents(self.root)
        entries = [
            'P0 规则一：编排者不直接写代码，所有代码修改经分级 coder 执行。',
            'P0 规则二：护栏约束执行，连续失败达到阈值后降级派发。',
            'P0 规则三：流程强制执行，阶段闸门未通过不得进入下一阶段。',
        ]
        for stem, entry in zip(build.P0_RULE_STEMS, entries):
            self.write_file(f'core/rules/{stem}.md', entry + '\n')
        skill_text = '# 工作流\n\n## 强制执行规则（P0）\n\n'
        for entry in entries:
            skill_text += f'- {entry}\n'
        self.write_file('core/skills/budget-workflow/SKILL.md', skill_text)
        proc = run_build(self.root, '--strict')
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_check_invokes_brand_scan(self):
        """--check：门禁扫描接入（构造违禁词样本 → exit 1）。"""
        write_agents(self.root)
        # agents 正文注入违禁词（core 在扫描范围内）。
        target = self.root / 'core' / 'agents' / 'architect.md'
        text = target.read_text(encoding='utf-8')
        target.write_text(text + '\n提及 ' + SAMPLE_FORBIDDEN + ' 一词。\n', encoding='utf-8')
        proc = run_build(self.root, '--check')
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('scan-brand', proc.stdout + proc.stderr)

    def test_setup_missing_warns(self):
        """P3-7 setup.sh 缺失：告警跳过（与 models/personas 降级告警风格一致）。"""
        proc = run_build(self.root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('core/setup.sh 缺失', proc.stderr)

    def test_agent_error_uses_repo_relative_path(self):
        """P3-8 agent 校验报错用仓库相对路径（core/agents/x.md 形态）。"""
        write_agents(self.root)
        self.write_file('core/agents/broken.md', make_agent_md(AGENT_TABLE[0]).replace(
            'name: architect', 'name: mismatch', 1))
        proc = run_build(self.root)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('core/agents/broken.md', proc.stderr)


class P0ConsistencyUnitTests(unittest.TestCase):
    """P0 一致性 diff 单元测试（§3.4 可执行判定规则）。"""

    def test_normalize_and_keywords(self):
        entry = '  `Leader` **不得** 写代码  \n'
        normalized = build._normalize_entry(entry)  # pylint: disable=protected-access
        self.assertEqual(normalized, 'leader 不得 写代码')
        keywords = build._entry_keywords('leader 不得 写代码')  # pylint: disable=protected-access
        self.assertEqual(keywords, {'leader', '不得', '写代码'})

    def test_missing_data_returns_empty(self):
        """数据未就位（rules/SKILL 缺失）返回空（降级跳过）。"""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        core_dir = Path(tmp.name) / 'core'
        core_dir.mkdir(parents=True)
        self.assertEqual(build.check_p0_consistency(core_dir), [])

    def test_consistent_entries_no_warning(self):
        """一致条目：无告警。"""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        core_dir = Path(tmp.name) / 'core'
        rules_dir = core_dir / 'rules'
        skill_dir = core_dir / 'skills' / 'budget-workflow'
        rules_dir.mkdir(parents=True)
        skill_dir.mkdir(parents=True)
        entries = ['编排者不直接写代码，修改经 coder 执行。', '护栏约束，失败降级。']
        for stem, entry in zip(build.P0_RULE_STEMS[:2], entries):
            (rules_dir / f'{stem}.md').write_text(entry + '\n', encoding='utf-8')
        skill_text = '# 工作流\n\n## 强制执行规则（P0）\n\n'
        for entry in entries:
            skill_text += f'- {entry}\n'
        (skill_dir / 'SKILL.md').write_text(skill_text, encoding='utf-8')
        self.assertEqual(build.check_p0_consistency(core_dir), [])

    def test_inconsistent_count_warns(self):
        """条目数不一致：产出告警。"""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        core_dir = Path(tmp.name) / 'core'
        rules_dir = core_dir / 'rules'
        skill_dir = core_dir / 'skills' / 'budget-workflow'
        rules_dir.mkdir(parents=True)
        skill_dir.mkdir(parents=True)
        for stem in build.P0_RULE_STEMS:
            (rules_dir / f'{stem}.md').write_text('规则。\n', encoding='utf-8')
        (skill_dir / 'SKILL.md').write_text(
            '# 工作流\n\n## 强制执行规则（P0）\n\n- 唯一条目\n', encoding='utf-8')
        warnings = build.check_p0_consistency(core_dir)
        self.assertEqual(len(warnings), 1)
        self.assertIn('条目数不一致', warnings[0])


class ManifestUnitTests(unittest.TestCase):
    """manifest 单元行为（§12-A7）。"""

    def test_manifest_sorted_and_no_timestamp(self):
        """manifest 键排序、无时间戳、不含自身。"""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        dist_dir = Path(tmp.name)
        for name in ('b.md', 'a.md', 'sub/c.md'):
            target = dist_dir / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('x\n', encoding='utf-8')
        manifest = build.gen_manifest(dist_dir)
        self.assertEqual(list(manifest['files']), ['a.md', 'b.md', 'sub/c.md'])
        self.assertNotIn('.manifest.json', manifest['files'])
        self.assertEqual(
            set(manifest), {'files'}, 'manifest 不得包含时间戳等其他顶层键')
        text = json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False)
        self.assertNotIn('time', text.lower())

    def test_atomic_replace_restores_on_failure(self):
        """原子替换失败路径：旧目录恢复（.new rename 失败时兜底）。"""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        final_dir = base / 'final'
        new_dir = base / 'final.new'
        old_dir = base / 'final.old'
        final_dir.mkdir()
        (final_dir / 'old.txt').write_text('old\n', encoding='utf-8')
        new_dir.mkdir()
        (new_dir / 'new.txt').write_text('new\n', encoding='utf-8')
        build._atomic_replace(new_dir, final_dir, old_dir)  # pylint: disable=protected-access
        self.assertTrue((final_dir / 'new.txt').is_file())
        self.assertFalse((final_dir / 'old.txt').exists())
        self.assertFalse(old_dir.exists())
        self.assertFalse(new_dir.exists())


if __name__ == '__main__':
    unittest.main()
