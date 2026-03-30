---
name: session-export
description: 导出 Claude Code 会话记录为可视化 HTML 报告和纯文本文件，用于回顾、总结和知识沉淀。
---

# 会话记录导出工具

## When to Use
- 用户说"导出会话"、"保存会话"、"会话报告"、"session export"
- 用户想回顾当前或历史会话的内容
- 用户想把会话内容导出给 LLM 做总结或问答
- 会话结束前，用户想保存本次对话的完整记录

## 脚本位置

Python 脚本位于 `~/.claude/skills/session-export/` 目录下（全局，跨项目可用）。

## Workflow

当用户触发此 skill 时，按以下步骤执行：

### Step 1: 确认导出范围

询问用户要导出哪个会话：
- 默认：当前项目最近的会话
- 可选：指定 session ID、导出所有会话

### Step 2: 执行导出脚本

根据用户选择，执行对应命令：

```bash
# 列出当前项目所有会话
python ~/.claude/skills/session-export/main.py --list --project-dir "$(pwd)"

# 导出最近的会话（默认）
python ~/.claude/skills/session-export/main.py --project-dir "$(pwd)"

# 导出指定会话
python ~/.claude/skills/session-export/main.py --session-id <id前缀> --project-dir "$(pwd)"

# 导出所有会话
python ~/.claude/skills/session-export/main.py --all --project-dir "$(pwd)"
```

注意：`--project-dir` 必须传当前项目的实际工作目录（`$(pwd)` 或绝对路径）。

### Step 3: 告知用户结果

输出文件位于 `<项目目录>/session_reports/<日期>_<标题>/`，包含：
- `会话报告.html` — 可视化报告，浏览器直接打开，工具调用可折叠
- `会话原文.txt` — 纯文本格式，适合粘贴到千问等 LLM 做总结和问答

### Step 4: 建议后续操作

如果用户需要智能总结或问答，建议：
1. 打开 `会话原文.txt`
2. 复制内容粘贴到千问网页端（https://tongyi.aliyun.com/qianwen/）
3. 让千问总结核心重点、亮点经验、产出成果，或对内容做问答

## 注意事项

- 脚本从 `~/.claude/projects/` 读取会话 JSONL 数据（只读，不修改原始文件）
- 输出到当前项目目录下的 `session_reports/`，建议在 `.gitignore` 中排除
- HTML 报告为纯静态单文件，零外部依赖
- 当前正在进行的会话也可以导出（截至执行时刻的内容）
