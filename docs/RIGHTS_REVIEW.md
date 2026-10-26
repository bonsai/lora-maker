# 権利・許諾レビュー手順

この文書は法的助言ではない。最終判断は権利者・利用規約・必要なら専門家の確認に従う。
`run_workflow.py` は「記録が揃っているか」を検査するだけで、許諾の有効性を判定しない。

## 原則

1. 公開されていること・名前が一致することは、利用許諾の根拠にならない。
2. 申告（「許可をもらった」）だけでは足りない。**根拠の参照先**と**利用範囲**を記録する。
3. 利用範囲は工程ごとに分ける。取得・フレーム抽出・データセット作成・学習は別々の行為である。
4. 不明は `unknown` のまま残す。`approved` に読み替えない。
5. 公開範囲を広げる（private → public、データセット公開、モデル配布）には、その時点で新しい承認が要る。

## 記録する3つの成果物

| ファイル | 何を承認するか | 主な記入者 |
| --- | --- | --- |
| `data/approvals/domain-decision.json` | 対象・出典・権利者・利用目的と公開範囲 | プロジェクト所有者 |
| `data/approvals/approval-record.json` | どの動画を、どの利用範囲で処理するか | 選定レビュー担当 |
| `data/approvals/dataset-approval.json` | 出来上がった画像・キャプション・manifest の中身 | データセットレビュー担当 |

雛形は `data/approvals/*.template.json`。**雛形は承認ではない**（`approved: false`）。
コピーして必要事項を実際に確認した後だけ記入する。

## 1. domain-decision.json

| フィールド | 内容 |
| --- | --- |
| `approved` | 実際にレビューを終えた時だけ `true` |
| `subject_name` / `subject_type` | 対象の同一性。外見だけで推定しない |
| `rights_holder` | 権利者名。「unknown」「none」は不可（不明なら止める） |
| `intended_use` | 本ワークフローでは `private_experiment` 固定 |
| `publication_scope` | `local_only` または `private_dataset` のみ許可 |
| `source_urls` | 参照元の正確な URL（1件以上） |
| `permission_evidence[]` | `reference`（文書パス・URL・メッセージID）、`checked_at`（YYYY-MM-DD）、`covers`（何をカバーするか） |
| `reviewed_by` / `reviewed_at` | レビューした人間と日付 |

`source_urls` は「見つけた候補」ではなく「出典として確認したもの」を書く。

## 2. approval-record.json

| フィールド | 内容 |
| --- | --- |
| `selected_video_ids` | 処理を許可する動画 ID。`selected-videos.yml` と一致必須 |
| `approved_uses` | `acquisition`, `frame_extraction`, `dataset_creation` を含める |
| `excluded_time_ranges` | 使わない区間。無い場合も空配列で明示 |
| `reason_each_video_is_representative` | 各 ID → 代表理由（選定理由の記録） |
| `reviewed_by` / `reviewed_at` | レビューした人間と日付 |

`selected_videos.yml` に載っているのに、ここに ID が無い動画は実行時に止まる。

## 3. selected-videos.yml

`selected-videos.example.yml` をコピーして作る。必須フィールド:

- `video_id`, `source_url`, `local_path`
- `creator_or_rights_holder`
- `terms_url`（利用規約・許諾文書の場所）
- `rights_basis`（`written_permission` / `self_owned` / `platform_license` など具体的に。`publicly_visible` は不可）
- `permitted_uses`（`acquisition`, `frame_extraction`, `dataset_creation` を含む）
- `permission_status`（`approved` 以外は実行されない）
- `reviewed_by`, `reviewed_at`

`local_path` はプロジェクト内（`C:\Users\0501JP\lora-maker` 配下）に置く。外部パスは拒否される。

## 4. dataset-approval.json

`dataset --execute` の実行後に表示される `manifest.json sha256` を `manifest_sha256` に、
`dataset content sha256` を `content_sha256` に記入する。
画像または caption を1枚でも編集すると content hash が変わり、`package` は失敗する（承認後の差し替え防止）。

`captions_reviewed` と `contact_sheet_reviewed` は、実際に目視確認した時だけ `true`。

## 上書き

`dataset --execute` は既存の画像・caption・manifest・contact sheet があると停止する。
内容を確認したうえで作り直す場合だけ `--overwrite` を付ける（`--execute` と併用必須）。

## 実行順

```powershell
python run_workflow.py validate     # YAML と安全設定
python run_workflow.py preflight    # 未解決条件の一覧（読み取りのみ、終了コード 1 = 未承認）
# 記録を埋める（実確認の後）
python run_workflow.py dataset      # まだ dry-run。ここで再度 preflight 相当を表示
python run_workflow.py dataset --execute
# contact sheet と caption を目視 → dataset-approval.json を記入
python run_workflow.py package
python run_workflow.py kaggle-plan  # ローカルに計画を書くだけ。アップロードしない
```

`preflight` が 0 件になるまで `--execute` に進まない。

## よくある誤り

- 規約ページを開いただけで `permission_status: approved` にする（→ `terms_url` と `reviewed_by` が空なら止まる）
- 「本人っぽい」という理由で `subject_type` を確定する（→ 同一性の根拠を `permission_evidence` に残す）
- 学習まで許可されたつもりでデータセットを渡す（→ 学習は本ワークフロー外。別途承認が必要）
- データセット公開後に規約を確認する（→ `private_dataset` 固定。公開は新しい承認）
