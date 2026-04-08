# xwiki

Karpathy の二層 LLM Knowledge Base アーキテクチャを実装した Python CLI。
ファイルを Markdown に変換して `raw/` に蓄積し、LLM で整理した `wiki/` を Obsidian ナレッジベースとして生成する。

```
X Drive ──[ingest]──> raw/ ──[compile]──> wiki/ ──[search/lint]──> ユーザー / LLM エージェント
```

## インストール

```bash
pip install anthropic          # LLM API（compile に必要）
pip install docling            # PDF 変換（高品質レイアウト解析）
pip install markitdown         # Word / PowerPoint / Excel 変換
# LibreOffice は旧形式（.doc/.ppt/.xls）の変換に必要（任意）
```

API キーを設定:

```bash
export ANTHROPIC_API_KEY=sk-...
```

## 使い方

### 1. Ingest — ファイルを raw/ に取り込む

```bash
python -m xwiki ingest <ソースディレクトリ> <KBルート>

# 例
python -m xwiki ingest D:/docs ./kb

# 強制再取り込み（変更なしでも全ファイル処理）
python -m xwiki ingest D:/docs ./kb --force

# 設定ファイルを指定
python -m xwiki ingest D:/docs ./kb --config config.toml
```

対応フォーマット: PDF / DOCX / PPTX / XLSX / DOC / PPT / XLS（テキストファイルはそのまま）

### 2. Compile — raw/ を LLM で wiki/ に変換

```bash
python -m xwiki compile <KBルート>

# まずドライランで確認（LLM を呼ばず対象ファイルだけ表示）
python -m xwiki compile ./kb --dry-run

# 強制再コンパイル（変更なしでも全ファイル処理）
python -m xwiki compile ./kb --force

# 設定ファイルを指定
python -m xwiki compile ./kb --config config.toml
```

以下の4条件のいずれかが変化した場合のみ再コンパイルが走る:

| 条件 | 内容 |
|------|------|
| `content_hash` | ファイルの内容が変わった |
| `prompt_hash` | プロンプトテンプレートが変わった |
| `model_id` | 使用モデルが変わった |
| `compiler_schema_version` | スキーマバージョンが変わった |

### 3. Search — wiki/ を AND 検索

```bash
python -m xwiki search "機械学習 損失関数" ./kb

# JSON 形式で出力（LLM エージェントや jq で使う場合）
python -m xwiki search "機械学習" ./kb --json
```

スコアリング: ファイル名マッチ +3 / concepts マッチ +2 / 本文マッチ +1（AND 検索）

### 4. Lint — wiki/ の品質チェック

```bash
python -m xwiki lint ./kb
```

チェック内容:
- 孤立 summary（concepts からリンクされていない記事）
- 壊れたリンク（`[[wikilink]]` のリンク先が存在しない）
- concepts が空の summary

結果は `wiki/_health/report.md` にも出力される。

## 設定ファイル（config.toml）

`config.toml` をコピーして編集:

```toml
[ingest]
source_path = "X:/"
kb_root = "C:/kb"
exclude_patterns = ["*.tmp", "~$*", ".DS_Store"]
max_file_size_mb = 100

[convert]
libreoffice_path = ""  # 空文字 = PATH から自動検索

[convert.routes]
pdf  = "docling"
docx = "markitdown"
pptx = "markitdown"
xlsx = "markitdown"
doc  = "libreoffice->docx->markitdown"
ppt  = "libreoffice->pptx->markitdown"
xls  = "libreoffice->xlsx->markitdown"

[compile]
llm_model = "claude-sonnet-4-6"
llm_max_tokens = 8000
chunk_size_tokens = 0  # 大きなファイルは 4000 程度に設定
```

## KB ディレクトリ構成

```
kb/
├── raw/                  ← ingest が生成（Markdown 変換済み）
│   └── wiki/
│       └── *.md
├── wiki/                 ← compile が生成（LLM 整理済み）
│   ├── summaries/        ← 要約記事（YAML front matter 付き）
│   ├── concepts/         ← 概念記事（[[wikilink]] 付き）
│   ├── INDEX.md          ← 自動生成インデックス
│   ├── log.md            ← 実行ログ（時系列追記）
│   └── _health/
│       └── report.md     ← lint レポート
└── _meta/
    └── AGENTS.md         ← AI エージェント向けスキーマ説明
```

## 典型的なワークフロー

```bash
# 初回セットアップ
python -m xwiki ingest D:/docs ./kb --config config.toml
python -m xwiki compile ./kb --config config.toml

# 定期更新（差分のみ処理される）
python -m xwiki ingest D:/docs ./kb
python -m xwiki compile ./kb

# 品質確認
python -m xwiki lint ./kb
python -m xwiki search "調べたいキーワード" ./kb
```
