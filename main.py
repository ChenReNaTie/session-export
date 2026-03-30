"""
Session Export 主入口

用法：
    python main.py --list --project-dir D:\\00_Project\\07_kb_app
    python main.py --project-dir D:\\00_Project\\07_kb_app
    python main.py --session-id abc123 --project-dir D:\\00_Project\\07_kb_app
    python main.py --all --project-dir D:\\00_Project\\07_kb_app
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# 将脚本所在目录加入 sys.path，确保同目录 import 正常
sys.path.insert(0, str(Path(__file__).parent))

from parser import parse_jsonl, find_project_sessions
from html_generator import generate_html
from text_exporter import generate_text


_CST = timedelta(hours=8)
_DEFAULT_PROJECTS_BASE = os.path.expanduser("~/.claude/projects")


def _safe_dirname(name: str, max_len: int = 50) -> str:
    """将标题转为安全的目录名"""
    safe = re.sub(r'[<>:"/\\|?*]', '', name)
    safe = safe.strip(". ")
    return safe[:max_len] if safe else "untitled"


def _format_ts_short(ts_str: str) -> str:
    """将 ISO 时间戳转为短日期格式 YYYY-MM-DD"""
    if not ts_str:
        return "unknown"
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        dt_cst = dt.astimezone(timezone(_CST))
        return dt_cst.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return "unknown"


def export_session(jsonl_path: str, output_dir: str) -> tuple:
    """
    导出单个会话，生成 HTML 报告和纯文本文件。

    参数:
        jsonl_path: JSONL 文件路径
        output_dir: 输出根目录

    返回:
        (html_path, text_path)
    """
    print(f"  解析: {jsonl_path}")
    session = parse_jsonl(jsonl_path)

    date_str = _format_ts_short(session.start_time)
    dir_name = f"{date_str}_{_safe_dirname(session.title)}"
    out_path = Path(output_dir) / dir_name
    out_path.mkdir(parents=True, exist_ok=True)

    html_content = generate_html(session)
    html_file = out_path / "会话报告.html"
    with open(html_file, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"  HTML: {html_file}")

    text_content = generate_text(session)
    text_file = out_path / "会话原文.txt"
    with open(text_file, "w", encoding="utf-8") as f:
        f.write(text_content)
    print(f"  文本: {text_file}")

    user_count = sum(1 for m in session.messages if m.role == "user" and not m.is_meta)
    assistant_count = sum(1 for m in session.messages if m.role == "assistant")
    tool_count = sum(len(m.tool_calls) for m in session.messages)
    print(f"  统计: {user_count} 条用户消息, {assistant_count} 条 AI 回复, {tool_count} 次工具调用")

    return (str(html_file), str(text_file))


def list_sessions(projects_base: str, project_dir: str) -> None:
    """列出项目的所有会话"""
    sessions = find_project_sessions(projects_base, project_dir)
    if not sessions:
        print(f"未找到项目 {project_dir} 的会话记录")
        return

    print(f"项目: {project_dir}")
    print(f"共 {len(sessions)} 个会话:\n")

    for sid, path, mtime in sessions:
        dt = datetime.fromtimestamp(mtime)
        size = os.path.getsize(path)
        size_str = f"{size / 1024:.0f}KB" if size < 1024 * 1024 else f"{size / 1024 / 1024:.1f}MB"

        title = ""
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        obj = json.loads(line.strip())
                        if obj.get("type") == "custom-title":
                            title = obj.get("customTitle", "").lstrip("&").strip()
                    except json.JSONDecodeError:
                        continue
        except OSError:
            pass

        title_display = title if title else "(无标题)"
        print(f"  {sid[:12]}...  {dt:%Y-%m-%d %H:%M}  {size_str:>8}  {title_display}")


def main():
    """主入口"""
    ap = argparse.ArgumentParser(description="Claude Code 会话记录导出工具")
    ap.add_argument("--session-id", "-s", help="指定 session ID（默认最近一个）")
    ap.add_argument("--project-dir", "-p", default=os.getcwd(), help="项目工作目录")
    ap.add_argument("--projects-base", "-b", default=_DEFAULT_PROJECTS_BASE, help="Claude projects 目录")
    ap.add_argument("--output-dir", "-o", help="输出目录（默认 项目目录/session_reports/）")
    ap.add_argument("--list", "-l", action="store_true", help="列出所有会话")
    ap.add_argument("--all", "-a", action="store_true", help="导出所有会话")
    args = ap.parse_args()

    output_dir = args.output_dir or os.path.join(args.project_dir, "session_reports")

    if args.list:
        list_sessions(args.projects_base, args.project_dir)
        return

    sessions = find_project_sessions(args.projects_base, args.project_dir)
    if not sessions:
        print(f"错误: 未找到项目 {args.project_dir} 的会话记录")
        print(f"搜索路径: {args.projects_base}")
        sys.exit(1)

    if args.all:
        print(f"导出 {len(sessions)} 个会话...\n")
        for sid, path, _ in sessions:
            try:
                export_session(path, output_dir)
                print()
            except Exception as e:
                print(f"  错误: {e}\n")
        print(f"完成! 输出目录: {output_dir}")
        return

    if args.session_id:
        target = None
        for sid, path, _ in sessions:
            if sid.startswith(args.session_id):
                target = path
                break
        if not target:
            print(f"错误: 未找到 session ID 以 '{args.session_id}' 开头的会话")
            sys.exit(1)
    else:
        target = sessions[0][1]

    export_session(target, output_dir)
    print(f"\n完成! 输出目录: {output_dir}")


if __name__ == "__main__":
    main()
