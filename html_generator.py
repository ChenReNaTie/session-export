"""
HTML 报告生成器

将解析后的 SessionData 生成可视化 HTML 单文件报告。
特性：
- 工具调用/文件内容默认折叠，点击展开
- Token 用量统计
- 子代理对话独立区块
- 纯 CSS + 原生 JS，零外部依赖
"""

import html
import re
from datetime import datetime, timezone, timedelta
from parser import SessionData, Message, ToolCall, SubAgent


# 北京时间偏移
_CST = timedelta(hours=8)


def _format_ts(ts_str: str) -> str:
    """将 ISO 时间戳转为北京时间显示"""
    if not ts_str:
        return ""
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        dt_cst = dt.astimezone(timezone(_CST))
        return dt_cst.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return ts_str


def _format_tokens(n: int) -> str:
    """格式化 token 数量"""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def _escape(text: str) -> str:
    """HTML 转义"""
    return html.escape(text)


def _tool_summary(tc: ToolCall) -> str:
    """生成工具调用的摘要行"""
    name = tc.name
    params = tc.input_params

    if name == "Bash":
        cmd = params.get("command", "")
        desc = params.get("description", "")
        if desc:
            return f"Bash: {desc}"
        return f"Bash: {cmd[:80]}{'...' if len(cmd) > 80 else ''}"
    elif name == "Read":
        return f"Read: {params.get('file_path', '')}"
    elif name in ("Write", "Edit"):
        return f"{name}: {params.get('file_path', '')}"
    elif name == "Glob":
        return f"Glob: {params.get('pattern', '')}"
    elif name == "Grep":
        return f"Grep: {params.get('pattern', '')} in {params.get('path', '.')}"
    elif name == "Agent":
        return f"Agent: {params.get('description', params.get('prompt', '')[:60])}"
    elif name == "WebSearch":
        return f"WebSearch: {params.get('query', '')}"
    elif name == "WebFetch":
        return f"WebFetch: {params.get('url', '')[:60]}"
    elif name == "TaskCreate":
        return f"TaskCreate: {params.get('subject', '')}"
    elif name == "TaskUpdate":
        return f"TaskUpdate: #{params.get('taskId', '')} -> {params.get('status', '')}"
    else:
        return f"{name}: {str(params)[:80]}"


def _render_tool_detail(tc: ToolCall, idx: int) -> str:
    """渲染单个工具调用的可折叠区块"""
    summary = _escape(_tool_summary(tc))
    status_icon = "&#x2717;" if tc.is_error else "&#x2713;"
    status_class = "error" if tc.is_error else "success"

    input_html = ""
    if tc.name == "Bash":
        cmd = tc.input_params.get("command", "")
        input_html = f'<pre class="tool-input"><code>{_escape(cmd)}</code></pre>'
    elif tc.name in ("Write", "Edit"):
        fp = tc.input_params.get("file_path", "")
        if tc.name == "Edit":
            old = tc.input_params.get("old_string", "")
            new = tc.input_params.get("new_string", "")
            input_html = (
                f'<div class="edit-block">'
                f'<div class="edit-label">文件: {_escape(fp)}</div>'
                f'<div class="edit-label">替换前:</div>'
                f'<pre class="tool-input old-str"><code>{_escape(old)}</code></pre>'
                f'<div class="edit-label">替换后:</div>'
                f'<pre class="tool-input new-str"><code>{_escape(new)}</code></pre>'
                f'</div>'
            )
        else:
            content = tc.input_params.get("content", "")
            preview = content[:200] + ("..." if len(content) > 200 else "")
            input_html = (
                f'<div class="edit-block">'
                f'<div class="edit-label">文件: {_escape(fp)} '
                f'({len(content)} 字符)</div>'
                f'<pre class="tool-input"><code>{_escape(preview)}</code></pre>'
                f'</div>'
            )
    elif tc.name == "Read":
        fp = tc.input_params.get("file_path", "")
        input_html = f'<div class="edit-label">文件: {_escape(fp)}</div>'
    else:
        params_str = str(tc.input_params)
        if len(params_str) > 500:
            params_str = params_str[:500] + "..."
        input_html = f'<pre class="tool-input"><code>{_escape(params_str)}</code></pre>'

    result = tc.result
    result_preview = result[:300] + ("..." if len(result) > 300 else "")
    result_full = result if len(result) > 300 else ""

    result_html = f'<pre class="tool-output"><code>{_escape(result_preview)}</code></pre>'
    if result_full:
        result_html += (
            f'<details class="result-full">'
            f'<summary>展开完整输出 ({len(result)} 字符)</summary>'
            f'<pre class="tool-output"><code>{_escape(result_full)}</code></pre>'
            f'</details>'
        )

    return (
        f'<details class="tool-block">'
        f'<summary class="tool-summary">'
        f'<span class="tool-icon {status_class}">{status_icon}</span> '
        f'{summary}'
        f'</summary>'
        f'<div class="tool-detail">'
        f'{input_html}'
        f'<div class="tool-result-label">输出:</div>'
        f'{result_html}'
        f'</div>'
        f'</details>'
    )


