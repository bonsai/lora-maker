# Plan: Shishi ローカル資産のメタデータ構築とダッシュボード統合

## 背景

`data/hokusai` には既に VLM（Vision Language Model）レビュー用のメタデータ構造が構築されている：
- `annotations.txt` — 簡易キャプション
- `hokusai_vlm_reviews.jsonl` — VLM詳細レビュー（subject, category, style_notes, lora_quality, training_suitability）
- `hokusai_vlm_reviews.db` — SQLite版
- `viewer/generate_report.py` → HTMLレポート

`data/shishi`（動画由来フレーム抽出画像）にも **同一構造** を導入し、既存のダッシュボード計画と統合する。

## 1. 目標構造（`data/shishi/`）

```
data/shishi/
├── selected-videos.yml              # 承認済み動画メタデータ（既存）
├── local-videos/                    # 動画ファイル（既存）
│   └── <video_id>/
│       └── <video_id>.mp4
├── images-shishi/                   # フレーム抽出画像 + キャプション（既存）
│   ├── <video_id>_NNNNNN.png
│   └── <video_id>_NNNNNN.txt
├── metadata/                        # 新規：統合メタデータ
│   ├── annotations.txt              # 画像パス → テキスト（VLMキャプション）
│   ├── shishi_vlm_reviews.jsonl     # VLM詳細レビュー（hokusai と同スキーマ）
│   ├── shishi_vlm_reviews.db        # SQLite版
│   └── frame_manifest.json          # フレーム抽出の統計・マッピング
└── review/                          # 既存 + 新規ダッシュボード
    ├── shishi-videos.html           # 既存：YouTube選定レビュー
    ├── contact-sheet.jpg            # 既存
    ├── frame-extraction-error-report.md
    ├── asset-dashboard.html         # 新規：ローカル資産ダッシュボード
    └── asset-manifest.json          # 新規：ダッシュボード用マニフェスト
```

## 2. Hokusai からのスキーマ継承

### 2.1 `annotations.txt`（簡易版）

```
# フォーマット: <relative_image_path>, <caption_text>
metadata/shishi_vlm_captions/gsQuyDa8Kgk_000000.png, yamazaki shishi, animation, solo, short hair
metadata/shishi_vlm_captions/gsQuyDa8Kgk_000001.png, yamazaki shishi, animation, solo, watercolor texture
```

**Shishi特有**: video_id を含めて均一ではないキャプション品質に対処。かつ既存の `images-shishi/<id>_NNNNNN.txt` から初期キャプションを読み込む。

### 2.2 `shishi_vlm_reviews.jsonl`（VLM詳細レビュー）

Hokusai と同じスキーマを維持：

```json
{
  "image": "gsQuyDa8Kgk_000000.png",
  "video_id": "gsQuyDa8Kgk",
  "response": {
    "subject": "The illustration depicts a young female character with distinctive short hair ...",
    "category": "character_animation",
    "style_notes": "The linework is fluid and expressive, typical of Yamazaki Shishi's watercolor rotoscope style...",
    "lora_quality": {
      "linework": 9,
      "contrast": 7,
      "composition": 8,
      "artifact_free": 8,
      "shishi_style": 9
    },
    "training_suitability": 9,
    "notes": "Excellent training material. Clear style consistency, no noise, distinctive artistic signature."
  }
}
```

**Shishi特有の追加フィールド**:
- `video_id` — 動画ソースの紐付け
- `lora_quality.shishi_style` — 作家性の評価（Shishi特有）

### 2.3 `frame_manifest.json`（フレーム抽出統計）

```json
{
  "generated_at": "2026-10-27T12:00:00+09:00",
  "generator": "frame-extract-v1",
  "videos": [
    {
      "video_id": "gsQuyDa8Kgk",
      "video_path": "local-videos/gsQuyDa8Kgk/gsQuyDa8Kgk.mp4",
      "duration_seconds": 11,
      "fps": 30,
      "frames": {
        "target_fps": 1,
        "extracted_count": 12,
        "first_frame": "gsQuyDa8Kgk_000000.png",
        "last_frame": "gsQuyDa8Kgk_000011.png"
      },
      "captions_source": "images-shishi/*.txt"
    }
  ],
  "summary": {
    "total_videos": 5,
    "total_frames": 144,
    "frames_per_video_avg": 28.8,
    "caption_coverage": "144/144"
  }
}
```

