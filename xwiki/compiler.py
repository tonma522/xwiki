"""wiki/ レイヤー: LLM による増分コンパイル"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .config import Config
from .state import Manifest, sha256

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------

SUMMARY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "overview": {"type": "string"},
        "key_points": {
            "type": "array",
            "items": {"type": "string"},
        },
        "concepts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["name", "description"],
            },
        },
    },
    "required": ["overview", "key_points", "concepts"],
}

COMPILER_SCHEMA_VERSION = "1"

# NOTE: SUMMARY_SCHEMA を変更したら COMPILER_SCHEMA_VERSION も必ずインクリメントすること

# prompt_hash の計算に使う代表的なユーザープロンプトテンプレート（変更時に再コンパイルが走る）
SUMMARY_USER_PROMPT_TEMPLATE = "以下のドキュメントを要約してください。\n\n{text}"

SUMMARY_SYSTEM_PROMPT = (
    "あなたは技術ドキュメントの要約専門家です。\n"
    "提供されたドキュメントを読み、指定されたスキーマに従って JSON で要約を出力してください。\n"
    "- overview: 3文以内の概要\n"
    "- key_points: 箇条書き最大5項目\n"
    "- concepts: 登場する重要な固有名詞・概念（最大10個、name と description のペア）"
)

CONCEPT_SYSTEM_PROMPT = (
    "あなたは技術 wiki の編集者です。\n"
    "提供された複数のサマリーを参照して、指定された概念について Obsidian 互換の概念記事を生成してください。\n"
    "関連するサマリーへの [[wikilink]] を含めてください。"
)

AGENTS_DOC_CONTENT = """\
# xwiki KB — エージェント指示書

このファイルを読んでいる LLM エージェントへ:
あなたは汎用チャットボットではなく、このナレッジベースの **規律ある wiki 保守者** です。

## KB 構造

- `raw/`: 機械変換された元ドキュメント（編集禁止）
- `wiki/summaries/`: LLM が生成したサマリー（各 raw/ ファイルに対応）
- `wiki/concepts/`: 概念記事（複数のサマリーを横断する重要概念）
- `wiki/INDEX.md`: 自動生成のカタログ（編集禁止）
- `wiki/log.md`: コンパイル作業の時系列ログ

## 編集ルール

1. **raw/ は編集しない**。元ドキュメントの変更は `xwiki ingest` で行う
2. **[[wikilink]] の正規化**: 概念名は表記ゆれなく統一する（例: 「AI」と「人工知能」は別概念として扱う）
3. **サマリーの構造**: `concepts:` front matter に登場概念を列挙する
4. **概念記事のリンク**: 必ず関連するサマリーへの `[[wikilink]]` を含める
5. **INDEX.md / log.md は直接編集しない**: `xwiki compile` が自動更新する

## クエリの扱い方

