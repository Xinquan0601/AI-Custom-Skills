"""集中常量：口径阈值、展示标签、配色与展示上限。

改口径先改这里，并同步 docs/stats-schema.md 与 ADR——统计口径是报告可比性的根。
"""
import os

# ============================================================================
# 版本与口径
# ============================================================================

# stats.json 结构版本。schema 不兼容变更时 +1，环比只在同版本存档间进行。
SCHEMA_VERSION = 2

# 报告展示时区（小时）。数据源一律 UTC，展示与窗口计算都按本地时区。
# 默认 UTC+8；可用 --utc-offset 或环境变量 INSIGHTS_UTC_OFFSET 覆盖（见 utc_offset()）。
DEFAULT_UTC_OFFSET_HOURS = 8
UTC_OFFSET_ENV = 'INSIGHTS_UTC_OFFSET'


def utc_offset() -> int:
    """当前展示时区偏移；非法值回落到默认值，不让一个环境变量毁掉整份报告。"""
    raw = os.environ.get(UTC_OFFSET_ENV, '').strip()
    if raw:
        try:
            hours = int(float(raw))
        except ValueError:
            return DEFAULT_UTC_OFFSET_HOURS
        if -12 <= hours <= 14:
            return hours
    return DEFAULT_UTC_OFFSET_HOURS

# 「实质会话」口径（ADR-0001）：用户消息 ≥2 条且时长 ≥1 分钟。
# 不满足但有用户消息的会话记为「快速问答」，单独计数，不混入主口径。
SUBSTANTIVE_MIN_USER_MESSAGES = 2
SUBSTANTIVE_MIN_DURATION_MINUTES = 1

# 默认窗口：未指定时覆盖数据源全部时间（由导出文件决定），这里只做兜底。
DEFAULT_WINDOW_DAYS = 15

# 并行会话检测：30 分钟窗口内多会话交错即算并行。
PARALLEL_OVERLAP_WINDOW_MS = 30 * 60 * 1000

# 响应时间：只统计 2 秒到 1 小时之间的「用户发出 → 助手回应」间隔。
RESPONSE_TIME_MIN_SECONDS = 2
RESPONSE_TIME_MAX_SECONDS = 3600

# 工具报错分类用的文本长度上限，避免把整段堆栈塞进分类器。
ERROR_TEXT_SCAN_CHARS = 4000

# 展示上限
TOP_PROJECTS = 8
TOP_TOOLS = 12
TOP_AGENTS_IN_CHART = 6
TOP_ERROR_TOOLS = 6
TOP_ERROR_CATEGORIES = 6
NARRATIVE_SESSION_SAMPLES = 40
NARRATIVE_MESSAGE_CHARS = 400
SESSION_SUMMARY_CHARS = 120
FIRST_PROMPT_CHARS = 200

# ============================================================================
# Agent（数据源 side 的 agent_key → 展示名 / 配色）
# ============================================================================

AGENT_LABELS = {
    'claudecode': 'Claude Code',
    'codex': 'Codex',
    'zcode': 'ZCode',
    'opencode': 'OpenCode',
    'workbuddy': 'WorkBuddy',
    'deepseekharness': 'DeepSeek Harness',
}

AGENT_COLORS = {
    'claudecode': '#d97757',
    'codex': '#10a37f',
    'zcode': '#2563eb',
    'opencode': '#7c3aed',
    'workbuddy': '#0ea5e9',
    'deepseekharness': '#4f46e5',
}

UNKNOWN_AGENT_LABEL = '其他 Agent'
UNKNOWN_AGENT_COLOR = '#94a3b8'


def agent_label(key):
    return AGENT_LABELS.get((key or '').strip().lower(), key or UNKNOWN_AGENT_LABEL)


def agent_color(key):
    return AGENT_COLORS.get((key or '').strip().lower(), UNKNOWN_AGENT_COLOR)


# ============================================================================
# 工具族：把不同 Agent 的工具名归一到 7 个能力族
# ============================================================================

TOOL_FAMILY_ORDER = ['exec', 'edit', 'read', 'search', 'web', 'agent', 'other']

TOOL_FAMILY_LABELS = {
    'exec': '执行命令',
    'edit': '写文件/改代码',
    'read': '读取文件',
    'search': '检索',
    'web': '联网',
    'agent': '子代理/任务',
    'other': '其他交互',
}

TOOL_FAMILY_COLORS = {
    'exec': '#0ea5e9',
    'edit': '#10b981',
    'read': '#6366f1',
    'search': '#f59e0b',
    'web': '#ec4899',
    'agent': '#8b5cf6',
    'other': '#94a3b8',
}

