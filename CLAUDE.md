# AIクリエイター — プロジェクト設計書

> **現在のソースコード場所**: `stages/03_development/manga_creator/`（読み取り専用移行期間中）  
> **正式移行先（予定）**: `dev/products/ai-creator/`  
> **Antigravity起動スクリプト**: `~/Desktop/▶️ Antigravity 起動スイッチ/▶️ AI Creator Studio起動.command`  
> **稼働確認URL**: http://localhost:5173（Frontend）/ http://localhost:5001（Backend API）

---

## 1. プロダクト概要

**AIクリエイター**は Gemini × Imagen × NotebookLM × Claude × Remotion を統合した、
ローカル稼働のオールインワンAIコンテンツ制作ツール。

### 3つのメインツール

| ツール | 説明 | 主要AI |
|-------|------|--------|
| 🎨 AI漫画クリエイター | Q&A形式でオリジナル漫画を自動生成 | Claude API + Imagen 4 |
| 📊 AIスライドクリエイター | テーマ入力 → プロ品質のプレゼン資料 | Gemini 2.5 Flash + NotebookLM |
| 🖼 AIデザインクリエイター | PDF解析・SVGエディター・LP生成・動画生成 | Gemini 2.5 Flash + Imagen 4 |

---

## 2. 技術スタック

### バックエンド（port:5001）
```
Flask + Python 3.12
├── anthropic          — Claude API (claude-sonnet-4-6) テキスト生成
├── google-genai       — Imagen 4 (imagen-4.0-generate-001) 画像生成
├── google-generativeai — Gemini 2.5 Flash テキスト/マルチモーダル
├── PyMuPDF (fitz)     — PDFラスタライズ・テキスト抽出
├── Pillow             — 画像合成・コマ割り処理
└── nlm CLI            — NotebookLM操作 (subprocess)
```

### フロントエンド（port:5173 via Vite）
```
Vite 6 + Vanilla JS (index.html + main.js + style.css)
├── React 19 + Remotion 4  — 動画プレビュー (src/RemotionEditor.jsx)
├── @supabase/supabase-js  — 認証 + デザイン保存
├── jspdf                  — PDF出力
└── jszip                  — ZIPエクスポート
```

### 外部サービス
| サービス | 用途 | 認証 |
|---------|------|------|
| Anthropic Claude API | 漫画ストーリー生成 | `CLAUDE_API_KEY` 環境変数 |
| Google Gemini/Imagen API | 画像生成・スタイル解析・デザイン生成 | `GEMINI_API_KEY` 環境変数 |
| NotebookLM (nlm CLI) | スライド自動生成 | `nlm login` 事前認証 |
| Supabase | ユーザー認証・デザイン永続化 | `SUPABASE_URL` / `SUPABASE_ANON_KEY` |

---

## 3. ファイル構成（現ソース）

```
stages/03_development/manga_creator/
├── app.py              — Flaskバックエンド（1928行）全APIエンドポイント
├── main.js             — フロントエンドロジック（3074行）
├── index.html          — SPA エントリーポイント（スクリーン切替ベース）
├── style.css           — 全UIスタイル
├── vite.config.js      — Vite設定（プロキシ: /api → :5001）
├── package.json        — JS依存関係
├── requirements.txt    — Python依存関係
├── src/
│   └── RemotionEditor.jsx  — 動画プレビューコンポーネント（React）
├── user_templates/     — ユーザー保存テンプレートJSON（ローカル永続化）
└── dist/               — ビルド成果物
```

---

## 4. APIエンドポイント全覧

### 🎌 AI漫画クリエイター

| メソッド | エンドポイント | 説明 |
|--------|-------------|------|
| POST | `/api/story` | ストーリー＆キャラクター設定生成（Claude） |
| POST | `/api/panels` | コマ割り・ネーム構成JSON生成（Claude） |
| POST | `/api/generate-image` | コマ画像1枚生成（Imagen 4） |
| POST | `/api/compose-image` | 全コマ合成→漫画ページ画像（Pillow） |
| POST | `/api/prompts-only` | プロンプトのみ生成（画像なし） |
| POST | `/api/export-notebooklm` | 漫画をNotebookLMノートブックへエクスポート |
| POST | `/api/nlm-query` | NotebookLMノートブックへの質問 |
| GET  | `/health` | ヘルスチェック |

