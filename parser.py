"""
JSONL 会话记录解析器

解析 Claude Code 的 .jsonl 会话文件，提取结构化的对话数据。
支持主会话和子代理(subagent)会话的解析。

JSONL 消息类型：
- user: 用户消息或工具返回结果
- assistant: AI 回复或工具调用
- progress: hook 执行进度（过滤）
- system: 系统消息（过滤）
- queue-operation: 队列操作（过滤）
- file-history-snapshot: 文件快照（过滤）
- custom-title: 会话标题
"""

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class ToolCall:
    """工具调用记录"""
    tool_use_id: str
    name: str
    input_params: dict = field(default_factory=dict)
    result: str = ""
    is_error: bool = False


@dataclass(frozen=True)
class Message:
    """一条对话消息"""
    role: str  # "user" | "assistant"
    text: str  # 纯文本内容
    tool_calls: tuple = ()  # assistant 的工具调用
    timestamp: str = ""
    model: str = ""
    usage: dict = field(default_factory=dict)
    is_meta: bool = False  # 系统注入的消息


@dataclass(frozen=True)
class SubAgent:
    """子代理会话"""
    agent_id: str
    agent_type: str  # "Explore", "Plan" 等
    messages: tuple = ()


@dataclass(frozen=True)
class SessionData:
    """完整的会话数据"""
    session_id: str
    project_dir: str
    title: str
    messages: tuple = ()
    sub_agents: tuple = ()
    start_time: str = ""
    end_time: str = ""
    total_input_tokens: int = 0
    total_output_tokens: int = 0


def _extract_text_from_content(content) -> str:
    """
    从 message.content 中提取纯文本。
    content 可能是字符串或包含 text/tool_use/tool_result 的列表。
    """
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                texts.append(item.get("text", ""))
        return "\n".join(texts).strip()
    return ""


def _extract_tool_calls(content) -> list:
    """从 assistant message.content 中提取工具调用列表"""
    if not isinstance(content, list):
        return []
    calls = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "tool_use":
            calls.append(ToolCall(
                tool_use_id=item.get("id", ""),
                name=item.get("name", ""),
                input_params=item.get("input", {}),
            ))
    return calls


def _extract_tool_results(content) -> dict:
    """
    从 user message.content 中提取工具返回结果。
    返回 {tool_use_id: (result_text, is_error)} 的映射。
    """
    if not isinstance(content, list):
        return {}
    results = {}
    for item in content:
        if isinstance(item, dict) and item.get("type") == "tool_result":
            tool_use_id = item.get("tool_use_id", "")
            result_content = item.get("content", "")
            is_error = item.get("is_error", False)
            if isinstance(result_content, list):
                parts = []
                for part in result_content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        parts.append(part.get("text", ""))
                result_content = "\n".join(parts)
            results[tool_use_id] = (str(result_content), is_error)
    return results


