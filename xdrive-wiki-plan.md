# Plan: X Drive → LLM Knowledge Base（Karpathyモデル）
**生成日**: 2026-04-07 / **レーン: Standard** / **推定複雑度**: 中〜高

## 概要

Andrej Karpathyが提唱するLLM Knowledge Baseアーキテクチャを採用する。
単なるファイル変換ミラーではなく、**LLMが能動的に編纂する二層構造のwiki**を構築する。

```
X Drive
  ↓ markitdown変換（機械的）
raw/        ← 元データの忠実なMD変換。LLMが読む素材
  ↓ LLM編纂（知的）
wiki/       ← LLMが書く概念記事・要約・バックリンク。人間とLLMが共に読む
  ↓ ツール群
tools/      ← 検索CLI・Q&Aエージェント・ヘルスチェック
```

**哲学（File over App）**:
- すべてのデータはMarkdown + 画像という普遍的フォーマット
- Obsidianで閲覧可能な構造
- AIプロバイダーに依存しない（BYOAI）
- wikiは明示的・検査可能・ポータブル

## スコープ

In:
- `raw/` レイヤー: markitdownによる機械変換（既存 `crawler.py` を発展）
- `wiki/` レイヤー: LLMによる増分コンパイル（概念記事・要約・バックリンク）
- Obsidian互換出力（YAML front matter、`[[wikilink]]` 形式）
- 増分コンパイル（変更されたraw/ファイルのみwikiを更新）
- 基本的な検索CLI（wiki全体をキーワード検索）
- LLMヘルスチェック（矛盾検出・欠損補完候補）

Out:
- GUIフロントエンド
- クラウドストレージ連携
- ファインチューニング（Karpathyが「さらなる探索」として言及）
- RAGパイプライン構築（小規模では不要とKarpathyが指摘）

## 前提条件

- Python 3.14、markitdown 0.1.5 インストール済み
- LLM API（Claude/OpenAI等）のAPIキーが利用可能（wiki編纂用）
- Obsidianがインストールされている（閲覧用、必須ではない）
- Xドライブへの読み取りアクセス確保済み

## 仮定

- LLMはClaude APIを使用（`ANTHROPIC_API_KEY` 環境変数で注入）
- wiki/ のファイル数が〜数百件規模ではRAGは不要（Karpathyの知見に従う）
- OCRはデフォルト無効（スキャンPDFが多いと判明したら後から追加）
- Obsidianの `[[wikilink]]` 形式をバックリンク標準とする
- LLMへのコンテキスト渡しはraw/のMDファイルを直接読み込む方式

## 調査サマリー

- **Fact**: `crawler.py:95-164` — 既存crawl処理はraw/レイヤーとして転用可能
- **Fact**: markitdown `convert()` が全フォーマット統一窓口
- **Fact**: Karpathyモデルの二層構造: `raw/`（機械変換）+ `wiki/`（LLM編纂）
- **Evidence**: PDFテスト成功。raw/レイヤーの基本動作は確認済み
- **Why it matters**: raw/だけでは「ファイルミラー」に留まる。wiki/レイヤーがあって初めて知識ベースになる
- **Uncertainty**: LLMのコンテキスト長制限（大量のraw/ファイルを一度に処理できない）→ 増分処理で対応

---

## ディレクトリ構造（最終形）

```
kb/                          ← Knowledge Base ルート（Obsidianのvault）
├── raw/                     ← 機械変換層（LLMの素材）
│   └── [Xドライブ構造を反映]
│       └── 営業部/
│           └── 提案書_A社.md
├── wiki/                    ← LLM編纂層（知識ベース本体）
│   ├── INDEX.md             ← 全体目次（LLMが管理）
│   ├── concepts/            ← 概念記事（LLMが生成）
│   │   ├── 製品A.md
│   │   └── プロジェクトX.md
│   ├── summaries/           ← ドキュメント要約（raw/との1:1対応）
│   │   └── 提案書_A社.md
│   └── _health/             ← ヘルスチェック結果
│       └── report.md
├── tools/                   ← CLIツール群
│   └── search.py
└── _meta/                   ← 管理ファイル（変換状態・設定）
    ├── state.json
    └── compile_log.md
```

---

## Phase 1: raw/ レイヤー整備

**目的**: `crawler.py` をモジュール化し、`raw/` レイヤーを堅牢化する  
**検証**: `python -m xwiki ingest <source>` で raw/ にMDファイルが生成される

### Task 1.1: パッケージ構成の確立

