# Plan: ローカル資産管理ダッシュボード（`data/shishi`）

## 1. 目的

`data/shishi` 以下の4種資産を **1画面で俯瞰・管理** するローカルHTMLダッシュボードを構築する。

| 資産 | 場所 | 内容 |
|------|------|------|
| **動画リスト** | `selected-videos.yml` | 承認済み動画のメタデータ・権利情報 |
| **動画** | `local-videos/<id>/<id>.mp4` | 実際にDLされた動画ファイル |
| **スクショ** | `images-shishi/<id>_NNNNNN.png` | フレーム抽出した学習用画像 |
| **メタデータ** | `.txt` / `.yml` / error reports | キャプション、承認書、エラーレポート |

既存の `review/shishi-videos.html` は **YouTube上の公開動画をレビューして候補を選ぶ** ためのもの。新ダッシュボードは **選んで承認し、DL・フレーム抽出まで完了した後の資産を管理する** 位置づけ。

## 2. 資産構造（Canonical Layout）

```
data/shishi/
├── selected-videos.yml          # 承認済み動画メタデータ（Single Source of Truth）
├── local-videos/                # 動画ファイル（.mp4）
│   ├── gsQuyDa8Kgk/
│   │   └── gsQuyDa8Kgk.mp4
│   └── ...
├── images-shishi/               # フレーム抽出画像 + 自動キャプション
│   ├── gsQuyDa8Kgk_000000.png
│   ├── gsQuyDa8Kgk_000000.txt
│   └── ...
└── review/                      # レビュー・可視化成果物
    ├── shishi-videos.html       # 既存：YouTube選定用レビュー
    ├── contact-sheet.jpg        # 既存：連絡先シート
    ├── frame-extraction-error-report.md
    └── asset-dashboard.html     # 新規：ローカル資産管理ダッシュボード（生成物）
```

## 3. ダッシュボード要件

### 3.1 表示モード

| モード | 用途 |
|--------|------|
| **Video Gallery** | 動画単位のカード。サムネイル（先頭フレーム）、メタデータ、スクショ枚数、ファイル存在確認 |
| **Frame Grid**    | 抽出画像を動画別 / 全体でグリッド表示。キャプション付き。ページネーション必須（144枚+） |
| **Dataset Table** | 学習セット（`images-shishi/*.png+.txt`）をテーブル表示。タグ検索、品質チェック用 |
| **Audit Log**     | `selected-videos.yml` の権利情報、`frame-extraction-error-report.md` などを一覧 |

### 3.2 フィルタ・検索

- 動画ID / タイトル あいまい検索
- 承認ステータス（ approved / pending / error ）
- スクショ有無（抽出成功 / 失敗 / 未実施）
- タグ（キャプション内タグからインデックス）

### 3.3 データソース

ダッシュボードは **生成物（ビルド成果物）** とし、ソースは `selected-videos.yml` + `images-shishi/` + `local-videos/` から自動構築する。

```yaml
# data/shishi/review/asset-manifest.json （中間ファイル、生成物）
{
  "generated_at": "2026-10-27T12:00:00",
  "videos": [
    {
      "video_id": "gsQuyDa8Kgk",
      "title": "L'OFFICIEL UKRAINE...",
      "has_local_video": true,
      "video_path": "local-videos/gsQuyDa8Kgk/gsQuyDa8Kgk.mp4",
      "frames": [
        {"path": "images-shishi/gsQuyDa8Kgk_000000.png", "caption": "..."}
      ],
      "frame_count": 12,
      "permission_status": "approved",
      "rights_basis": "platform_license"
    }
  ],
  "stats": {
    "total_videos_approved": 5,
    "total_videos_downloaded": 5,
    "total_frames": 144,
    "tags_index": {"yamazaki shishi": 144, "animation": 120, ...}
  }
}
```

## 4. 技術スタック

| レイヤ | 選択 | 理由 |
|--------|------|------|
| **Generator** | Python 3.13（`tools/build_asset_dashboard.py`） | ファイルシステム走査、YAML読み込み、JSON書き出し。既存パイプラインと同じ言語 |
| **Frontend** | 静的HTML + Vanilla JS（Single File） | ブラウザで `file://` 直接開ける。サーバ不要。配布・Git管理が簡単 |
| **Styling** | インライン/埋め込みCSS | 既存 `shishi-videos.html` と同じ方式。外部依存ゼロ |
| **Asset Manifest** | `data/shishi/review/asset-manifest.json` | Python生成、JS読込。フレーム情報が多いためHTMLに直接埋め込むと重くなるので分離 |

## 5. 実装フェーズ

### Phase 1: ディスカバリ & マニフェスト生成（今日）

- [ ] `tools/build_asset_dashboard.py` スケルトン作成
- [ ] `data/shishi` を traverse して `asset-manifest.json` を生成
- [ ] 存在チェック: `local-videos/<id>/*.mp4`, `images-shishi/<id>_*.png`
- [ ] `.txt` キャプションを読み込んでタグインデックスを構築
- [ ] CLI: `python tools/build_asset_dashboard.py --input data/shishi --output data/shishi/review/`

