"""xwiki CLI エントリーポイント"""

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="xwiki",
        description="X Drive → LLM Knowledge Base (Karpathyモデル)",
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    # ingest
    p_ingest = sub.add_parser("ingest", help="ソースファイルを raw/ に変換・取り込む")
    p_ingest.add_argument("source", nargs="?", help="取り込み元ディレクトリ（config.toml の source_path を上書き）")
    p_ingest.add_argument("--config", default="config.toml", help="設定ファイルパス")
    p_ingest.add_argument("--force", action="store_true", help="差分無視で全ファイル再変換")

    # compile
    p_compile = sub.add_parser("compile", help="raw/ を wiki/ に LLM 増分コンパイル")
    p_compile.add_argument("--config", default="config.toml", help="設定ファイルパス")
    p_compile.add_argument("--force", action="store_true", help="差分無視で全ファイル再コンパイル")
    p_compile.add_argument("--dry-run", action="store_true", help="LLM コール数とコストを見積もる（書き込みなし）")

    # search
    p_search = sub.add_parser("search", help="wiki/ をキーワード検索")
    p_search.add_argument("query", help="検索クエリ")
    p_search.add_argument("--config", default="config.toml", help="設定ファイルパス")
    p_search.add_argument("--json", action="store_true", dest="json_output", help="JSON 形式で出力（LLM ツール用）")

    # lint
    p_lint = sub.add_parser("lint", help="wiki/ の品質ヘルスチェック")
    p_lint.add_argument("--config", default="config.toml", help="設定ファイルパス")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    from pathlib import Path
    from .config import load_config

    config_path = Path(getattr(args, "config", "config.toml"))
    config = load_config(config_path if config_path.exists() else None)

    if args.command == "ingest":
        from .ingest import ingest
        source = Path(args.source) if args.source else config.source_path
        ingest(source.resolve(), config.kb_root.resolve(), config, force=args.force)

    elif args.command == "compile":
        from .compiler import compile
        compile(config.kb_root.resolve(), config, force=args.force, dry_run=args.dry_run)

    elif args.command == "search":
        from .search import search
        search(config.kb_root.resolve(), args.query, config, json_output=args.json_output)

    elif args.command == "lint":
        from .linter import lint
        lint(config.kb_root.resolve(), config)


if __name__ == "__main__":
    main()