## 3. メタデータ構築ワークフロー

```yaml
# workflows/06b-shishi-metadata-build.yml
name: "06b-shishi-metadata-build"
triggers: [manual, post-frame-extraction]
gates:
  - file_exists: data/shishi/selected-videos.yml
  - directory_not_empty: data/shishi/images-shishi/
steps:
  - name: build-frame-manifest
    tool: python tools/build_shishi_manifest.py
    input: data/shishi/images-shishi/, data/shishi/local-videos/, data/shishi/selected-videos.yml
    output: data/shishi/metadata/frame_manifest.json

  - name: run-vlm-review
    tool: python data/hokusai/reviewer/batch_review.py
    args:
      - --input-dir
      - data/shishi/images-shishi/
      - --output
      - data/shishi/metadata/shishi_vlm_reviews.jsonl
      - --db
      - data/shishi/metadata/shishi_vlm_reviews.db
      - --annotations
      - data/shishi/metadata/annotations.txt
    note: "Hokusai reviewer を共用。タグ: shishi, animation, watercolor"

  - name: generate-dashboard-manifest
    tool: python tools/build_asset_dashboard.py
    input:
      - data/shishi/selected-videos.yml
      - data/shishi/metadata/frame_manifest.json
      - data/shishi/metadata/shishi_vlm_reviews.jsonl
    output: data/shishi/review/asset-manifest.json

  - name: build-dashboard-html
    tool: python tools/build_asset_dashboard.py --html
    input: data/shishi/review/asset-manifest.json
    output: data/shishi/review/asset-dashboard.html
```

## 4. ツール実装リスト

### 4.1 `tools/build_shishi_manifest.py`（新規）

**役割**: `images-shishi/` + `local-videos/` + `selected-videos.yml` から `frame_manifest.json` を生成。

**機能**:
- 動画単位でフレームファイルをグルーピング
- 動画ファイルの存在確認（FFprobe でメタデータ取得、オプション）
- キャプションファイル（.txt）の存在確認
- YAML承認データとの紐付け

**引数**:
```bash
python tools/build_shishi_manifest.py \
  --images data/shishi/images-shishi/ \
  --videos data/shishi/local-videos/ \
  --approvals data/shishi/selected-videos.yml \
  --output data/shishi/metadata/frame_manifest.json
```

### 4.2 `tools/build_asset_dashboard.py`（既存計画から拡張）

**役割**: VLMレビュー結果を含めたダッシュボード生成。

**入力**:
- `selected-videos.yml`
- `metadata/frame_manifest.json`
- `metadata/shishi_vlm_reviews.jsonl`
- `images-shishi/`（実画像パス参照）

**出力**:
- `review/asset-manifest.json`（中間、画像パス含む）
- `review/asset-dashboard.html`（最終成果物）

**VLMレビュー統合機能**:
- 画像カードに VLM の `lora_quality` スコアを表示（星表示）
- `training_suitability` で色分け（緑=8-9, 黄=6-7, 赤=<6）
- category でフィルタ（character_animation, landscape, etc.）

## 5. ダッシュボード統合仕様

### 5.1 Video Gallery モード（Phase 2 既存）

拡張：VLMレビュー結果を集計表示

```
┌─────────────────────────────────────┐
│ L'OFFICIEL UKRAINE...               │
│ ✅ Approved  |  🎬 11s  |  🖼 12 frames│
│ VLM Avg: ⭐ 8.5/10 (linework 9,      │
│          style 9, artifact_free 8)  │
│ [thumbnail] [View Frames] [Audit]   │
└─────────────────────────────────────┘
```

### 5.2 Frame Grid モード（Phase 3 既存）

拡張：VLM詳細レビューをインライン表示