**受入基準:**
- 承認済み5本の動画がマニフェストに正しく列挙される
- 各動画の frame_count、has_local_video が正しい
- タグ頻度トップ20が JSON に出力される

### Phase 2: ダッシュボードHTML雛形（今日〜明日）

- [ ] `data/shishi/review/asset-dashboard.html` 雛形（CSSフレームワークなし）
- [ ] Video Gallery モード（動画カード）
- [ ] サムネイル表示：最初のフレーム画像を `<img>` で埋め込み
- [ ] メタデータ表示：タイトル、承認状況、スクショ枚数、タグ一覧
- [ ] ローカル動画プレビュー：`<video>` タグ（`file://` 制約あり、パス表示で代替可能）

**受入基準:**
- `file:///C:/.../asset-dashboard.html` をブラウザで開いて5本の動画がカード表示される
- 画像が表示される（相対パスで解決）

### Phase 3: Frame Grid & Dataset Table（明日）

- [ ] Frame Grid：動画別タブ / 全体グリッド。ページネーション（50枚/ページ）
- [ ] キャプション表示：画像ホバーまたは直下に `.txt` 内容を表示
- [ ] Dataset Table：テーブル形式。タグでフィルタ可能
- [ ] 検索：クライアントサイド（JS）でタイトル・タグ・IDをインクリメンタル検索

**受入基準:**
- 144枚の画像が重くなくスクロールできる（ページネーション or 仮想スクロール）
- タグ「yamazaki shishi」でフィルタすると全144枚が表示される

### Phase 4: 統合 & 既存レビュー共存（明日）

- [ ] `shishi-videos.html`（YouTubeレビュー）との役割分離を明記
- [ ] `review/README.md` に各HTMLの用途を記載
- [ ] `lora-train.ps1` または `tools/kaggle_pipeline.py` の `doctor` に「ダッシュボードが最新か？」のチェックを追加（任意）
- [ ] `.gitignore`：`asset-manifest.json`, `asset-dashboard.html` を **追跡対象とする**（review/配下の生成物として）または `.gitignore` してCI生成にする。今回は **手動生成・コミット**で始める

## 6. ワークフロー（YAML → 日常操作）

```yaml
# workflows/06-asset-dashboard.yml （新規設計案）
name: "06-asset-dashboard"
triggers: [manual, post-extraction]
gates:
  - file_exists: data/shishi/selected-videos.yml
  - file_exists: data/shishi/images-shishi/
  - directory_not_empty: data/shishi/images-shishi/
steps:
  - name: generate-manifest
    tool: python tools/build_asset_dashboard.py
    args: [--input, data/shishi, --output, data/shishi/review/]
  - name: open-dashboard
    instruction: "Open data/shishi/review/asset-dashboard.html in browser"
```

**日常フロー:**
1. フレーム抽出後、`python tools/build_asset_dashboard.py` を実行
2. ブラウザで `asset-dashboard.html` を開く
3. 動画・画像・メタデータの整合性を目視確認
4. 問題あれば `selected-videos.yml` や抽出スクリプトを修正 → 再生成

## 7. 画面構成案（Wireframe）

```
+-------------------------------------------------------------+
|  [Asset Dashboard]  Yamazaki Shishi  |  🎥 5 Videos  🖼 144 Frames  |
+-------------------------------------------------------------+
| [Video Gallery] [Frame Grid] [Dataset Table] [Audit Log]   |
+-------------------------------------------------------------+
| 🔍 Search: [____________]  Filter: [All ▼] [Approved ▼]    |
+-------------------------------------------------------------+
| +------------------+  +------------------+  +----------------+ |
| | 🖼 [thumb]        |  | 🖼 [thumb]        |  | ...            | |
| | L'OFFICIEL...    |  | Bloom YAMAZAKI    |                 | |
| | ✅ Approved       |  | ✅ Approved       |                 | |
| | 🖼 12 frames      |  | 🖼 40 frames      |                 | |
| | [▶ local video]  |  | [▶ local video]  |                 | |
| +------------------+  +------------------+  +----------------+ |
+-------------------------------------------------------------+
| Selected: gsQuyDa8Kgk_000000.png  "yamazaki shishi, ..."    |
+-------------------------------------------------------------+
```

## 8. 注意事項・制約

- **ブラウザセキュリティ:** `file://` プロトコルでは `<video src="../local-videos/...">` が動作しない場合がある（ChromeはOK、Edge/制限付き）。その場合は動画パスを表示してコピー可能にする。
- **大容量画像:** 144枚 × 数MB の画像をページ内に全展開すると重い。ページネーションまたは lazy loading が必須。
- **パス解決:** HTML は `data/shishi/review/` に置くため、画像への相対パスは `../images-shishi/` となる。
- **Git管理:** 生成物（HTML, JSON）をコミットするか否か。今回は **生成コマンドを共有** しつつ、成果物もコミットしておくとブラウザで即見れるため推奨（ただしマニフェストは画像パスを含むため、他環境ではパスが異なる可能性あり → ローカル専用と明記）。