def _render_message(msg: Message, idx: int) -> str:
    """渲染单条消息"""
    if msg.is_meta:
        return ""

    role_class = msg.role
    role_label = "用户" if msg.role == "user" else "AI"
    ts = _format_ts(msg.timestamp)

    parts = []

    if msg.text:
        text = msg.text
        text = re.sub(r'<system-reminder>.*?</system-reminder>', '', text, flags=re.DOTALL)
        text = re.sub(r'<local-command-caveat>.*?</local-command-caveat>', '', text, flags=re.DOTALL)
        text = re.sub(r'<command-name>.*?</command-name>', '', text, flags=re.DOTALL)
        text = re.sub(r'<command-message>.*?</command-message>', '', text, flags=re.DOTALL)
        text = re.sub(r'<command-args>.*?</command-args>', '', text, flags=re.DOTALL)
        text = re.sub(r'<local-command-stdout>.*?</local-command-stdout>', '', text, flags=re.DOTALL)
        text = re.sub(r'<ide_opened_file>.*?</ide_opened_file>', '', text, flags=re.DOTALL)
        text = text.strip()
        if text:
            parts.append(f'<div class="msg-text">{_escape(text)}</div>')

    if msg.tool_calls:
        tool_html = "".join(
            _render_tool_detail(tc, i) for i, tc in enumerate(msg.tool_calls)
        )
        parts.append(f'<div class="msg-tools">{tool_html}</div>')

    if not parts:
        return ""

    content = "\n".join(parts)
    model_badge = ""
    if msg.model:
        model_badge = f'<span class="model-badge">{_escape(msg.model)}</span>'

    return (
        f'<div class="message {role_class}" id="msg-{idx}">'
        f'<div class="msg-header">'
        f'<span class="role-label">{role_label}</span>'
        f'{model_badge}'
        f'<span class="timestamp">{ts}</span>'
        f'</div>'
        f'{content}'
        f'</div>'
    )


def _render_sub_agent(sa: SubAgent) -> str:
    """渲染子代理区块"""
    msgs_html = "\n".join(
        _render_message(m, i) for i, m in enumerate(sa.messages)
    )
    msgs_html = msgs_html.strip()
    if not msgs_html:
        return ""
    return (
        f'<details class="subagent-block">'
        f'<summary class="subagent-summary">'
        f'子代理: {_escape(sa.agent_type)} ({_escape(sa.agent_id[:12])})'
        f'</summary>'
        f'<div class="subagent-content">{msgs_html}</div>'
        f'</details>'
    )


def generate_html(session: SessionData) -> str:
    """生成完整的 HTML 报告"""
    user_count = sum(1 for m in session.messages if m.role == "user" and not m.is_meta)
    assistant_count = sum(1 for m in session.messages if m.role == "assistant")
    tool_count = sum(len(m.tool_calls) for m in session.messages)

    start = _format_ts(session.start_time)
    end = _format_ts(session.end_time)

    messages_html = "\n".join(
        _render_message(m, i) for i, m in enumerate(session.messages)
    )

    subagents_html = "\n".join(
        _render_sub_agent(sa) for sa in session.sub_agents
    )
    if subagents_html.strip():
        subagents_html = (
            f'<div class="subagents-section">'
            f'<h2>子代理会话</h2>'
            f'{subagents_html}'
            f'</div>'
        )

    return _build_full_html(
        title=session.title,
        session_id=session.session_id,
        project_dir=session.project_dir,
        start=start, end=end,
        user_count=user_count,
        assistant_count=assistant_count,
        tool_count=tool_count,
        total_input=session.total_input_tokens,
        total_output=session.total_output_tokens,
        messages_html=messages_html,
        subagents_html=subagents_html,
    )


def _build_full_html(**kw) -> str:
    """组装完整 HTML 页面"""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_escape(kw['title'])} - 会话报告</title>
{_get_css()}
</head>
<body>
<div class="container">
  <header class="report-header">
    <h1>{_escape(kw['title'])}</h1>
    <div class="meta-grid">
      <div class="meta-item">
        <span class="meta-label">Session ID</span>
        <span class="meta-value">{_escape(kw['session_id'][:12])}...</span>
      </div>
      <div class="meta-item">
        <span class="meta-label">项目目录</span>
        <span class="meta-value">{_escape(kw['project_dir'])}</span>
      </div>
      <div class="meta-item">
        <span class="meta-label">时间</span>
        <span class="meta-value">{kw['start']} ~ {kw['end']}</span>
      </div>
    </div>
    <div class="stats-bar">
      <div class="stat">
        <span class="stat-num">{kw['user_count']}</span>
        <span class="stat-label">用户消息</span>
      </div>
      <div class="stat">
        <span class="stat-num">{kw['assistant_count']}</span>
        <span class="stat-label">AI 回复</span>
      </div>
      <div class="stat">
        <span class="stat-num">{kw['tool_count']}</span>
        <span class="stat-label">工具调用</span>
      </div>
      <div class="stat">
        <span class="stat-num">{_format_tokens(kw['total_input'])}</span>
        <span class="stat-label">输入 Token</span>
      </div>
      <div class="stat">
        <span class="stat-num">{_format_tokens(kw['total_output'])}</span>
        <span class="stat-label">输出 Token</span>
      </div>
    </div>
    <div class="toolbar">
      <button onclick="toggleAllTools(true)">展开所有工具调用</button>
      <button onclick="toggleAllTools(false)">折叠所有工具调用</button>
    </div>
  </header>
  <main class="conversation">
    {kw['messages_html']}
  </main>
  {kw['subagents_html']}