```
┌────────────┐  ┌────────────┐  ┌────────────┐
│ 🖼 frame.png│  │ 🖼 frame.png│  │ 🖼 frame.png│
│ ⭐ 9/10    │  │ ⭐ 8/10    │  │ ⭐ 6/10 ⚠️ │
│ [caption]  │  │ [caption]  │  │ [caption]  │
│ character  │  │ character  │  │ blurry     │
└────────────┘  └────────────┘  └────────────┘
```

### 5.3 VLM Review モード（新規）

Hokusai の `viewer/generate_report.py` 方式に準じたレポートビュー。

- 全フレームの `training_suitability` 分布（ヒストグラム、SVGまたはCSS）
- `lora_quality` 各軸の平均スコア
- 低スコアフレーム（<6）の一覧 — 手動除外レビュー用

## 6. Hokusai との共通化設計

### 6.1 共用モジュール

```
tools/review_shared/              # 新規：共用モジュール
├── __init__.py
├── vlm_schema.py                 # JSONスキーマ定義（Hokusai=Shishi共通）
├── image_manifest.py             # 画像ディレクトリ→マニフェスト生成
├── db_utils.py                   # SQLite read/write 共通
└── html_generator.py             # HTMLレポート生成共通JS/CSS
```

### 6.2 統一スキーマ定義（`vlm_schema.py`）

```python
from dataclasses import dataclass
from typing import Dict, Optional

@dataclass
class LoraQualityScores:
    linework: int      # 線の質（0-10）
    contrast: int      # コントラスト（0-10）
    composition: int   # 構図（0-10）
    artifact_free: int # アーティファクトなし（0-10）
    # ターゲット特有スコア（オプション）
    shishi_style: Optional[int] = None
    ukiyo_e_style: Optional[int] = None

@dataclass
class VlmReviewRecord:
    image: str                        # 画像ファイル名
    response: dict                    # VLM生レスポンス
    subject: str
    category: str
    style_notes: str
    lora_quality: LoraQualityScores
    training_suitability: int         # 0-10
    notes: str
    video_id: Optional[str] = None    # Shishi特有
    source_url: Optional[str] = None  # Hokusai特有
```

## 7. 実装フェーズ（統合版）

### Phase 1: メタデータ基盤（本日）

- [ ] `tools/build_shishi_manifest.py` 実装 → `metadata/frame_manifest.json` 生成確認
- [ ] Hokusai `reviewer/` から `batch_review.py` を Shishi 画像に適用 → `shishi_vlm_reviews.jsonl` 生成
- [ ] `annotations.txt` 生成（既存 `.txt` キャプションを集約）

### Phase 2: 共用モジュール抽出（同日）

- [ ] `tools/review_shared/` 作成
- [ ] `vlm_schema.py`, `db_utils.py` を Hokusai から移行/共通化
- [ ] Hokusai 側にシンボリックリンク or import path 修正

### Phase 3: ダッシュボード実装（翌日）

- [ ] `tools/build_asset_dashboard.py` — Video Gallery + Frame Grid
- [ ] VLMレビュー結果統合（星表示、フィルタ）
- [ ] `asset-dashboard.html` 生成確認（`file://` で開く）

### Phase 4: VLM Review モード（翌日）

- [ ] スコア分布ビュー（training_suitability ヒストグラム）
- [ ] 低品質フレーム除外ワークフロー（チェックボックス→YAML出力）

## 8. 実行順序の決定

```
Step 1: tools/build_shishi_manifest.py 実装
Step 2: Hokusai reviewer を Shishi に流用実行
Step 3: tools/review_shared/ 共通化
Step 4: tools/build_asset_dashboard.py 実装
Step 5: VLM Review モード追加
```

**今すぐ開始できるもの**: Step 1（`build_shishi_manifest.py`）は既存ファイル構造のみを参照するため、外部依存なしで実装可能。

---

次のアクション：
1. `tools/build_shishi_manifest.py` を実装 → 5本動画、144フレームのマニフェスト生成
2. Hokusai reviewer を Shishi に実行 → VLMレビューJSONL生成

どちらから進めますか？それとも両方同時に進めますか？
