"""wiki/ キーワード検索"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

from .compiler import _parse_concepts_val

log = logging.getLogger(__name__)


@dataclass
class SearchResult:
    path: str    # kb_root からの相対パス（posix形式）
    score: int   # マッチスコア（高いほど上位）
    excerpt: str # マッチ周辺のテキスト（先頭200文字）


def search(kb_root: Path, query: str, json_output: bool = False) -> list[SearchResult]:
    """wiki/ 配下を AND 検索する"""
    words = [w.lower() for w in query.split() if w]
    if not words:
        return []

    search_dirs = [
        kb_root / "wiki" / "summaries",
        kb_root / "wiki" / "concepts",
    ]

    results: list[SearchResult] = []

    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for md_path in search_dir.rglob("*.md"):
            try:
                result = _score_file(md_path, kb_root, words)
            except Exception as e:
                log.warning(f"  検索スキップ {md_path}: {e}")
                continue
            if result is not None:
                results.append(result)

    # score 降順、同スコアはパス昇順
    results.sort(key=lambda r: (-r.score, r.path))

    if json_output:
        data = [{"path": r.path, "score": r.score, "excerpt": r.excerpt} for r in results]
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        for r in results:
            print(f"kb/{r.path} [score: {r.score}]")
            print(f"  > {r.excerpt}")

    return results


def _score_file(md_path: Path, kb_root: Path, words: list[str]) -> SearchResult | None:
    """ファイルをスコアリングして SearchResult を返す。全単語がマッチしない場合は None"""
    # シンボリックリンク経由で kb_root 外を指すパスを安全にスキップ
    try:
        rel_path = md_path.relative_to(kb_root).as_posix()
    except ValueError:
        log.warning(f"  kb_root 外のパスをスキップ: {md_path}")
        return None
    stem_lower = md_path.stem.lower()

    # ファイルを1回だけ読み込む（TOCTOU 防止・I/O 最適化）
    raw_text = md_path.read_text(encoding="utf-8")

    # front matter インラインパース
    fm: dict = {}
    if raw_text.startswith("---"):
        parts = raw_text.split("---", 2)
        if len(parts) >= 3:
            try:
                fm = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                fm = {}
            body = parts[2]
        else:
            body = raw_text
    else:
        body = raw_text

    concepts_val = fm.get("concepts", [])
    concept_names = _parse_concepts_val(concepts_val, md_path)
    concepts_lower = [c.lower() for c in concept_names]
    body_lower = body.lower()

    excerpt = body.lstrip()[:200]

    total_score = 0
    for word in words:
        word_matched = False
        word_score = 0

        # ファイル名（stem）にマッチ: +3
        if word in stem_lower:
            word_score += 3
            word_matched = True

        # concepts にマッチ: +2
        if any(word in c for c in concepts_lower):
            word_score += 2
            word_matched = True

        # 本文にマッチ: +1（単語ごと）
        if word in body_lower:
            word_score += 1
            word_matched = True

        if not word_matched:
            # AND 検索: 1単語でもどこにもマッチしなければ除外
            return None

        total_score += word_score

    return SearchResult(path=rel_path, score=total_score, excerpt=excerpt)