# 小写工具名 → 能力族；未列出的归入 other。
TOOL_FAMILY_BY_NAME = {
    # 执行命令 / 代码沙箱
    'bash': 'exec', 'shell': 'exec', 'powershell': 'exec', 'exec_command': 'exec',
    'run_code': 'exec', 'execute': 'exec', 'run_terminal_cmd': 'exec',
    # 写 / 改
    'write': 'edit', 'write_file': 'edit', 'create_file': 'edit', 'edit': 'edit',
    'multiedit': 'edit', 'apply_patch': 'edit', 'str_replace': 'edit',
    'str_replace_editor': 'edit', 'notebookedit': 'edit',
    # 读
    'read': 'read', 'read_file': 'read', 'view_image': 'read', 'viewimage': 'read',
    'open_file': 'read', 'notebookread': 'read',
    # 检索
    'grep': 'search', 'glob': 'search', 'search': 'search', 'find': 'search',
    'ls': 'search', 'list_dir': 'search',
    # 联网
    'webfetch': 'web', 'websearch': 'web', 'web_search': 'web', 'fetch': 'web',
    # 子代理 / 任务
    'agent': 'agent', 'task': 'agent', 'subagent': 'agent', 'spawn_agent': 'agent',
}

WRITE_TOOL_NAMES = {'write', 'write_file', 'create_file', 'edit', 'multiedit',
                    'str_replace', 'str_replace_editor', 'notebookedit'}
PATCH_TOOL_NAMES = {'apply_patch', 'patch'}
SHELL_TOOL_NAMES = {'bash', 'shell', 'powershell', 'exec_command', 'run_terminal_cmd'}


def tool_family(tool_name):
    name = (tool_name or '').strip().lower()
    if not name:
        return 'other'
    if name.startswith('mcp__') or name.startswith('mcp_'):
        return 'other'
    if name in TOOL_FAMILY_BY_NAME:
        return TOOL_FAMILY_BY_NAME[name]
    for prefix, family in (('web', 'web'), ('grep', 'search'), ('read', 'read'),
                           ('write', 'edit'), ('edit', 'edit'), ('bash', 'exec'),
                           ('shell', 'exec')):
        if name.startswith(prefix):
            return family
    return 'other'


# ============================================================================
# 语言识别与代码产出
# ============================================================================

EXTENSION_TO_LANGUAGE = {
    '.ts': 'TypeScript', '.tsx': 'TypeScript', '.js': 'JavaScript',
    '.jsx': 'JavaScript', '.mjs': 'JavaScript', '.py': 'Python', '.rb': 'Ruby',
    '.go': 'Go', '.rs': 'Rust', '.java': 'Java', '.kt': 'Kotlin', '.swift': 'Swift',
    '.c': 'C', '.h': 'C', '.cc': 'C++', '.cpp': 'C++', '.hpp': 'C++',
    '.cs': 'C#', '.php': 'PHP', '.lua': 'Lua', '.sh': 'Shell', '.ps1': 'PowerShell',
    '.sql': 'SQL', '.md': 'Markdown', '.json': 'JSON', '.yaml': 'YAML', '.yml': 'YAML',
    '.toml': 'TOML', '.ini': 'INI', '.xml': 'XML', '.html': 'HTML', '.css': 'CSS',
    '.scss': 'CSS', '.vue': 'Vue', '.svelte': 'Svelte', '.dart': 'Dart',
}

# 会话涉及文件时的语言统计上限，防止超长路径列表拖慢渲染。
MAX_LANGUAGES = 12

# ============================================================================
# 工具报错分类：命中即归类，按顺序匹配
# ============================================================================

ERROR_CATEGORY_ORDER = [
    'sandbox_permission', 'edit_conflict', 'file_access', 'file_changed',
    'not_found', 'timeout', 'network', 'syntax', 'runtime', 'invalid_argument',
    'config', 'command_failed', 'interrupted', 'unclassified', 'other',
]

ERROR_CATEGORY_LABELS = {
    'sandbox_permission': '权限/沙箱拦截',
    'edit_conflict': '编辑冲突（old_string 对不上）',
    'file_access': '文件读写失败',
    'file_changed': '文件已变更',
    'not_found': '文件/路径不存在',
    'timeout': '执行超时',
    'network': '网络失败',
    'syntax': '语法/解析错误',
    'runtime': '运行时错误',
    'invalid_argument': '参数不合法',
    'config': '配置缺失（API Key 等）',
    'command_failed': '命令执行失败',
    'interrupted': '被中断',
    'unclassified': '未提供错误详情',
    'other': '其他错误',
}

# 条形图标签窄，另配一套短名，长名留给正文与样本
ERROR_CATEGORY_SHORT = {
    'sandbox_permission': '权限拦截',
    'edit_conflict': '编辑冲突',
    'file_access': '文件读写',
    'file_changed': '文件变更',
    'not_found': '路径不存在',
    'timeout': '超时',
    'network': '网络',
    'syntax': '语法解析',
    'runtime': '运行时',
    'invalid_argument': '参数不合法',
    'config': '配置缺失',
    'command_failed': '命令失败',
    'interrupted': '被中断',
    'unclassified': '无错误详情',
    'other': '其他',
}

