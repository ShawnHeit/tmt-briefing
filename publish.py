#!/usr/bin/env python3
"""
TMT Briefing 公开发布脚本

做的事情：
1. 从源目录读取 tmt-briefing.html
2. 扫描 HTML 里引用的所有 ../知识库/...{pdf,html,md} 路径
   （包括 href="..."、JSON "href": "..." 等多种写法）
3. 把 HTML 复制到 ./index.html，并把 ../知识库/ 替换成 知识库/
4. 把被引用的资源（PDF / audit HTML / md）复制到 ./知识库/ 对应位置
5. 复制过来的 audit HTML 自动改写"返回简报"链接，使其在 GitHub Pages 下能跳回 index.html
6. 删除本仓库里不再被引用的"陈旧"资源
7. git add . && git commit && git push

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
SOURCE_BOT_ROOT = Path("/Users/heyicheng/Documents/TMT_Bot/Bot")

PUBLIC_DIR = Path(__file__).resolve().parent
PUBLIC_HTML = PUBLIC_DIR / "index.html"
PUBLIC_KB_ROOT = PUBLIC_DIR / "知识库"

ASSET_EXTS = (".pdf", ".html", ".md")


def extract_referenced_assets(html_text: str) -> set[str]:
    """抽出所有 ../知识库/...{pdf,html,md} 引用，返回 URL 解码后的相对路径集合。

    覆盖以下写法：
      - href="../知识库/..."     （HTML 标签）
      - href="../%E7%9F%A5%E8%AF%86%E5%BA%93/..."  （URL 编码）
      - "href": "../知识库/..."  （JSON 数据，audit 卡片用这个）
      - "pdf_path": "../知识库/..." / "../%E7%9F%A5..."（JSON 数据）
      - "path": "../知识库/..."
      - src="../知识库/..."
    """
    raw_kb = "知识库"
    enc_kb = "%E7%9F%A5%E8%AF%86%E5%BA%93"

    ext_alt = "(?:" + "|".join(re.escape(e) for e in ASSET_EXTS) + ")"
    kb_alt = f"(?:{re.escape(raw_kb)}|{re.escape(enc_kb)})"

    patterns = [
        rf'href\s*=\s*"(\.\./{kb_alt}/[^"]+?{ext_alt})"',
        rf'src\s*=\s*"(\.\./{kb_alt}/[^"]+?{ext_alt})"',
        rf'"(?:href|pdf_path|md_path|path|file)"\s*:\s*"(\.\./[^"]+?{ext_alt})"',
    ]

    paths: set[str] = set()
    for pat in patterns:
        for m in re.findall(pat, html_text, flags=re.IGNORECASE):
            decoded = unquote(m)
            if "/知识库/" not in decoded:
                continue
            paths.add(decoded)
    return paths


def rewrite_main_html(html_text: str) -> str:
    """主页 HTML：把 ../知识库/ 改成 知识库/（含 URL 编码版本）。"""
    out = html_text
    out = out.replace("../知识库/", "知识库/")
    out = out.replace("../%E7%9F%A5%E8%AF%86%E5%BA%93/", "%E7%9F%A5%E8%AF%86%E5%BA%93/")
    return out


def rewrite_audit_html(html_text: str) -> str:
    """audit 子页面 HTML：把"返回简报"链接重写成相对于公开仓库的 index.html。

    源 audit HTML 在 Bot/知识库/{公司}/audits/ 下，其返回链接形如:
        ../../../tmt-briefing/tmt-briefing.html#audit
    在公开仓库里 audit HTML 在 知识库/{公司}/audits/ 下，主页是 ../../../index.html。
    """
    out = html_text
    out = out.replace(
        "../../../tmt-briefing/tmt-briefing.html",
        "../../../index.html",
    )
    out = out.replace(
        "../../../tmt-briefing/tmt-briefing.html#audit",
        "../../../index.html#audit",
    )
    return out


def sync_assets(referenced: set[str]) -> tuple[int, int, int]:
    """把引用到的资源（PDF / audit HTML / md）复制到 PUBLIC_KB_ROOT，
    并清理本仓库里不再被引用的旧文件。"""
    PUBLIC_KB_ROOT.mkdir(parents=True, exist_ok=True)

    copied = 0
    missing = 0
    pruned = 0

    wanted_public_paths: set[Path] = set()

    for ref in sorted(referenced):
        rel = ref.removeprefix("../")  # "知识库/.../xxx.pdf"
        src = SOURCE_BOT_ROOT / rel
        dst = PUBLIC_DIR / rel
        wanted_public_paths.add(dst.resolve())

        if not src.exists():
            print(f"  ⚠️  缺失（HTML 引用了但本地找不到）: {rel}")
            missing += 1
            continue

        dst.parent.mkdir(parents=True, exist_ok=True)

        if dst.suffix.lower() == ".html":
            text = src.read_text(encoding="utf-8", errors="ignore")
            new_text = rewrite_audit_html(text)
            need_write = (
                not dst.exists()
                or dst.read_text(encoding="utf-8", errors="ignore") != new_text
            )
            if need_write:
                dst.write_text(new_text, encoding="utf-8")
                copied += 1
        else:
            if dst.exists() and dst.stat().st_size == src.stat().st_size:
                continue
            shutil.copy2(src, dst)
            copied += 1

    if PUBLIC_KB_ROOT.exists():
        for existing in PUBLIC_KB_ROOT.rglob("*"):
            if existing.is_file() and existing.suffix.lower() in ASSET_EXTS:
                if existing.resolve() not in wanted_public_paths:
                    print(
                        f"  🗑️  清理不再引用的: {existing.relative_to(PUBLIC_DIR)}"
                    )
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

    referenced = extract_referenced_assets(html_text)
    by_ext: dict[str, int] = {}
    for r in referenced:
        ext = Path(r).suffix.lower()
        by_ext[ext] = by_ext.get(ext, 0) + 1
    summary = ", ".join(f"{c} 个 {ext}" for ext, c in sorted(by_ext.items()))
    print(f"🔎 HTML 引用了 {len(referenced)} 个资源（{summary}）")

    new_html = rewrite_main_html(html_text)
    PUBLIC_HTML.write_text(new_html, encoding="utf-8")
    print(f"📝 已写入: {PUBLIC_HTML}")

    print("📦 同步资源文件...")
    copied, missing, pruned = sync_assets(referenced)
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
