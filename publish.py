#!/usr/bin/env python3
"""
TMT Briefing 公开发布脚本

做的事情：
1. 从源目录读取 tmt-briefing.html
2. 扫描 HTML 里引用的所有 ../知识库/...pdf 路径
3. 把 HTML 复制到 ./index.html，并把 ../知识库/ 替换成 知识库/
4. 把被引用的 PDF 复制到 ./知识库/ 对应位置（保留目录层级）
5. 删除本仓库里不再被引用的"陈旧" PDF
6. git add . && git commit && git push

使用：
    python3 publish.py             # 仅同步内容，不 push
    python3 publish.py --push      # 同步内容 + 自动 commit & push
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

SOURCE_HTML = Path(
    "/Users/heyicheng/Documents/TMT_Bot/Bot/tmt-briefing/tmt-briefing.html"
)
SOURCE_KB_ROOT = Path("/Users/heyicheng/Documents/TMT_Bot/Bot/知识库")

PUBLIC_DIR = Path(__file__).resolve().parent
PUBLIC_HTML = PUBLIC_DIR / "index.html"
PUBLIC_KB_ROOT = PUBLIC_DIR / "知识库"


def extract_referenced_pdfs(html_text: str) -> set[str]:
    """从 HTML 抽出所有 ../知识库/...pdf 引用，返回 URL 解码后的相对路径集合。"""
    patterns = [
        r'href="(\.\./知识库/[^"]+\.pdf)"',
        r'href="(\.\./%E7%9F%A5%E8%AF%86%E5%BA%93/[^"]+\.pdf)"',
        r'"pdf_path"\s*:\s*"(\.\./[^"]+\.pdf)"',
        r'"path"\s*:\s*"(\.\./知识库/[^"]+\.pdf)"',
    ]
    paths: set[str] = set()
    for pat in patterns:
        for m in re.findall(pat, html_text):
            paths.add(unquote(m))
    return paths


def rewrite_html_paths(html_text: str) -> str:
    """把 ../知识库/ 改成 知识库/（含 URL 编码版本）。"""
    out = html_text
    out = out.replace("../知识库/", "知识库/")
    out = out.replace("../%E7%9F%A5%E8%AF%86%E5%BA%93/", "%E7%9F%A5%E8%AF%86%E5%BA%93/")
    return out


def sync_pdfs(referenced: set[str]) -> tuple[int, int, int]:
    """把引用到的 PDF 复制到 PUBLIC_KB_ROOT，并清理不再被引用的旧 PDF。"""
    PUBLIC_KB_ROOT.mkdir(parents=True, exist_ok=True)

    copied = 0
    missing = 0
    pruned = 0

    wanted_public_paths: set[Path] = set()

    for ref in sorted(referenced):
        rel = ref.removeprefix("../")
        src = PUBLIC_DIR.parent.parent / "Documents" / "TMT_Bot" / "Bot" / rel
        # 上面 PUBLIC_DIR 是 ~/Documents/tmt-briefing-public，所以 .parent.parent 是 ~/
        # 实际我们用绝对路径更稳：
        src = Path("/Users/heyicheng/Documents/TMT_Bot/Bot") / rel
        dst = PUBLIC_DIR / rel  # rel 是 "知识库/AI算力/..."
        wanted_public_paths.add(dst.resolve())

        if not src.exists():
            print(f"  ⚠️  缺失（HTML 引用了但本地找不到）: {rel}")
            missing += 1
            continue

        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists() and dst.stat().st_size == src.stat().st_size:
            continue
        shutil.copy2(src, dst)
        copied += 1

    if PUBLIC_KB_ROOT.exists():
        for existing in PUBLIC_KB_ROOT.rglob("*.pdf"):
            if existing.resolve() not in wanted_public_paths:
                print(f"  🗑️  清理不再引用的: {existing.relative_to(PUBLIC_DIR)}")
                existing.unlink()
                pruned += 1
        for d in sorted(
            (p for p in PUBLIC_KB_ROOT.rglob("*") if p.is_dir()),
            key=lambda p: -len(p.parts),
        ):
            try:
                d.rmdir()
            except OSError:
                pass

    return copied, missing, pruned


def run_git(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=PUBLIC_DIR, check=check, capture_output=True, text=True
    )


def git_commit_and_push() -> None:
    if not (PUBLIC_DIR / ".git").exists():
        print("⚠️  还没 git init，先跳过 push。请按 README 的指引初始化后再来。")
        return

    run_git(["add", "."])
    status = run_git(["status", "--porcelain"]).stdout.strip()
    if not status:
        print("📭 没有变更，跳过 commit。")
        return

    msg = f"Update briefing {datetime.now():%Y-%m-%d %H:%M}"
    run_git(["commit", "-m", msg])
    print(f"✅ 已提交: {msg}")

    push = run_git(["push", "-u", "origin", "main"], check=False)
    if push.returncode == 0:
        print("🚀 已推送到 GitHub")
    else:
        print("❌ push 失败，stderr:")
        print(push.stderr)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--push", action="store_true", help="同步完成后自动 git add/commit/push"
    )
    args = parser.parse_args()

    if not SOURCE_HTML.exists():
        print(f"❌ 源 HTML 不存在: {SOURCE_HTML}")
        return 1

    print(f"📖 读取源 HTML: {SOURCE_HTML}")
    html_text = SOURCE_HTML.read_text(encoding="utf-8")

    referenced = extract_referenced_pdfs(html_text)
    print(f"🔎 HTML 引用了 {len(referenced)} 个 PDF（去重后）")

    new_html = rewrite_html_paths(html_text)
    PUBLIC_HTML.write_text(new_html, encoding="utf-8")
    print(f"📝 已写入: {PUBLIC_HTML}")

    print("📦 同步 PDF 文件...")
    copied, missing, pruned = sync_pdfs(referenced)
    print(
        f"   完成：复制 {copied} 个，缺失 {missing} 个，清理 {pruned} 个旧文件"
    )

    if args.push:
        print("\n🔁 正在 git add/commit/push...")
        git_commit_and_push()
    else:
        print("\n💡 已完成本地同步。要推送到 GitHub 请加 --push")

    return 0


if __name__ == "__main__":
    sys.exit(main())