# 顺序即优先级：越具体的特征越靠前。
# 注意：判错前会先剥掉导出包附加的 "File sandbox: xxx." 尾巴，否则所有报错都会被归到沙箱。
ERROR_CATEGORY_PATTERNS = [
    ('sandbox_permission', ('grantwrite', 'setnamedsecurityinfo', 'permission denied',
                            'access denied', 'win32 5)', 'eperm', 'eacces',
                            'file sandbox: read-only')),
    ('edit_conflict', ('old_string', 'oldstring', 'string to replace not found',
                       'must differ', 'matched 2 times', 'multiple matches',
                       'found 0 occurrences', 'no changes to apply')),
    ('file_access', ('cannot read', 'cannot write', 'cannot modify', 'cannot edit',
                     'failed to read', 'failed to write', 'permissionerror')),
    ('file_changed', ('has been modified since read', 'modified since read',
                      'file changed since')),
    ('not_found', ('file not found', 'no such file', 'does not exist',
                   'cannot find path', 'enoent')),
    ('timeout', ('deadline reached', 'timed out', 'timeout', 'etimedout')),
    ('network', ('econnrefused', 'enotfound', 'connection reset',
                 'network error', 'tls handshake', 'ssl error', 'proxy error',
                 'fetch failed')),
    ('syntax', ('expected', 'unexpected token', 'unexpected eof',
                'expression expected', 'syntaxerror', 'syntax error',
                'unexpected unicode escape')),
    ('runtime', ('typeerror', 'referenceerror', 'is not defined',
                 'is not a function', 'index out of bounds')),
    ('invalid_argument', ('out of range', 'must be a positive', 'must differ',
                          'lossless json', 'invalid argument')),
    ('config', ('no api key', 'not configured', 'missing env', 'api_key')),
    ('command_failed', ('exit code', 'exit status', 'command failed',
                        'failed with code', 'non-zero', 'exit 2')),
    ('interrupted', ('interrupted', 'cancelled', 'canceled', 'aborted')),
]

# 客户端写进 user 角色的系统提示，统计消息量前要剔掉
SYNTHETIC_USER_PREFIXES = (
    'Time sampled while preparing turn',
    'The approval policy changed from',
    '<path>',
)

# 报错正文为空时，至少按工具族给出「未提供错误详情」，不做猜测
# 报错正文为空时不做任何猜测：导出包只给了状态，猜错类型比不分类更糟
EMPTY_ERROR_TOOL_FAMILY: dict[str, str] = {}

TOOL_RESULT_ERROR_STATUSES = {'error', 'failed', 'failure'}
TOOL_RESULT_INCOMPLETE_STATUSES = {'incomplete', 'incomplete_result'}

# ============================================================================
# 报告展示标签
# ============================================================================

OUTCOME_ORDER = ['not_achieved', 'partially_achieved', 'mostly_achieved',
                 'fully_achieved', 'unclear_from_transcript']
SATISFACTION_ORDER = ['frustrated', 'dissatisfied', 'likely_satisfied',
                      'satisfied', 'happy', 'unsure']

LABEL_MAP = {
    # 目标类别
    'debug_investigate': '调试/排查', 'implement_feature': '实现功能',
    'fix_bug': '修 Bug', 'write_script_tool': '写脚本/工具',
    'refactor_code': '重构代码', 'configure_system': '配置系统',
    'create_pr_commit': '建 PR/提交', 'analyze_data': '分析数据',
    'understand_codebase': '理解代码库', 'write_tests': '写测试',
    'write_docs': '写文档', 'deploy_infra': '部署/基建',
    'warmup_minimal': '缓存预热',
    # 有效因素
    'fast_accurate_search': '快速准确检索', 'correct_code_edits': '正确修改代码',
    'good_explanations': '讲解清晰', 'proactive_help': '主动帮助',
    'multi_file_changes': '多文件修改', 'handled_complexity': '处理复杂任务',
    'good_debugging': '调试得当',
    # 摩擦类型
    'misunderstood_request': '误解需求', 'wrong_approach': '方法不对',
    'buggy_code': '代码有 Bug', 'user_rejected_action': '用户拒绝操作',
    'claude_got_blocked': '被卡住', 'user_stopped_early': '会话被打断',
    'wrong_file_or_location': '改错文件/位置', 'excessive_changes': '改动过多',
    'slow_or_verbose': '慢/啰嗦', 'tool_failed': '工具/模型故障',
    'user_unclear': '需求边界不清晰', 'external_issue': '外部问题',
    # 满意度
    'frustrated': '沮丧', 'dissatisfied': '不满意', 'likely_satisfied': '可能满意',
    'satisfied': '满意', 'happy': '高兴', 'unsure': '未知', 'neutral': '中性',
    'delighted': '欣喜',
    # 会话类型
    'single_task': '单任务', 'multi_task': '多任务',
    'iterative_refinement': '迭代打磨', 'exploration': '探索',
    'quick_question': '快速问答',
    # 结果
    'fully_achieved': '完全达成', 'mostly_achieved': '基本达成',
    'partially_achieved': '部分达成', 'not_achieved': '未达成',
    'unclear_from_transcript': '结果不明',
    # 帮助度
    'unhelpful': '没用', 'slightly_helpful': '略有帮助',
    'moderately_helpful': '中等帮助', 'very_helpful': '很有帮助',
    'essential': '关键作用',
}