- **対象**: `C:/dev/schedule/xwiki/` パッケージを新設
- **内容**: 以下のモジュール構成に分割
  ```
  xwiki/
  ├── __init__.py
  ├── __main__.py       # エントリーポイント (ingest / compile / search / lint)
  ├── config.py         # Config dataclass + TOML読み込み
  ├── ingest.py         # raw/レイヤー（旧 crawler.py）
  ├── converter.py      # markitdown呼び出し・Obsidian互換メタヘッダー
  ├── compiler.py       # wiki/レイヤー（LLM編纂）← Phase 2で実装
  ├── search.py         # 検索CLI ← Phase 3で実装
  └── state.py          # 差分管理（md5）
  ```
- **依存**: なし
- **受け入れ条件**: `python -m xwiki ingest IHI kb/` が動作し、`kb/raw/` にMDが生成される
- **検証**: 旧 `crawler.py` と同等の出力が `kb/raw/` に生成されること

### Task 1.2: 設定ファイル（TOML）

- **対象**: `xwiki/config.py`、`config.toml`
- **内容**:
  ```toml
  [source]
  path = "X:/"
  exclude_patterns = ["~$*", "*.tmp", "$RECYCLE.BIN", ".git"]
  max_file_size_mb = 100

  [output]
  kb_root = "./kb"

  [convert]
  ocr_enabled = false
  chunk_size_tokens = 0    # 0=無効

  [llm]
  provider = "anthropic"   # anthropic | openai
  model = "claude-sonnet-4-6"
  max_tokens_per_call = 8000

  [wiki]
  generate_concepts = true
  generate_summaries = true
  generate_crosslinks = true
  ```
- **依存**: Task 1.1
- **受け入れ条件**: `--config config.toml` で全設定が反映される
- **検証**: 設定ファイルなしでもデフォルト値で動作する

### Task 1.3: Obsidian互換メタヘッダーへの変更

- **対象**: `xwiki/converter.py`
- **内容**: YAML front matterをObsidian標準に合わせる
  ```yaml
  ---
  source: "X:/営業部/提案書_A社.xlsx"
  tags: [raw, excel]
  created: 2026-04-07T14:38:00
  modified: 2024-03-15T09:00:00
  ---
  ```
  - `tags` フィールドにファイル形式タグを追加
  - `aliases` フィールド（ファイル名の別名）を追加
- **依存**: Task 1.1
- **受け入れ条件**: 生成されたMDがObsidianで正常にレンダリングされる
- **検証**: Obsidianでvaultを開きfront matterが認識されること

---

## Phase 2: wiki/ レイヤー（LLM編纂）

**目的**: LLMがraw/を読んでwiki/を自律的に編纂する増分コンパイラを実装する  
**検証**: `python -m xwiki compile` でwiki/に概念記事・要約・バックリンクが生成される

### Task 2.1: 増分コンパイラの基本実装

- **対象**: `xwiki/compiler.py`
- **内容**: LLMを使ってraw/の各MDファイルから `wiki/summaries/` に要約を生成
  - コンパイル済みファイルは state.json で追跡（md5で増分判定）
  - 1ファイル = 1 LLM call（トークン節約）
  - プロンプト構造:
    ```
    以下のドキュメントを読んで要約を生成してください。
    出力形式: Obsidian互換のMarkdown（YAML front matter + 本文）
    含めるもの: 概要・キーポイント・登場する重要概念リスト
    ```
  - 生成されるfront matter:
    ```yaml
    ---
    source_raw: "raw/営業部/提案書_A社.md"
    summary_of: "提案書_A社.xlsx"
    concepts: [製品A, プロジェクトX, A社]
    generated: 2026-04-07T15:00:00
    ---
    ```
- **依存**: Task 1.2（LLM設定）
- **受け入れ条件**: raw/の各ファイルに対応するsummaryがwiki/summaries/に生成される
- **検証**: 要約MD内に `concepts:` リストが存在し、内容が元ファイルと対応している

### Task 2.2: 概念記事生成

- **対象**: `xwiki/compiler.py` に `generate_concepts()` を追加
- **内容**: summaries/ の `concepts:` リストを集約し、概念ごとの記事を生成
  - 全summaryの `concepts:` を収集 → 頻出概念リストを構築
  - 概念ごとにLLMが記事を生成: 定義・登場するドキュメント一覧・関連概念
  - `[[wikilink]]` 形式でsummaries/や他の概念記事へリンク
  ```markdown
  # 製品A

  ## 概要
  ...

  ## 関連ドキュメント
  - [[提案書_A社]] — 提案内容の詳細
  - [[仕様書_v2]] — 技術仕様

  ## 関連概念
  - [[プロジェクトX]]
  - [[A社]]
  ```