def _sum_tokens(usage: dict) -> tuple:
    """从 usage 字段提取 input/output token 数"""
    input_tokens = usage.get("input_tokens", 0)
    cache_creation = usage.get("cache_creation_input_tokens", 0)
    cache_read = usage.get("cache_read_input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    return (input_tokens + cache_creation + cache_read, output_tokens)


def parse_jsonl(file_path: str) -> SessionData:
    """
    解析单个 JSONL 会话文件，返回结构化的 SessionData。

    处理逻辑：
    1. 按行读取 JSONL，按 type 分类处理
    2. 将 assistant 的 tool_use 和后续 user 的 tool_result 配对
    3. 过滤 progress/queue-operation 等噪音消息
    4. 提取会话标题、时间跨度、token 统计
    """
    records = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    session_id = Path(file_path).stem
    title = ""
    timestamps = []
    total_input = 0
    total_output = 0
    project_dir = ""

    # 第一遍：收集元数据和标题
    for rec in records:
        rec_type = rec.get("type", "")
        if rec_type == "custom-title":
            title = rec.get("customTitle", title)
        ts = rec.get("timestamp", "")
        if ts:
            timestamps.append(ts)
        if not project_dir:
            cwd = rec.get("cwd", "")
            if cwd:
                project_dir = cwd

    # 第二遍：提取对话消息
    messages = []
    pending_tool_calls: dict[str, ToolCall] = {}

    for rec in records:
        rec_type = rec.get("type", "")

        if rec_type == "assistant":
            msg = rec.get("message", {})
            content = msg.get("content", "")
            text = _extract_text_from_content(content)
            tool_calls = _extract_tool_calls(content)
            usage = msg.get("usage", {})
            inp, out = _sum_tokens(usage)
            total_input += inp
            total_output += out

            for tc in tool_calls:
                pending_tool_calls[tc.tool_use_id] = tc

            if text or tool_calls:
                messages.append(Message(
                    role="assistant",
                    text=text,
                    tool_calls=tuple(tool_calls),
                    timestamp=rec.get("timestamp", ""),
                    model=msg.get("model", ""),
                    usage=usage,
                    is_meta=False,
                ))

        elif rec_type == "user":
            msg = rec.get("message", {})
            content = msg.get("content", "")
            is_meta = rec.get("isMeta", False)

            tool_results = _extract_tool_results(content)
            if tool_results:
                for tid, (result_text, is_error) in tool_results.items():
                    if tid in pending_tool_calls:
                        old = pending_tool_calls.pop(tid)
                        updated = ToolCall(
                            tool_use_id=old.tool_use_id,
                            name=old.name,
                            input_params=old.input_params,
                            result=result_text,
                            is_error=is_error,
                        )
                        for i in range(len(messages) - 1, -1, -1):
                            m = messages[i]
                            if m.role == "assistant" and m.tool_calls:
                                new_calls = []
                                for tc in m.tool_calls:
                                    if tc.tool_use_id == updated.tool_use_id:
                                        new_calls.append(updated)
                                    else:
                                        new_calls.append(tc)
                                messages[i] = Message(
                                    role=m.role,
                                    text=m.text,
                                    tool_calls=tuple(new_calls),
                                    timestamp=m.timestamp,
                                    model=m.model,
                                    usage=m.usage,
                                    is_meta=m.is_meta,
                                )
                                break
                continue

            text = _extract_text_from_content(content)
            if text:
                messages.append(Message(
                    role="user",
                    text=text,
                    timestamp=rec.get("timestamp", ""),
                    is_meta=is_meta,
                ))

    sub_agents = _parse_sub_agents(file_path)
    title = title.lstrip("&").strip() if title else session_id[:8]

    return SessionData(
        session_id=session_id,
        project_dir=project_dir,
        title=title,
        messages=tuple(messages),
        sub_agents=tuple(sub_agents),
        start_time=timestamps[0] if timestamps else "",
        end_time=timestamps[-1] if timestamps else "",
        total_input_tokens=total_input,
        total_output_tokens=total_output,
    )


def _parse_sub_agents(main_jsonl_path: str) -> list:
    """解析主会话关联的子代理会话"""
    session_dir = Path(main_jsonl_path).with_suffix("")
    subagents_dir = session_dir / "subagents"
    if not subagents_dir.exists():
        return []

    agents = []
    for meta_file in subagents_dir.glob("*.meta.json"):
        agent_id = meta_file.stem.replace(".meta", "")
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except (json.JSONDecodeError, OSError):
            meta = {}

        agent_type = meta.get("agentType", "Unknown")
        jsonl_file = subagents_dir / f"{agent_id}.jsonl"
        if jsonl_file.exists():
            sub_data = parse_jsonl(str(jsonl_file))
            agents.append(SubAgent(
                agent_id=agent_id,
                agent_type=agent_type,
                messages=sub_data.messages,
            ))

    return agents


def find_project_sessions(projects_base: str, project_cwd: str) -> list:
    """
    根据项目工作目录找到所有会话文件。

    参数:
        projects_base: ~/.claude/projects/ 的路径
        project_cwd: 项目工作目录，如 D:\\00_Project\\07_kb_app

    返回:
        [(session_id, jsonl_path, mtime)] 按修改时间倒序排列
    """
    # Claude Code 的目录编码规则：
    # D:\00_Project\07_kb_app → D--00-Project-07-kb-app
    # 规则：将 \、:、/、空格、下划线 替换为 -
    normalized = project_cwd.replace("\\", "-").replace("/", "-").replace(":", "-").replace(" ", "-").replace("_", "-")

    project_dir = None
    base = Path(projects_base)
    if not base.exists():
        return []

    for d in base.iterdir():
        if d.is_dir() and d.name.lower() == normalized.lower():
            project_dir = d
            break

    if not project_dir:
        return []

    sessions = []
    for jsonl in project_dir.glob("*.jsonl"):
        session_id = jsonl.stem
        mtime = jsonl.stat().st_mtime
        sessions.append((session_id, str(jsonl), mtime))

    return sorted(sessions, key=lambda x: x[2], reverse=True)
