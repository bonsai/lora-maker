# 研究ワークフロー達成度確認レポート

**評定日**: 2026-10-27
**対象リポジトリ**: `bonsai/lora-maker` (main @ 40f2442)

---

## 1. データの取得

| サブジェクト | 状態 | 詳細 |
|---|---|---|
| **Shishi 動画** | ✅ **完了** | 7本 DL済み (`data/shishi/local-videos/`)。`selected-videos.yml` で承認管理。|
| **Shishi フレーム** | ✅ **完了** | 144枚抽出済み (`data/shishi/images-shishi/`)。全枚に自動キャプション付き (`.txt`)。|
| **Hokusai 画像** | ✅ **完了** | 114枚済み (`data/hokusai/data/images-resized-720/`)。|

**証拠**:
- `data/shishi/local-videos/` — 7動画、合計約71MB
- `data/shishi/images-shishi/` — 144 pairs (`.png` + `.txt`)
- `data/hokusai/data/images-resized-720/` — 114 images

**残タスク**: 今後の追加動画の選定・DL（pipelineは確立済み）

---

## 2. メタデータの構造化と表示

| 層 | 状態 | 詳細 |
|---|---|---|
| **構造化DB** | ✅ **完了** | `data/assets.db` (SQLite) に統合。`projects/frames/videos/vlm_reviews/vlm_scores` 5テーブル + 3View。|
| **Hokusai投入** | ✅ **完了** | 114 frames + 77 VLM reviews投入済み。|
| **Shishi投入** | ✅ **完了** | 7 videos + 144 frames + 144 captions投入済み。|
| **静的ダッシュボード** | ✅ **完了** | `asset-dashboard.html` (52KB standalone) — Video Gallery / Frame Grid / Dataset Table。|
| **動的ダッシュボード** | 🟡 **進行中** | FastAPI+Plotly版の schema + seed スクリプト完了。アプリ本体未実装。|
| **VLMメタ統合** | 🟡 **待ち** | Shishi画像へのVLMレビュー未実行。Hokusaiは済。|

**証拠**:
- `tools/dashboard_api/schema.sql` — 統合スキーマ
- `tools/dashboard_api/seed_db.py` — データ投入スクリプト
- `data/shishi/review/asset-dashboard.html` — file:// で開く静的版

**残タスク**:
- [ ] FastAPIサーバー実装 (`tools/dashboard_api/main.py`)
- [ ] Plotly.js インタラクティブチャート（スコア分布、カテゴリ円グラフ、品質ヒートマップ）
- [ ] Shishi画像にVLMレビュー実行 → DB追記

---

## 3. 重い計算の委託（Kaggle / GPU）

| 項目 | 状態 | 詳細 |
|---|---|---|
| **パイプライン構築** | ✅ **完了** | `tools/kaggle_pipeline.py` — `doctor/build/dataset/train/wait/logs/fetch/run` 全サブコマンド。|
| **kaggle互換trainスクリプト** | ✅ **完了** | `kaggle/train_lora.py` — headless kohya-ss/sd-scripts ランチャー。config埋め込み対応。|
| **認証・承認ゲート** | ✅ **完了** | dataset approval SHA-256検証、`--execute` フラグ、dry-runデフォルト。|
| **実地検証** | 🟡 **検証中** | Version 6 pushed。GPU T4 x2 で学習実行中。360 steps, 10 epochs, dim=32。|
| **成果物取得** | ⬜ **未完了** | `.safetensors` の自動fetch待ち。|

**最終ログ** (2026-10-27 03:11 JST相当):
- Step 24/360 (7%), avr_loss 0.059, ~10s/it
- 推定残り: ~55分

**証拠**:
- `tools/kaggle_pipeline.py` (556行、26 tests passing)
- `kaggle/train_lora.py` — embedded config markers
- Kaggle Running log — 664.8s elapsed @ T4 x2

**残タスク**:
- [ ] Training complete → `fetch` 実行確認
- [ ] LoRA `.safetensors` を `dist/lora/` に配置
- [ ] Generation 用に `comfy-gen-lora` へ転送

