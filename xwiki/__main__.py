"""xwiki CLI エントリーポイント"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

try:
    from . import __version__
except ImportError:
    __version__ = "0.0.0"

from .config import load_config


def main() -> None:
    """CLIエントリーポイント。サブコマンドを解析して対応するモジュールに委譲する。"""
    parser = argparse.ArgumentParser(
        prog="xwiki",
        description="LLM Knowledge Base CLI",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"xwiki {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # ingest サブコマンド
    p_ingest = subparsers.add_parser("ingest", help="ファイルをraw/レイヤーに取り込む")
    p_ingest.add_argument("source", nargs="?", help="取り込み元ディレクトリ")
    p_ingest.add_argument("kb", nargs="?", help="KBルートディレクトリ")
    p_ingest.add_argument("--config", default=None, help="設定ファイルパス（TOML）")
    p_ingest.add_argument("--force", action="store_true", help="増分判定を無視して全ファイル再処理")

    # compile サブコマンド
    p_compile = subparsers.add_parser("compile", help="raw/をLLMでwiki/にコンパイル")
    p_compile.add_argument("kb", nargs="?", help="KBルートディレクトリ")
    p_compile.add_argument("--config", default=None, help="設定ファイルパス（TOML）")
    p_compile.add_argument("--force", action="store_true", help="増分判定を無視して全ファイル再コンパイル")
    p_compile.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="LLMコール数を事前表示して実行しない",
    )

    # search サブコマンド
    p_search = subparsers.add_parser("search", help="wiki/を検索")
    p_search.add_argument("query", help="検索クエリ")
    p_search.add_argument("kb", nargs="?", help="KBルートディレクトリ")
    p_search.add_argument("--config", default=None, help="設定ファイルパス（TOML）")
    p_search.add_argument("--json", action="store_true", help="JSON形式で出力（LLMツール用）")

    # lint サブコマンド
    p_lint = subparsers.add_parser("lint", help="wikiのヘルスチェック")
    p_lint.add_argument("kb", nargs="?", help="KBルートディレクトリ")
    p_lint.add_argument("--config", default=None, help="設定ファイルパス（TOML）")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    # config 読み込み
    config_path: Path | None = Path(args.config) if args.config else None
    config = load_config(config_path)

    # CLI引数でconfig値を上書き
    if hasattr(args, "source") and args.source:
        config.source_path = Path(args.source)
    if hasattr(args, "kb") and args.kb:
        config.kb_root = Path(args.kb)

    # サブコマンド実行
    if args.command == "ingest":
        from .ingest import ingest
        ingest(config.source_path, config.kb_root, config, force=args.force)

    elif args.command == "compile":
        from .compiler import compile as compile_kb
        compile_kb(config.kb_root, config, force=args.force, dry_run=args.dry_run)

    elif args.command == "search":
        from .search import search
        search(config.kb_root, args.query, json_output=args.json)

    elif args.command == "lint":
        from .linter import lint
        lint(config.kb_root, client=None)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
