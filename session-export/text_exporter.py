"""
纯文本导出器

将会话数据导出为干净的纯文本格式，适合粘贴到千问等 LLM 网页端做总结和问答。
过滤系统噪音，只保留有意义的对话内容。
"""

import re
from datetime import datetime, timezone, timedelta
from parser import SessionData, Message, ToolCall

_CST = timedelta(hours=8)


def _format_ts(ts_str: str) -> str:
    """将 ISO 时间戳转为北京时间"""
    if not ts_str:
        return ""
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        dt_cst = dt.astimezone(timezone(_CST))
        return dt_cst.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return ts_str


def _clean_system_tags(text: str) -> str:
    """移除系统注入的 XML 标签内容"""
    patterns = [
        r'<system-reminder>.*?</system-reminder>',
        r'<local-command-caveat>.*?</local-command-caveat>',
        r'<command-name>.*?</command-name>',
        r'<command-message>.*?</command-message>',
        r'<command-args>.*?</command-args>',
        r'<local-command-stdout>.*?</local-command-stdout>',
        r'<ide_opened_file>.*?</ide_opened_file>',
    ]
    for p in patterns:
        text = re.sub(p, '', text, flags=re.DOTALL)
    return text.strip()


def _format_tool_call(tc: ToolCall) -> str:
    """格式化单个工具调用为简洁文本"""
    name = tc.name
    params = tc.input_params

    if name == "Bash":
        cmd = params.get("command", "")
        desc = params.get("description", "")
        header = f"[执行命令] {desc}" if desc else f"[执行命令] {cmd[:120]}"
    elif name == "Read":
        header = f"[读取文件] {params.get('file_path', '')}"
    elif name == "Write":
        header = f"[创建文件] {params.get('file_path', '')}"
    elif name == "Edit":
        header = f"[编辑文件] {params.get('file_path', '')}"
    elif name == "Glob":
        header = f"[搜索文件] {params.get('pattern', '')}"
    elif name == "Grep":
        header = f"[搜索内容] {params.get('pattern', '')} in {params.get('path', '.')}"
    elif name == "Agent":
        header = f"[子代理] {params.get('description', '')}"
    elif name == "WebSearch":
        header = f"[网页搜索] {params.get('query', '')}"
    else:
        header = f"[{name}]"

    result = tc.result
    if len(result) > 500:
        result = result[:500] + f"\n... (共 {len(tc.result)} 字符，已截断)"

    status = "失败" if tc.is_error else "成功"
    return f"{header} ({status})\n{result}" if result else header


def generate_text(session: SessionData) -> str:
    """生成纯文本格式的会话记录"""
    lines = []

    lines.append(f"# 会话记录: {session.title}")
    lines.append(f"Session ID: {session.session_id}")
    lines.append(f"项目: {session.project_dir}")
    lines.append(f"时间: {_format_ts(session.start_time)} ~ {_format_ts(session.end_time)}")
    lines.append(f"Token: 输入 {session.total_input_tokens:,} / 输出 {session.total_output_tokens:,}")
    lines.append("")
    lines.append("=" * 60)
    lines.append("")

    for msg in session.messages:
        if msg.is_meta:
            continue

        role = "【用户】" if msg.role == "user" else "【AI】"

        text = _clean_system_tags(msg.text) if msg.text else ""
        if text:
            lines.append(f"{role}")
            lines.append(text)
            lines.append("")

        if msg.tool_calls:
            for tc in msg.tool_calls:
                tool_text = _format_tool_call(tc)
                lines.append(tool_text)
                lines.append("")

        if text or msg.tool_calls:
            lines.append("-" * 40)
            lines.append("")

    if session.sub_agents:
        lines.append("")
        lines.append("=" * 60)
        lines.append("# 子代理会话")
        lines.append("")
        for sa in session.sub_agents:
            lines.append(f"## 子代理: {sa.agent_type} ({sa.agent_id[:12]})")
            lines.append("")
            for msg in sa.messages:
                if msg.is_meta:
                    continue
                role = "【用户】" if msg.role == "user" else "【AI】"
                text = _clean_system_tags(msg.text) if msg.text else ""
                if text:
                    lines.append(f"{role}")
                    lines.append(text)
                    lines.append("")

    return "\n".join(lines)
