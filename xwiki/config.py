"""設定ファイル読み込みと Config dataclass"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    # ソース
    source_path: Path = Path(".")
    # KB 出力先
    kb_root: Path = Path("./kb")
    # クローリング
    exclude_patterns: list[str] = field(default_factory=lambda: [
        "~$*", "*.tmp", "$RECYCLE.BIN", ".git", "__pycache__", "Thumbs.db", ".DS_Store"
    ])
    max_file_size_mb: int = 100
    # 変換
    ocr_enabled: bool = False
    chunk_size_tokens: int = 0  # 0 = 無効
    # LLM
    llm_provider: str = "anthropic"
    llm_model: str = "claude-sonnet-4-6"
    llm_max_tokens: int = 8000
    # Wiki 生成
    generate_summaries: bool = True
    generate_concepts: bool = True


def load_config(path: Path | None = None) -> Config:
    """TOML ファイルから Config を読み込む。ファイルが存在しない場合はデフォルト値を返す。"""
    if path is None or not path.exists():
        return Config()

    try:
        import tomllib  # Python 3.11+
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]

    raw = tomllib.loads(path.read_text(encoding="utf-8"))

    source = raw.get("source", {})
    output = raw.get("output", {})
    convert = raw.get("convert", {})
    llm = raw.get("llm", {})
    wiki = raw.get("wiki", {})

    return Config(
        source_path=Path(source.get("path", ".")),
        kb_root=Path(output.get("kb_root", "./kb")),
        exclude_patterns=source.get("exclude_patterns", Config().exclude_patterns),
        max_file_size_mb=source.get("max_file_size_mb", 100),
        ocr_enabled=convert.get("ocr_enabled", False),
        chunk_size_tokens=convert.get("chunk_size_tokens", 0),
        llm_provider=llm.get("provider", "anthropic"),
        llm_model=llm.get("model", "claude-sonnet-4-6"),
        llm_max_tokens=llm.get("max_tokens", 8000),
        generate_summaries=wiki.get("generate_summaries", True),
        generate_concepts=wiki.get("generate_concepts", True),
    )