- **依存**: Task 2.1
- **受け入れ条件**: `wiki/concepts/` に概念記事が生成され、`[[リンク]]` が存在する
- **検証**: Obsidianのグラフビューで概念間リンクが可視化されること

### Task 2.3: INDEX.md の LLM管理

- **対象**: `xwiki/compiler.py` に `update_index()` を追加
- **内容**: LLMがwiki/全体を把握したINDEX.mdを生成・更新
  - 概念記事一覧
  - 最近更新されたsummary一覧
  - 未リンクの孤立ドキュメント一覧（ヘルスチェック用）
  - Karpathyが指摘する「brief summaries of all documents」をINDEXに含める
- **依存**: Task 2.2
- **受け入れ条件**: INDEX.mdがwiki/の全体像を反映している
- **検証**: INDEX.mdのリンクが全て有効なファイルを指していること

---

## Phase 3: ツール群とヘルスチェック

**目的**: LLMがwikiを操作するためのCLIツールを整備し、wiki品質を維持する  
**検証**: `python -m xwiki search <query>` と `python -m xwiki lint` が動作する

### Task 3.1: 検索CLI

- **対象**: `xwiki/search.py`
- **内容**: wiki/全体に対するキーワード検索ツール
  - `python -m xwiki search "製品A 提案"` → 関連ファイル一覧を出力
  - 出力形式: ファイルパス + マッチした行 + スコア
  - LLMエージェントがツールとして呼び出せるよう、JSON出力モードも用意
  - `--json` フラグでJSON出力（Claude Toolsとの統合用）
- **依存**: Phase 2完了
- **受け入れ条件**: クエリに対して関連ファイルが返される。`--json` で機械可読な出力
- **検証**: 既知のキーワードで検索し、期待するファイルが上位に来ること

### Task 3.2: LLMヘルスチェック

- **対象**: `xwiki/compiler.py` に `lint_wiki()` を追加
- **内容**: Karpathyが言う「LLM health checks」の実装
  - 矛盾検出: 同じ概念について異なる説明がある箇所を発見
  - 孤立ファイル検出: バックリンクがゼロのファイルを列挙
  - 欠損概念候補: summaries/ に頻出するが概念記事がない語句
  - 新記事候補: 興味深い接続点の提案
  - 出力: `wiki/_health/report.md`
- **依存**: Task 2.3
- **受け入れ条件**: `python -m xwiki lint` でヘルスチェックレポートが生成される
- **検証**: 既知の孤立ファイルがレポートに含まれること

---

## テスト戦略

- **テスト姿勢**: verification-first
- **例外理由**: LLM出力は非決定的。内容の正しさより「構造と形式の正しさ」を検証
- **検証対象**:
  1. `raw/` 生成: ファイル数・拡張子・front matterの存在
  2. `wiki/summaries/` 生成: concepts: フィールドの存在・リンクの有効性
  3. `wiki/concepts/` 生成: `[[wikilink]]` の存在・対応ファイルの実在
  4. 増分動作: 2回目の `compile` が変更ファイルのみ再処理すること
- **実行コマンド**:
  ```bash
  python -m xwiki ingest <source> [--config config.toml]
  python -m xwiki compile [--config config.toml]
  python -m xwiki search <query> [--json]
  python -m xwiki lint
  ```

## リスクと対策

| リスク | 影響 | 対策 |
|--------|------|------|
| LLMコール数が多くコスト増大 | API費用が予測困難 | 増分処理で変更ファイルのみ処理。`--dry-run` で事前見積もり |
| LLMが不正確な概念を生成 | wikiの情報品質低下 | ヘルスチェックで定期的に人間がレビュー。raw/が常に真実の源 |
| 概念名の表記ゆれ（製品A vs 製品-A） | 重複概念記事が生成される | LLMプロンプトで正規化を指示。ヘルスチェックで検出 |
| コンテキスト長超過 | 大きなraw/ファイルを処理できない | チャンク分割（Task 1.2の `chunk_size_tokens`）で対応 |
| LLM APIが利用不可 | wiki/レイヤーが生成できない | raw/レイヤーは独立して動作。wiki/はオプション扱い |

## ロールバック計画

- `raw/` と `wiki/` は独立。`wiki/` を削除して再生成可能（冪等）
- `_meta/state.json` を削除すれば全ファイルを再変換・再編纂できる
- ソースXドライブは読み取り専用。元データは常に安全
- `wiki/` 全体をgit管理することでLLM編纂の履歴を追跡可能