### 📊 AIスライドクリエイター

| メソッド | エンドポイント | 説明 |
|--------|-------------|------|
| POST | `/api/slide/analyze-brand` | ブランド解析（URL/テキスト → スタイル抽出） |
| POST | `/api/slide/create` | NotebookLMでスライド生成開始（非同期） |
| POST | `/api/slide/status` | 生成ステータスポーリング |
| POST | `/api/slide/revise` | スライド修正リクエスト |
| POST | `/api/slide/download` | スライドダウンロード（PDF/PPTX） |

### 🖼 AIデザインクリエイター

| メソッド | エンドポイント | 説明 |
|--------|-------------|------|
| POST | `/api/analyze-style` | 画像のスタイル解析（Gemini Vision → JSON） |
| POST | `/api/analyze-design-style` | デザイン詳細解析（色・フォント・ムード） |
| POST | `/api/generate-design` | スタイル指示 → SVG要素レイアウト生成 |
| POST | `/api/generate-landing-page` | LP情報 → SVGレイアウト生成（6セクション） |
| POST | `/api/generate-video` | プロンプト → Remotion動画シーン構成JSON |
| POST | `/api/convert-pdf` | PDF → 画像配列（ページごとbase64） |
| POST | `/api/transform-image` | 画像 + プロンプト → AI変換 |
| POST | `/api/ai-layout` | テキスト指示 → レイアウト提案 |

### 📁 テンプレート管理

| メソッド | エンドポイント | 説明 |
|--------|-------------|------|
| GET  | `/api/templates` | テンプレート一覧取得 |
| POST | `/api/templates` | テンプレート保存 |
| GET  | `/api/templates/<id>` | テンプレート詳細取得 |
| DELETE | `/api/templates/<id>` | テンプレート削除 |

---

## 5. 主要データフロー

### AI漫画クリエイター（Q&Aモード）
```
ユーザーQ&A回答
  → /api/story  → Claude API → ストーリー/キャラクターJSON
  → /api/panels → Claude API → コマ割り構成JSON（panel配列）
  → /api/generate-image × N → Imagen 4 → 各コマ画像base64
  → /api/compose-image → Pillow → 完成漫画ページPNG
  → /api/export-notebooklm → nlm CLI → NotebookLMスライド
```

### AIスライドクリエイター
```
テーマ入力 + スタイル選択
  → /api/slide/create → nlm CLI → notebookId返却
  → /api/slide/status (polling) → 完了待機
  → /api/slide/download → ファイルダウンロード
```

### AIデザインクリエイター（LP生成モード）
```
プロダクト情報入力
  → /api/generate-landing-page → Gemini 2.5 Flash → SVG要素JSON
  → フロントエンドSVGレンダリング（ドラッグ編集可能）
  → jspdf → PDF出力
```

---

## 6. スライドスタイル一覧

app.py `SLIDE_STYLES` で定義された7スタイル：

| スタイル名 | 説明 |
|-----------|------|
| コンサル/エグゼクティブ | McKinseyスタイル、ピラミッド原則 |
| ピッチデッキ | VCピッチ向け高コントラスト |
| 学術/リサーチ | データ駆動、学術会議スタイル |
| モダンニュースペーパー | Swiss Bauhaus哲学、非対称レイアウト |
| マンガスタイル | 日本漫画デザイン、白黒 |
| サイバーパンク/ネオン | ダーク背景、ネオングロー |
| ウォーターカラー | 水彩タッチ、優雅なデザイン |

---

## 7. LPカラーテーマ一覧

`/api/generate-landing-page` で使用可能な5テーマ：

| テーマ | 背景 | アクセント | 雰囲気 |
|-------|------|---------|-------|
| professional | `#0D1B2A` | `#00A8E8` | テック/企業 |
| vibrant | `#0F1219` | `#00F0FF` | サイバー/モダン |
| clean | `#FFFFFF` | `#6C63FF` | ミニマル/SaaS |
| bold | `#0A0A0A` | `#FFD600` | インパクト |
| natural | `#F9F6F0` | `#4A7C59` | オーガニック |

---

## 8. 著作権ガードレール

