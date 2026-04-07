"""wiki/ キーワード検索 CLI（stub）"""

from __future__ import annotations

import logging
from pathlib import Path

from .config import Config

log = logging.getLogger(__name__)


def search(kb_root: Path, query: str, config: Config, json_output: bool = False) -> None:
    """wiki/ 配下を AND 検索する（未実装）"""
    # TODO: Phase 3 Task 3.1 で実装
    log.info("[stub] search は未実装です（Phase 3 で実装予定）")
