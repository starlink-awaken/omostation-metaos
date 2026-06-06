"""SSOT 映射自动扫描——从文件头部元数据生成映射表"""

import os
import re
import sys
from pathlib import Path


def scan_ssot(base_dir: str = ".") -> list[dict]:
    """扫描所有 .md 文件，提取 SSOT 位置声明，生成映射表"""
    entries = []
    base = Path(base_dir).resolve()

    for md_file in sorted(base.rglob("*.md")):
        rel = md_file.relative_to(base)
        fname = str(rel)

        # INDEX.md 导航页不需要 SSOT 声明
        if fname.endswith("INDEX.md"):
            entries.append(
                {
                    "file": fname,
                    "ssot": "",
                    "type": "index_nav",
                }
            )
            continue

        content = md_file.read_text(encoding="utf-8")

        # 从文件头部提取 SSOT 位置声明
        m = re.search(r"> \*\*SSOT 位置：\*\*\s*`([^`]+)`", content)
        if m:
            ssot_ref = m.group(1)
            entries.append(
                {
                    "file": fname,
                    "ssot": ssot_ref,
                    "type": "definition",
                }
            )
        else:
            entries.append(
                {
                    "file": fname,
                    "ssot": "",
                    "type": "reference",
                }
            )

    return entries


def format_markdown_table(entries: list[dict]) -> str:
    """生成可替换到 SSOT 映射文件的 Markdown 表格"""
    lines = [
        "| 文件 | SSOT 位置 | 类型 |",
        "|------|-----------|------|",
    ]
    has_ssot = [e for e in entries if e["ssot"]]
    no_ssot = [e for e in entries if not e["ssot"]]

    for e in has_ssot:
        lines.append(f"| `{e['file']}` | `{e['ssot']}` | ✅ 定义 |")
    for e in no_ssot:
        lines.append(f"| `{e['file']}` | — | ℹ️ {e['type']} |")

    return "\n".join(lines)


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else "."
    print(f"扫描目录: {os.path.abspath(base)}")

    entries = scan_ssot(base)
    has = sum(1 for e in entries if e["ssot"])
    no = len(entries) - has

    print(f"\n总计: {len(entries)} 文件")
    print(f"  有 SSOT: {has}")
    print(f"  无 SSOT: {no}")

    print("\n--- 映射表 ---")
    print(format_markdown_table(entries))

    # 输出缺失文件清单（仅 definition/reference 类型，排除 INDEX）
    missing = [e for e in entries if not e["ssot"] and e["type"] != "index_nav"]
    if missing:
        print(f"\n⚠️  以下 {len(missing)} 个文件应声明 SSOT 位置但未找到:")
        for e in missing:
            print(f"  - {e['file']}")

    return 0 if no <= 3 else 1  # INDEX 和红队文件通常是 2-3 个


if __name__ == "__main__":
    sys.exit(main())