- 特定のドキュメントを探す → `xwiki search "キーワード"`
- wiki 全体の健全性チェック → `xwiki lint`
- 新しいドキュメントを取り込む → `xwiki ingest [source]`
"""


# ---------------------------------------------------------------------------
# ヘルパー関数
# ---------------------------------------------------------------------------

def _safe_concept_filename(name: str) -> str:
    """概念名からパストラバーサルに使われる文字を除去してファイル名に安全な文字列を返す"""
    sanitized = re.sub(r'[/\\<>:"|?*\x00-\x1f]', '_', name)
    sanitized = sanitized.replace('..', '__')
    return sanitized.strip('._') or "_unnamed"


def _parse_concepts_val(concepts_val: Any, md_path: Path) -> list[str]:
    """front matter の concepts フィールドから概念名リストを返す"""
    names: list[str] = []
    if isinstance(concepts_val, str):
        # YAML が "[A, B]" のような文字列として返した場合
        for name in concepts_val.strip("[]").split(","):
            name = name.strip()
            if name:
                names.append(name)
    elif isinstance(concepts_val, list):
        for item in concepts_val:
            if isinstance(item, str):
                name = item.strip()  # strip("[],") は不要—YAML がリストで返すので既にクリーン
                if name:
                    names.append(name)
            elif isinstance(item, dict):
                name = str(item.get("name", "")).strip()
                if name:
                    names.append(name)
    return names


def _parse_front_matter(md_path: Path) -> dict[str, Any]:
    """Markdown の YAML front matter を dict で返す。失敗時は空 dict"""
    text = md_path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        return yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return {}


def _split_text_into_chunks(text: str, chunk_size_tokens: int) -> list[str]:
    """テキストを chunk_size_tokens 単位で行境界で分割する"""
    lines = text.splitlines(keepends=True)
    chunks: list[str] = []
    current_chunk_lines: list[str] = []
    current_tokens = 0

    for line in lines:
        line_tokens = len(line) // 4
        if current_tokens + line_tokens > chunk_size_tokens and current_chunk_lines:
            chunks.append("".join(current_chunk_lines))
            current_chunk_lines = [line]
            current_tokens = line_tokens
        else:
            current_chunk_lines.append(line)
            current_tokens += line_tokens

    if current_chunk_lines:
        chunks.append("".join(current_chunk_lines))

    return chunks


def _summary_to_markdown(
    summary: dict[str, Any],
    raw_rel_path: str,
    filename: str,
    model_id: str,
) -> str:
    """サマリー dict を Markdown 文字列に整形する"""
    overview: str = summary.get("overview", "")
    key_points: list[str] = summary.get("key_points", [])
    concepts: list[dict[str, str]] = summary.get("concepts", [])

    concept_names = [c.get("name", "") for c in concepts if c.get("name")]
    generated = datetime.now().isoformat()

    concept_names_str = "[" + ", ".join(concept_names) + "]"

    lines: list[str] = []
    lines.append("---")
    lines.append(f'source_raw: "{raw_rel_path}"')
    lines.append(f'summary_of: "{filename}"')
    lines.append(f"concepts: {concept_names_str}")
    lines.append(f'generated: "{generated}"')
    lines.append(f'model: "{model_id}"')
    lines.append("---")
    lines.append("")
    lines.append("## 概要")
    lines.append("")
    lines.append(overview)
    lines.append("")
    lines.append("## キーポイント")
    lines.append("")
    for kp in key_points:
        lines.append(f"- {kp}")
    lines.append("")
    lines.append("## 登場する概念")
    lines.append("")
    for concept in concepts:
        name = concept.get("name", "")
        desc = concept.get("description", "")
        lines.append(f"- **{name}**: {desc}")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# パブリック関数
# ---------------------------------------------------------------------------

def compile_summary(
    raw_md_path: Path,
    client: Any,
    config: Config,
    raw_rel_path: str = "",
) -> str:
    """raw MD ファイルを読み込み、LLM でサマリーを生成し、Markdown 文字列を返す"""
    text = raw_md_path.read_text(encoding="utf-8")
    # 日本語は UTF-8 で 3バイト/文字が多いため bytes 長で近似
    rough_tokens = len(text.encode("utf-8")) // 4

    fallback: dict[str, Any] = {"overview": "", "key_points": [], "concepts": []}

    try:
        if config.chunk_size_tokens > 0 and rough_tokens > config.chunk_size_tokens:
            # 階層要約: チャンク分割 → partial summaries → synthesis
            chunks = _split_text_into_chunks(text, config.chunk_size_tokens)
            partial_summaries: list[dict[str, Any]] = []
            for i, chunk in enumerate(chunks):
                chunk_prompt = (
                    f"以下のドキュメントの一部（チャンク {i + 1}/{len(chunks)}）を要約してください。\n\n"
                    f"{chunk}"
                )
                try:
                    partial = client.complete_json(chunk_prompt, SUMMARY_SYSTEM_PROMPT, SUMMARY_SCHEMA)
                    partial_summaries.append(partial)
                except Exception as e:
                    log.warning(f"    チャンク {i + 1} の要約失敗: {e}")
                    partial_summaries.append(fallback.copy())

            partials_json = json.dumps(partial_summaries, ensure_ascii=False, indent=2)
            synthesis_prompt = (
                "以下は同じドキュメントを分割して要約したものです。\n"
                "これらを統合して、ドキュメント全体の最終的な要約を生成してください。\n\n"
                f"{partials_json}"
            )
            summary = client.complete_json(synthesis_prompt, SUMMARY_SYSTEM_PROMPT, SUMMARY_SCHEMA)
        else:
            # 分割なし: 全テキストを一度に処理
            prompt = SUMMARY_USER_PROMPT_TEMPLATE.format(text=text)
            summary = client.complete_json(prompt, SUMMARY_SYSTEM_PROMPT, SUMMARY_SCHEMA)

    except Exception as e:
        log.error(f"    サマリー LLM エラー: {e}")
        summary = fallback

    if not raw_rel_path:
        raw_rel_path = raw_md_path.name
    return _summary_to_markdown(summary, raw_rel_path, raw_md_path.name, client.model)


def gather_concepts(kb_root: Path) -> dict[str, list[Path]]:
    """wiki/summaries/ の全 MD から concepts を収集する"""
    summaries_root = kb_root / "wiki" / "summaries"
    if not summaries_root.exists():
        return {}

    concept_map: dict[str, list[Path]] = {}
    for md_path in summaries_root.rglob("*.md"):
        try:
            fm = _parse_front_matter(md_path)
        except Exception as e:
            log.warning(f"    front matter parse 失敗 {md_path}: {e}")
            continue

        concepts_val = fm.get("concepts", [])
        for name in _parse_concepts_val(concepts_val, md_path):
            concept_map.setdefault(name, []).append(md_path)

    return concept_map


def compile_concept_article(concept: str, summaries: list[Path], client: Any) -> str:
    """概念記事を生成して文字列で返す"""
    summary_lines: list[str] = []
    for i, summary_path in enumerate(summaries, 1):
        try:
            text = summary_path.read_text(encoding="utf-8")
            excerpt = text[:500]
        except Exception:
            excerpt = f"（読み込み失敗: {summary_path.name}）"
        summary_lines.append(f"{i}. {summary_path.stem}\n{excerpt}")

    summaries_block = "\n\n".join(summary_lines)
    user_prompt = (
        f"概念名: {concept}\n\n"
        f"関連するサマリー:\n{summaries_block}"
    )

    try:
        article = client.complete(user_prompt, CONCEPT_SYSTEM_PROMPT)
    except Exception as e:
        log.error(f"    概念記事生成エラー ({concept}): {e}")
        article = f"# {concept}\n\n（生成失敗）\n"

    # [[wikilink]] が含まれない場合は末尾に追加
    if "[[" not in article:
        related_links = "\n".join(f"- [[{p.stem}]]" for p in summaries)
        article = article.rstrip() + f"\n\n## 関連ドキュメント\n{related_links}\n"

    return article


def update_index(kb_root: Path) -> None:
    """wiki/INDEX.md を機械生成する（LLM 不使用）"""
    summaries_root = kb_root / "wiki" / "summaries"
    concepts_root = kb_root / "wiki" / "concepts"
    index_path = kb_root / "wiki" / "INDEX.md"

    now = datetime.now().isoformat()

    # summaries 収集
    summary_files = sorted(summaries_root.rglob("*.md")) if summaries_root.exists() else []
    # concepts ファイル収集
    concept_files = sorted(concepts_root.rglob("*.md")) if concepts_root.exists() else []

    # 概念ごとに登場するサマリー数
    concept_summary_counts: dict[str, int] = {}
    for cf in concept_files:
        concept_summary_counts[cf.stem] = 0

    # summary → concepts マッピング & 概念登場カウント
    summary_concept_map: dict[str, list[str]] = {}
    orphan_summaries: list[Path] = []

    for sf in summary_files:
        try:
            fm = _parse_front_matter(sf)
        except Exception:
            fm = {}

        raw_stem = sf.stem
        concepts_val = fm.get("concepts", [])
        concept_names: list[str] = _parse_concepts_val(concepts_val, sf)

        summary_concept_map[raw_stem] = concept_names

        if not concept_names:
            orphan_summaries.append(sf)

        for cname in concept_names:
            if cname in concept_summary_counts:
                concept_summary_counts[cname] += 1

    lines: list[str] = []
    lines.append("# Knowledge Base Index")
    lines.append(f"_自動生成: {now}_")
    lines.append("")
    lines.append(f"## Summaries ({len(summary_files)} 件)")
    lines.append("")
    lines.append("| ファイル | 概念 |")
    lines.append("|------|------|")
    for sf in summary_files:
        stem = sf.stem
        concept_names_for_sf = summary_concept_map.get(stem, [])
        concepts_cell = ", ".join(concept_names_for_sf) if concept_names_for_sf else ""
        lines.append(f"| [[raw/{stem}]] | {concepts_cell} |")
    lines.append("")
    lines.append(f"## Concepts ({len(concept_files)} 件)")
    lines.append("")
    for cf in concept_files:
        count = concept_summary_counts.get(cf.stem, 0)
        lines.append(f"- [[concepts/{cf.stem}]] — 登場するsummary数: {count}")
    lines.append("")
    lines.append("## 孤立ファイル（Concepts なし）")
    lines.append("")
    for sf in orphan_summaries:
        lines.append(f"- [[raw/{sf.stem}]]")
    lines.append("")

    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text("\n".join(lines), encoding="utf-8")
    log.info(f"  INDEX.md 更新: {index_path.relative_to(kb_root)}")


def update_log(
    kb_root: Path,
    new_count: int,
    updated_count: int,
    skipped_count: int,
    model_id: str,
    prompt_hash: str,
) -> None:
    """wiki/log.md に追記する"""
    log_path = kb_root / "wiki" / "log.md"
    now = datetime.now().isoformat()

    entry_lines = [
        f"## {now}",
        f"- compiled: {new_count + updated_count} files ({new_count} new, {updated_count} updated, {skipped_count} skipped)",
        f"- model: {model_id}",
        f"- prompt_hash: {prompt_hash[:12]}",
        "",
    ]
    entry = "\n".join(entry_lines)

    log_path.parent.mkdir(parents=True, exist_ok=True)
    if log_path.exists():
        existing = log_path.read_text(encoding="utf-8")
        log_path.write_text(existing + "\n" + entry, encoding="utf-8")
    else:
        log_path.write_text("# Compile Log\n\n" + entry, encoding="utf-8")

    log.info(f"  log.md 更新: {log_path.relative_to(kb_root)}")


def init_agents_doc(kb_root: Path) -> None:
    """kb/_meta/AGENTS.md を初回のみ生成する（上書き禁止）"""
    agents_path = kb_root / "_meta" / "AGENTS.md"
    if agents_path.exists():
        return
    agents_path.parent.mkdir(parents=True, exist_ok=True)
    agents_path.write_text(AGENTS_DOC_CONTENT, encoding="utf-8")
    log.info(f"  AGENTS.md 生成: {agents_path.relative_to(kb_root)}")


def compile(
    kb_root: Path,
    config: Config,
    force: bool = False,
    dry_run: bool = False,
) -> None:
    """raw/ の MD を LLM で wiki/ に増分コンパイルする"""
    from .llm import LLMClient

    client = LLMClient(model=config.llm_model, max_tokens=config.llm_max_tokens)

    manifest_path = kb_root / "_meta" / "manifest.json"
    manifest = Manifest.load(manifest_path)

    # 1. AGENTS.md 初期生成（初回のみ）
    init_agents_doc(kb_root)

    # 2. サマリー生成
    raw_root = kb_root / "raw"
    summaries_root = kb_root / "wiki" / "summaries"

    # 現在の prompt_hash を計算（system + user テンプレートを組み合わせて変更を検知）
    current_prompt_hash = client.prompt_hash(SUMMARY_USER_PROMPT_TEMPLATE, SUMMARY_SYSTEM_PROMPT)

    raw_files = list(raw_root.rglob("*.md")) if raw_root.exists() else []

    new_count = updated_count = skipped_count = 0

    if dry_run:
        to_compile = [
            f for f in raw_files
            if force or manifest.is_changed_for_compile(
                f.relative_to(kb_root).as_posix(),
                sha256(f),
                current_prompt_hash,
                config.llm_model,
                COMPILER_SCHEMA_VERSION,
            )
        ]
        log.info(f"[dry-run] コンパイル対象: {len(to_compile)} / {len(raw_files)} ファイル")
        return

    try:
        for raw_path in raw_files:
            raw_rel = raw_path.relative_to(kb_root).as_posix()
            current_hash = sha256(raw_path)

            if not force and not manifest.is_changed_for_compile(
                raw_rel, current_hash, current_prompt_hash, config.llm_model, COMPILER_SCHEMA_VERSION
            ):
                log.info(f"  [スキップ] {raw_path.name}")
                skipped_count += 1
                continue

            is_new = (
                manifest.sources.get(raw_rel) is None
                or manifest.sources[raw_rel].status != "compiled"
            )

            try:
                summary_md = compile_summary(raw_path, client, config, raw_rel_path=raw_rel)

                # 出力パス: wiki/summaries/{raw/ 以降のパス}
                rel_from_raw = raw_path.relative_to(raw_root)
                summary_path = summaries_root / rel_from_raw
                summary_path.parent.mkdir(parents=True, exist_ok=True)
                summary_path.write_text(summary_md, encoding="utf-8")

                manifest.mark_compiled(
                    raw_rel,
                    prompt_hash=current_prompt_hash,
                    model_id=config.llm_model,
                    schema_version=COMPILER_SCHEMA_VERSION,
                )

                if is_new:
                    new_count += 1
                else:
                    updated_count += 1

                log.info(f"  完了 -> {summary_path.relative_to(kb_root)}")

            except Exception as e:
                log.error(f"  サマリー生成エラー {raw_path.name}: {e}")
    finally:
        manifest.save(manifest_path)

    # 3. 概念収集 → 概念記事生成
    if config.generate_concepts:
        concept_map = gather_concepts(kb_root)
        concepts_root = kb_root / "wiki" / "concepts"
        concepts_root.mkdir(parents=True, exist_ok=True)

        for concept, summary_paths in concept_map.items():
            concept_path = concepts_root / f"{_safe_concept_filename(concept)}.md"
            if not force and concept_path.exists():
                continue
            try:
                article = compile_concept_article(concept, summary_paths, client)
                concept_path.write_text(article, encoding="utf-8")
                log.info(f"  概念記事: {concept}.md")
            except Exception as e:
                log.error(f"  概念記事生成エラー {concept}: {e}")

    # 4. INDEX 更新（機械生成）
    update_index(kb_root)

    # 5. log.md 追記
    update_log(kb_root, new_count, updated_count, skipped_count, config.llm_model, current_prompt_hash)

    log.info(f"[完了] {new_count}件新規, {updated_count}件更新, {skipped_count}件スキップ")
