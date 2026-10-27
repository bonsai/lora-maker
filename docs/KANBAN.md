# KANBAN — ヤマザキシシ SDXL LoRA

正本は [`reqs.yaml`](reqs.yaml)。このファイルはその表示用ビューで、状態を変えたら両方を更新する。
最終更新: 2026-10-27

## 現在地

| 項目 | 状態 |
| --- | --- |
| データセット | 144 枚 + captions、承認済み (ZIP 77.8MB / sha256 `1360cb59…`) |
| Kaggle dataset | `tyokouchi/yamazaki-shishi-sdxl-dataset` private・ready |
| 学習 | **未完了**。過去 notebook は NaN / ERROR、CLI パイプラインは未実装 |
| Kaggle GPU | 1.65h / 30h 使用 (残 28.35h) |
| ローカル | 2GB VRAM 級のため学習不可。Kaggle T4 を使う |

## ボード

### Done
- [x] K-01 データセット生成・承認 (144 枚 / manifest `adb510cb…`)
- [x] K-02 Kaggle private dataset 登録
- [x] K-03 過去 notebook の試行を `kaggle/` に隔離 (参照用)

### Ready (次に着手)
- [ ] **K-04** `tools/kaggle_pipeline.py` — doctor / build / push / wait / fetch / run
- [ ] **K-05** `kaggle/train_lora.py` + `config.toml` — kohya SDXL, T4 向け既定値

### In Progress
- なし

### Todo
- [ ] K-06 承認ゲート + テスト (`--execute` 必須、private 固定、token 非出力)
- [ ] K-07 CI (オフライン: unittest + validate + build)
- [ ] K-09 T4 で 1 本目の学習を完走
- [ ] K-10 ComfyUI で before/after 評価
- [ ] K-11 手順とレシピのドキュメント化

### Blocked
- [ ] **K-08 CD (workflow_dispatch)** — GitHub secrets / Environment が未設定。ローカルは OAuth のみ
  - 解除条件: `KAGGLE_USERNAME` + `KAGGLE_KEY` (または `KAGGLE_API_TOKEN`) を Secrets に登録し、Environment `kaggle` に承認者を設定

## 次の 3 手

1. `tools/kaggle_pipeline.py` を実装し、`doctor` と `build` をネットワークなしで通す
2. `kaggle/train_lora.py` を生成し、T4 用 config (batch 1 / ga 4 / fp16 / no_half_vae / grad checkpointing) を固定
3. `--execute` で kernel を push → `wait` → `fetch` し、1 本目を完走させる

## 実行コマンド (予定)

```powershell
python tools/kaggle_pipeline.py doctor
python tools/kaggle_pipeline.py build
python tools/kaggle_pipeline.py run --execute --kernel tyokouchi/yamazaki-shishi-lora
```

## ゲート (fail-closed)

- dataset / kernel が private 以外 → 中断
- dataset 承認ハッシュが実ファイルと不一致 → 中断
- `--execute` なしで remote 操作 → dry-run 表示のみ
- 認証情報をログ・receipt・YAML に含める → 失敗扱い

## リスク

| ID | リスク | 対策 |
| --- | --- | --- |
| X-01 | T4 16GB で OOM | batch 1 / ga 4 / grad checkpointing / cache latents / unet only |
| X-02 | fp16 VAE で NaN | `no_half_vae` / `min_snr_gamma` / step ログ |
| X-03 | GPU quota 消費 | 1 回 2h 以内 / 2 epoch ごとに保存 / dry-run 先行 |
| X-04 | public 化・元動画混入 | private 固定 / ZIP 検証 / push 前ゲート |
| X-05 | CI から Kaggle 認証不可 | `KAGGLE_API_TOKEN` 対応 / 失敗時はローカル CLI |
