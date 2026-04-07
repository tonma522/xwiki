"""
X Drive Crawler - Phase 1 Prototype
ファイルをクローリングしてMarkdownに変換し、wiki構造で出力する
"""

import os
import sys
import json
import hashlib
import logging
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Optional

from markitdown import MarkItDown

# ===== 設定 =====
SUPPORTED_EXTENSIONS = {".pdf", ".xlsx", ".xls", ".pptx", ".ppt", ".docx", ".doc"}
MAX_FILE_SIZE_MB = 100  # これ以上は処理スキップ

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


# ===== データ構造 =====
@dataclass
class ConvertResult:
    source_path: str
    output_path: str
    status: str  # "ok" | "skip" | "error"
    reason: str = ""
    file_size_bytes: int = 0
    converted_at: str = ""


@dataclass
class CrawlState:
    """差分処理のための状態管理"""
    processed: dict[str, str] = field(default_factory=dict)  # path -> md5

    def save(self, path: Path):
        path.write_text(json.dumps(self.processed, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "CrawlState":
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(processed=data)
        return cls()


# ===== ユーティリティ =====
def file_md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def source_to_output_path(source: Path, source_root: Path, output_root: Path) -> Path:
    """ソースパスをwiki出力パスに変換"""
    relative = source.relative_to(source_root)
    # 拡張子を .md に変換
    output = output_root / "sources" / relative.with_suffix(".md")
    return output


def build_meta_header(source: Path, result_text: str) -> str:
    """LLMフレンドリーなメタデータヘッダーを付与"""
    stat = source.stat()
    header = f"""---
source: {source.as_posix()}
filename: {source.name}
extension: {source.suffix.lower()}
size_bytes: {stat.st_size}
modified: {datetime.fromtimestamp(stat.st_mtime).isoformat()}
converted: {datetime.now().isoformat()}
---

# {source.stem}

"""
    return header + result_text


# ===== メイン処理 =====
def crawl(source_root: Path, output_root: Path, force: bool = False) -> list[ConvertResult]:
    md = MarkItDown()
    state_path = output_root / "_meta" / "state.json"
    state = CrawlState.load(state_path)

    results: list[ConvertResult] = []
    files = [
        p for p in source_root.rglob("*")
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    ]

    log.info(f"対象ファイル数: {len(files)}")

    for i, src in enumerate(files, 1):
        log.info(f"[{i}/{len(files)}] {src.name}")

        # サイズチェック
        size = src.stat().st_size
        if size > MAX_FILE_SIZE_MB * 1024 * 1024:
            log.warning(f"  スキップ（サイズ超過）: {size / 1024 / 1024:.1f} MB")
            results.append(ConvertResult(
                source_path=str(src),
                output_path="",
                status="skip",
                reason=f"size_exceeded:{size}",
                file_size_bytes=size,
            ))
            continue

        # 差分チェック
        src_key = str(src)
        current_hash = file_md5(src)
        if not force and state.processed.get(src_key) == current_hash:
            log.info("  スキップ（変更なし）")
            continue

        # 変換
        out_path = source_to_output_path(src, source_root, output_root)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            result = md.convert(str(src))
            content = build_meta_header(src, result.text_content or "")
            out_path.write_text(content, encoding="utf-8")
            state.processed[src_key] = current_hash

            results.append(ConvertResult(
                source_path=str(src),
                output_path=str(out_path),
                status="ok",
                file_size_bytes=size,
                converted_at=datetime.now().isoformat(),
            ))
            log.info(f"  完了 -> {out_path.relative_to(output_root)}")

        except Exception as e:
            log.error(f"  エラー: {e}")
            results.append(ConvertResult(
                source_path=str(src),
                output_path="",
                status="error",
                reason=str(e),
                file_size_bytes=size,
            ))

    # 状態保存
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state.save(state_path)

    return results


def generate_index(output_root: Path, results: list[ConvertResult]):
    """sources/ 配下の構造からINDEX.mdを生成"""
    sources_dir = output_root / "sources"
    if not sources_dir.exists():
        return

    lines = ["# Wiki Index\n", f"_生成日時: {datetime.now().strftime('%Y-%m-%d %H:%M')}_\n\n"]

    for md_file in sorted(sources_dir.rglob("*.md")):
        rel = md_file.relative_to(output_root)
        depth = len(rel.parts) - 2  # sources/ の分を引く
        indent = "  " * depth
        lines.append(f"{indent}- [{md_file.stem}]({rel.as_posix()})\n")

    (output_root / "INDEX.md").write_text("".join(lines), encoding="utf-8")
    log.info("INDEX.md 生成完了")


def write_report(output_root: Path, results: list[ConvertResult]):
    """変換レポートを出力"""
    ok = [r for r in results if r.status == "ok"]
    skip = [r for r in results if r.status == "skip"]
    error = [r for r in results if r.status == "error"]

    lines = [
        "# 変換レポート\n\n",
        f"- 完了: {len(ok)}\n",
        f"- スキップ: {len(skip)}\n",
        f"- エラー: {len(error)}\n\n",
    ]

    if error:
        lines.append("## エラー一覧\n\n")
        for r in error:
            lines.append(f"- `{r.source_path}`\n  - {r.reason}\n")

    report_path = output_root / "_meta" / "report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("".join(lines), encoding="utf-8")
    log.info(f"レポート: {report_path}")


# ===== エントリーポイント =====
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="X Drive → Wiki MD 変換ツール")
    parser.add_argument("source", help="クローリング対象のルートディレクトリ")
    parser.add_argument("output", help="wiki出力先ディレクトリ")
    parser.add_argument("--force", action="store_true", help="差分無視で全ファイル再変換")
    args = parser.parse_args()

    source_root = Path(args.source).resolve()
    output_root = Path(args.output).resolve()

    if not source_root.exists():
        log.error(f"ソースディレクトリが存在しません: {source_root}")
        sys.exit(1)

    log.info(f"ソース: {source_root}")
    log.info(f"出力先: {output_root}")

    results = crawl(source_root, output_root, force=args.force)
    generate_index(output_root, results)
    write_report(output_root, results)

    ok_count = sum(1 for r in results if r.status == "ok")
    log.info(f"完了: {ok_count}/{len(results)} ファイル変換")