---

## 4. 画像生成の自動化とその評価の自動化

| 項目 | 状態 | 詳細 |
|---|---|---|
| **生成環境構築** | ⬜ **未開始** | `comfy-gen-lora` リポジトリは scaffold のみ (README + 空ディレクトリ)。|
| **ComfyUI連携** | ⬜ **未開始** | Kaggle上でのComfyUI headless起動スクリプト未実装。|
| **生成自動化** | ⬜ **未開始** | プロンプトバッチ → 画像生成 → 出力保存のpipeline未設計。|
| **評価自動化** | ⬜ **未開始** | VLMによる生成画像評価（FID/CLIP/VLMスコア）未実装。|

**証拠**:
- `comfy-gen-lora/README.md` — 草案のみ
- `comfy-gen-lora/kaggle/` — 空ディレクトリ

**残タスク** (大きめ):
- [ ] Kaggle ComfyUI kernel 設計（LoRA読み込み + 推論）
- [ ] プロンプトセット管理（Shishi風プロンプトの体系化）
- [ ] 生成画像の自動保存・命名規則
- [ ] VLMによる生成品質評価（Hokusai reviewer の流用検討）

---

## 5. VLM-reviewerの確立

| 項目 | 状態 | 詳細 |
|---|---|---|
| **スキル定義** | ✅ **完了** | `data/hokusai/reviewer/skill.yaml` — pi skill 互換。provider/model/presets 完備。|
| **レビューエンジン** | ✅ **完了** | `vlm_reviewer.py` + `batch_review.py` — LM Studio/OpenAI/Gemini/Ollama 対応。|
| **Hokusai実行** | ✅ **完了** | 252行のjsonl生成済み（内77件が正常パースされDB投入）。114枚中約68%をカバー。|
| **Shishi実行** | ⬜ **未開始** | 144枚へのVLMレビュー未実行。|
| **統合DB連携** | ✅ **完了** | `vlm_reviews` + `vlm_scores` テーブル設計済み。Hokusai分は投入済み。|

**証拠**:
- `data/hokusai/reviewer/` — 8ファイルのスキルパッケージ
- `data/hokusai/data/hokusai_vlm_reviews.jsonl` — 252 records
- `data/assets.db` — `vlm_reviews` 77件（Hokusai）、`vlm_scores` 308 rows（4軸×77）

**注意**: jsonl 252行に対してDB投入は77件。残り175件はJSONパース失敗または重複の可能性。要調査。

**残タスク**:
- [ ] jsonlパース失敗原因調査（構造不正レコードの修正）
- [ ] Shishi 144枚へのVLMレビュー実行（batch_review.py 流用）
- [ ] `training_suitability < 6` の低品質フレーム除外ワークフロー

---

## 総合評定

| # | ワークフロー | 達成度 | ブロッカー | 次のアクション |
|---|------------|--------|-----------|-------------|
| 1 | データの取得 | ✅ 90% | なし | 追加動画があればDL pipeline実行 |
| 2 | メタデータ構造化・表示 | 🟡 70% | FastAPI未実装 | `tools/dashboard_api/main.py` 実装 |
| 3 | 重い計算の委託 | 🟡 75% | 学習完了待ち | Kaggle status確認 → fetch |
| 4 | 生成・評価の自動化 | ⬜ 10% | 未着手 | `comfy-gen-lora` kernel設計 |
| 5 | VLM-reviewerの確立 | 🟡 60% | Shishi未実行 | Shishi batch_review 実行 |

---

## 推奨優先順位

1. **Kaggle学習完了確認** (Today) — `kaggle_pipeline.py status` → `fetch`
2. **FastAPIダッシュボード** (This Week) — `main.py` + Plotly.js でインタラクティブ可視化
3. **Shishi VLMレビュー** (This Week) — Hokusai reviewer 流用、144枚処理
4. **comfy-gen-lora設計** (Next Week) — LoRA推論 + 生成評価 pipeline
