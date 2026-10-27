# YouTube 3分動画スクリプト（日本語）

---

**[0:00‑0:10]**
こんにちは！本日は「ヤマザキシシ LoRA」を3分で作る手順をご紹介します。

**[0:10‑0:45]**
**Step 1 – Kaggle Notebook で make‑lora.py を実行**
1. Kaggle にログインし、新規ノートブックを作成
2. 「yamazaki‑shishi‑sdxl‑dataset」を **Add Data** でアタッチ
3. Notebook に下記コードを貼り付け、`make_lora.py` として保存
4. 実行すると、SDXL‑base を読み込み LoRA の骨格だけを作り、`/kaggle/working/` に `lora‑yamazaki‑shishi.safetensors` が生成されます。
※所要時間は **約10分**、GPU が混雑していなければ 5‑7 分で完了します。

**[0:45‑1:30]**
**Step 2 – Kohya_ss / AI‑Toolkit で LoRA 訓練**
1. Kohya_ss（または AI‑Toolkit）をローカルまたは Kaggle の GPU 環境にインストール
2. 以下の設定で学習を開始
   - **Model**: `stabilityai/stable-diffusion-xl-base-1.0`
   - **Dataset**: Notebook の出力フォルダ（`/kaggle/working/images`）
   - **Trigger token**: `yamazaki_shishi`
   - **Epochs**: 10‑20（144枚で十分）
   - **Learning rate**: 1e‑4
   - **Batch size**: 2‑4（GPU メモリに合わせて調整）
3. 訓練が始まり、loss が減少ながら画像が生成され、数十分で完了。
※所要時間は **20‑45分**、GPU が空いていれば 15 分前後で終わります。

**[1:30‑2:00]**
**Step 3 – LoRA ファイルの取得**
- 訓練が終わったら `/kaggle/working/` にある `lora‑yamazaki‑shishi.safetensors` を **Download**
- または Kaggle Notebook の **Output** タブから直接ダウンロードできます。

**[2:00‑2:30]**
**ポイント**
- 144枚の画像で十分です。過度にエポックを重ねると時間がかかります。
- 学習率が高すぎると不安定になるので、1e‑4 が無難です。
- GPU が混雑すると時間が伸びるので、混雑時間帯を避けるとスムーズです。

**[2:30‑2:50]**
**まとめ**
1️⃣ Kaggle Notebook で make‑lora.py を走らせ、LoRA の雛形を作る
2️⃣ Kohya_ss / AI‑Toolkit で本格訓練、20‑45 分で完了
3️⃣ 生成された `lora‑yamazaki‑shishi.safetensors` をダウンロードすれば、ComfyUI や他の UI にインポートして即使用できます。

**[2:50‑3:00]**
以上で 3 分間の LoRA 作成ガイドは終了です。ぜひ試してみてください！