</div>
{_get_js()}
</body>
</html>"""


def _get_css() -> str:
    """返回内联 CSS 样式"""
    return """<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0d1117; color: #c9d1d9; line-height: 1.6; }
.container { max-width: 960px; margin: 0 auto; padding: 20px; }
.report-header { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 24px; margin-bottom: 24px; }
.report-header h1 { color: #58a6ff; font-size: 1.5em; margin-bottom: 16px; }
.meta-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 16px; }
.meta-item { font-size: 0.85em; }
.meta-label { color: #8b949e; margin-right: 8px; }
.meta-value { color: #c9d1d9; }
.stats-bar { display: flex; gap: 24px; padding: 12px 0; border-top: 1px solid #30363d; border-bottom: 1px solid #30363d; margin-bottom: 12px; }
.stat { text-align: center; }
.stat-num { display: block; font-size: 1.3em; font-weight: 600; color: #58a6ff; }
.stat-label { font-size: 0.75em; color: #8b949e; }
.toolbar { display: flex; gap: 8px; }
.toolbar button { background: #21262d; border: 1px solid #30363d; color: #c9d1d9; padding: 4px 12px; border-radius: 4px; cursor: pointer; font-size: 0.8em; }
.toolbar button:hover { background: #30363d; }
.conversation { display: flex; flex-direction: column; gap: 16px; }
.message { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; }
.message.user { border-left: 3px solid #3fb950; }
.message.assistant { border-left: 3px solid #58a6ff; }
.msg-header { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.role-label { font-weight: 600; font-size: 0.85em; padding: 2px 8px; border-radius: 4px; }
.user .role-label { background: #0d2818; color: #3fb950; }
.assistant .role-label { background: #0d1d30; color: #58a6ff; }
.model-badge { font-size: 0.7em; background: #21262d; color: #8b949e; padding: 1px 6px; border-radius: 3px; }
.timestamp { font-size: 0.75em; color: #484f58; margin-left: auto; }
.msg-text { white-space: pre-wrap; word-break: break-word; font-size: 0.9em; }
.msg-tools { margin-top: 8px; display: flex; flex-direction: column; gap: 4px; }
.tool-block { border: 1px solid #30363d; border-radius: 6px; overflow: hidden; }
.tool-summary { padding: 6px 12px; cursor: pointer; font-size: 0.82em; background: #0d1117; color: #8b949e; list-style: none; display: flex; align-items: center; gap: 6px; }
.tool-summary::-webkit-details-marker { display: none; }
.tool-summary::before { content: "\\25B6"; font-size: 0.7em; transition: transform 0.2s; }
details[open] > .tool-summary::before { transform: rotate(90deg); }
.tool-icon.success { color: #3fb950; }
.tool-icon.error { color: #f85149; }
.tool-detail { padding: 8px 12px; background: #0d1117; }
.tool-input, .tool-output { background: #161b22; border: 1px solid #21262d; border-radius: 4px; padding: 8px; font-size: 0.8em; overflow-x: auto; margin: 4px 0; }
.tool-input code, .tool-output code { font-family: "Cascadia Code", "Fira Code", monospace; white-space: pre-wrap; word-break: break-all; }
.tool-result-label { font-size: 0.75em; color: #8b949e; margin-top: 6px; }
.edit-label { font-size: 0.78em; color: #8b949e; margin: 4px 0 2px; }
.old-str { border-left: 3px solid #f85149; }
.new-str { border-left: 3px solid #3fb950; }
.result-full summary { font-size: 0.75em; color: #58a6ff; cursor: pointer; margin: 4px 0; }
.subagents-section { margin-top: 24px; }
.subagents-section h2 { color: #d2a8ff; font-size: 1.1em; margin-bottom: 12px; }
.subagent-block { border: 1px solid #30363d; border-radius: 8px; margin-bottom: 8px; overflow: hidden; }
.subagent-summary { padding: 10px 16px; background: #161b22; cursor: pointer; color: #d2a8ff; font-size: 0.9em; }
.subagent-content { padding: 12px; display: flex; flex-direction: column; gap: 12px; }
</style>"""


def _get_js() -> str:
    """返回内联 JavaScript"""
    return """<script>
function toggleAllTools(open) {
  document.querySelectorAll('.tool-block').forEach(d => d.open = open);
}
</script>"""
