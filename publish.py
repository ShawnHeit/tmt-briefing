#!/usr/bin/env python3
"""
TMT Briefing public publish script.

Copies the single-page briefing plus every referenced asset into this clean
GitHub Pages repo. Markdown notes are also mirrored to ASCII `notes/` URLs,
because GitHub Pages can be unreliable serving raw `.md` under Chinese paths.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, unquote

SOURCE_HTML = Path(
    "/Users/heyicheng/Documents/TMT_Bot/Bot/tmt-briefing/tmt-briefing.html"
)
SOURCE_BOT_ROOT = Path("/Users/heyicheng/Documents/TMT_Bot/Bot")

PUBLIC_DIR = Path(__file__).resolve().parent
PUBLIC_HTML = PUBLIC_DIR / "index.html"
PUBLIC_KB_ROOT = PUBLIC_DIR / "知识库"
PUBLIC_NOTES_ROOT = PUBLIC_DIR / "notes"
PUBLIC_DATA_ROOT = PUBLIC_DIR / "data"

ASSET_EXTS = (".pdf", ".html", ".md")


def extract_referenced_assets(html_text: str) -> set[str]:
    """Return decoded local asset paths referenced by the page."""
    ext_alt = "(?:" + "|".join(re.escape(ext) for ext in ASSET_EXTS) + ")"
    kb_alt = r"(?:知识库|%E7%9F%A5%E8%AF%86%E5%BA%93)"
    daily_alt = r"(?:每日汇总|%E6%AF%8F%E6%97%A5%E6%B1%87%E6%80%BB)"
    patterns = [
        rf'href="(\.\./{kb_alt}/[^"]+?{ext_alt})"',
        rf'href="(\.\./{daily_alt}/[^"]+?{ext_alt})"',
        rf'href="(\.\./data/[^"]+?{ext_alt})"',
        rf'"(?:href|pdf_path|md_path|path|file)"\s*:\s*"(\.\./[^"]+?{ext_alt})"',
    ]

    paths: set[str] = set()
    for pattern in patterns:
        for match in re.findall(pattern, html_text, flags=re.IGNORECASE):
            decoded = unquote(match)
            if decoded.startswith(("../知识库/", "../每日汇总/", "../data/")):
                paths.add(decoded)
    return paths


def encoded_rel(rel: str) -> str:
    return "/".join(quote(part) for part in rel.split("/"))


def note_alias_for(rel: str) -> str:
    """Build a stable ASCII path for a markdown note."""
    digest = hashlib.sha1(rel.encode("utf-8")).hexdigest()[:10]
    stem = Path(rel).stem
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-")[:80] or "note"
    return f"notes/{digest}_{slug}.md"


def build_note_aliases(referenced: set[str]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for ref in sorted(referenced):
        rel = ref.removeprefix("../")
        if rel.lower().endswith(".md"):
            aliases[rel] = note_alias_for(rel)
    return aliases


def rewrite_main_html(html_text: str, note_aliases: dict[str, str]) -> str:
    """Rewrite local paths for GitHub Pages."""
    out = html_text
    for rel, alias in note_aliases.items():
        out = out.replace(f"../{rel}", alias)
        out = out.replace(f"../{encoded_rel(rel)}", alias)
    out = out.replace("../知识库/", "知识库/")
    out = out.replace("../%E7%9F%A5%E8%AF%86%E5%BA%93/", "%E7%9F%A5%E8%AF%86%E5%BA%93/")
    out = out.replace("../每日汇总/", "每日汇总/")
    out = out.replace("../%E6%AF%8F%E6%97%A5%E6%B1%87%E6%80%BB/", "%E6%AF%8F%E6%97%A5%E6%B1%87%E6%80%BB/")
    out = out.replace("../data/", "data/")
    return out


def rewrite_audit_html(html_text: str) -> str:
    """Make audit pages link back to the public index."""
    out = html_text
    out = out.replace("../../tmt-briefing/tmt-briefing.html#audit", "../../index.html#audit")
    out = out.replace("../../../tmt-briefing/tmt-briefing.html#audit", "../../../index.html#audit")
    return out


def copy_if_changed(src: Path, dst: Path) -> bool:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and dst.stat().st_size == src.stat().st_size:
        return False
    shutil.copy2(src, dst)
    return True


def sync_assets(
    referenced: set[str], note_aliases: dict[str, str]
) -> tuple[int, int, int]:
    copied = 0
    missing = 0
    pruned = 0
    wanted_public_paths: set[Path] = set()
    wanted_note_paths: set[Path] = set()

    for ref in sorted(referenced):
        rel = ref.removeprefix("../")
        src = SOURCE_BOT_ROOT / rel
        dst = PUBLIC_DIR / rel
        wanted_public_paths.add(dst.resolve())

        if not src.exists():
            print(f"  ⚠️  缺失（HTML 引用了但本地找不到）: {rel}")
            missing += 1
            continue

        if dst.suffix.lower() == ".html":
            text = src.read_text(encoding="utf-8", errors="ignore")
            new_text = rewrite_audit_html(text)
            dst.parent.mkdir(parents=True, exist_ok=True)
            if not dst.exists() or dst.read_text(encoding="utf-8", errors="ignore") != new_text:
                dst.write_text(new_text, encoding="utf-8")
                copied += 1
        else:
            if copy_if_changed(src, dst):
                copied += 1

        alias = note_aliases.get(rel)
        if alias:
            note_dst = PUBLIC_DIR / alias
            wanted_note_paths.add(note_dst.resolve())
            if copy_if_changed(src, note_dst):
                copied += 1

    if PUBLIC_KB_ROOT.exists():
        for existing in PUBLIC_KB_ROOT.rglob("*"):
            if existing.is_file() and existing.suffix.lower() in ASSET_EXTS:
                if existing.resolve() not in wanted_public_paths:
                    print(f"  🗑️  清理不再引用的: {existing.relative_to(PUBLIC_DIR)}")
                    existing.unlink()
                    pruned += 1

    if PUBLIC_NOTES_ROOT.exists():
        for existing in PUBLIC_NOTES_ROOT.rglob("*.md"):
            if existing.resolve() not in wanted_note_paths:
                print(f"  🗑️  清理不再引用的: {existing.relative_to(PUBLIC_DIR)}")
                existing.unlink()
                pruned += 1

    for root in (PUBLIC_KB_ROOT, PUBLIC_NOTES_ROOT, PUBLIC_DATA_ROOT):
        if not root.exists():
            continue
        for directory in sorted((p for p in root.rglob("*") if p.is_dir()), key=lambda p: -len(p.parts)):
            try:
                directory.rmdir()
            except OSError:
                pass

    return copied, missing, pruned


def run_git(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=PUBLIC_DIR, check=check, capture_output=True, text=True
    )


def git_commit_and_push() -> None:
    if not (PUBLIC_DIR / ".git").exists():
        print("⚠️  还没 git init，先跳过 push。")
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
    parser.add_argument("--push", action="store_true", help="同步完成后自动 git add/commit/push")
    args = parser.parse_args()

    if not SOURCE_HTML.exists():
        print(f"❌ 源 HTML 不存在: {SOURCE_HTML}")
        return 1

    print(f"📖 读取源 HTML: {SOURCE_HTML}")
    html_text = SOURCE_HTML.read_text(encoding="utf-8")
    referenced = extract_referenced_assets(html_text)
    note_aliases = build_note_aliases(referenced)

    counts = {ext: sum(1 for ref in referenced if ref.lower().endswith(ext)) for ext in ASSET_EXTS}
    summary = ", ".join(f"{counts[ext]} 个 {ext}" for ext in ASSET_EXTS)
    print(f"🔎 HTML 引用了 {len(referenced)} 个资源（{summary}；notes mirror {len(note_aliases)} 个）")

    PUBLIC_HTML.write_text(rewrite_main_html(html_text, note_aliases), encoding="utf-8")
    print(f"📝 已写入: {PUBLIC_HTML}")

    print("📦 同步资源文件...")
    copied, missing, pruned = sync_assets(referenced, note_aliases)
    print(f"   完成：复制 {copied} 个，缺失 {missing} 个，清理 {pruned} 个旧文件")

    if args.push:
        print("\n🔁 正在 git add/commit/push...")
        git_commit_and_push()
    else:
        print("\n💡 已完成本地同步。要推送到 GitHub 请加 --push")

    return 0


if __name__ == "__main__":
    sys.exit(main())