`COPYRIGHT_NG_WORDS` で既知の著作権侵害リスクワードをブロック：
- 対象: 鳥山明、尾田栄一郎、ワンピース、ナルト、ドラゴンボール、鬼滅の刃 など
- 動作: 含まれる場合は400エラーを返す
- UIにも常時警告バナーを表示

---

## 9. 開発環境セットアップ

```bash
# バックエンド起動
cd ~/Claude/stages/03_development/manga_creator
source venv/bin/activate  # または python3 -m venv venv && pip install -r requirements.txt
export CLAUDE_API_KEY="..."
export GEMINI_API_KEY="..."
python app.py  # → port:5001

# フロントエンド起動（別ターミナル）
cd ~/Claude/stages/03_development/manga_creator
npm install
npm run dev   # → port:5173（Vite dev server、/api → :5001 にプロキシ）

# Antigravityから起動（推奨）
open ~/Desktop/🌌\ Antigravity\ Apps.html
# → "AI Creator Studio" カードをクリック
```

---

## 10. 既知の課題・技術的負債

| 優先度 | 課題 | 影響 |
|-------|------|------|
| 🔴 高 | `stages/` に配置（本来は `dev/products/ai-creator/` に移行すべき） | 構造違反 |
| 🔴 高 | `main.js` 3074行の巨大ファイル（分割が必要） | 保守性低下 |
| 🔴 高 | `app.py` 1928行（Blueprint分割が必要） | 保守性低下 |
| 🟡 中 | Vanilla JSで管理（Vue3/Reactへの移行検討） | 開発速度 |
| 🟡 中 | Supabase設定がハードコード気味（環境変数化） | セキュリティ |
| 🟡 中 | 動画生成のRemotionプレビューのみ（エクスポート未実装） | 機能不足 |
| 🟢 低 | テスト未実装 | 品質 |

---

## 11. 次の開発タスク（優先順）

### P1: ソース移行
- [ ] `stages/03_development/manga_creator/` → `dev/products/ai-creator/` にコピー
- [ ] `.claude/settings.json` で `/trust-project` 実行
- [ ] 起動スクリプトのパスを更新

### P2: 動画エクスポート完成
- [ ] Remotion動画のMP4エクスポート機能
- [ ] `@remotion/renderer` でサーバーサイドレンダリング
- [ ] `/api/export-video` エンドポイント追加

### P3: バックエンド分割（Flask Blueprint）
```
app.py → 
├── routers/manga.py    (story, panels, generate-image, compose-image)
├── routers/slide.py    (slide/* endpoints)
├── routers/design.py   (analyze-style, generate-design, generate-lp, generate-video)
└── routers/templates.py
```

### P4: フロントエンドVue3移行
- [ ] `main.js` → Vue3 + Composition API
- [ ] 各ツールを独立コンポーネントに分割
- [ ] Pinia でステート管理

### P5: 新機能追加候補
- [ ] **AIコピーライター**: プロンプト → SNS/広告コピー生成
- [ ] **AI名刺デザイナー**: 情報入力 → 名刺SVG生成
- [ ] **AI動画スクリプト**: YouTube/Reels用構成案生成

---

## 12. Antigravity登録情報

```python
# antigravity_launcher.py の登録エントリ
'creator-studio': {
    'name': 'AI Creator Studio',
    'command': '~/Desktop/▶️ Antigravity 起動スイッチ/▶️ AI Creator Studio起動.command',
    'check_port': 5173,
    'url': 'http://localhost:5173',
}
```

起動スクリプト内容（`▶️ AI Creator Studio起動.command`）：
```bash
cd "/Users/jungosakamoto/Claude/stages/03_development/manga_creator"
lsof -ti :5001 | xargs kill -9 2>/dev/null
lsof -ti :5173 | xargs kill -9 2>/dev/null
open "http://localhost:5173"
python3 app.py &
npm run dev
```

**ソース移行後は起動スクリプトのパスを `dev/products/ai-creator/` に更新すること。**

---

## 13. 環境変数チェックリスト

```bash
CLAUDE_API_KEY      # Anthropic API（漫画ストーリー生成）
GEMINI_API_KEY      # Google Gemini/Imagen（画像生成・スタイル解析）
SUPABASE_URL        # Supabase URL（デザイン保存）
SUPABASE_ANON_KEY   # Supabase匿名キー（認証）
# nlm login は事前に実行しておく（NotebookLMスライド使用時）
```
