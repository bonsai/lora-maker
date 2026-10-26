#!/usr/bin/env python3
"""Build and train an SDXL LoRA from a Kaggle image dataset.

Default input:
  /kaggle/input/datasets/tyokouchi/yamazaki-shishi-sdxl-dataset

Run in a Kaggle GPU notebook:
  !python /kaggle/working/lora-maker.py

Optional:
  !python /kaggle/working/lora-maker.py --max-train-steps 500 --rank 8

This uses Diffusers' DreamBooth LoRA training example. Images are gathered
recursively from the dataset; a shared instance prompt is used, so per-image
caption files are not required.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

DEFAULT_DATASET = Path(
    "/kaggle/input/datasets/tyokouchi/yamazaki-shishi-sdxl-dataset"
)
DEFAULT_OUTPUT = Path("/kaggle/working/lora-maker-output")
TRAIN_SCRIPT_URL = (
    "https://raw.githubusercontent.com/huggingface/diffusers/main/"
    "examples/dreambooth/train_dreambooth_lora_sdxl.py"
)
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}


def run(command: list[str]) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, check=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--model",
        default="stabilityai/stable-diffusion-xl-base-1.0",
        help="SDXL base model ID or local model path",
    )
    parser.add_argument(
        "--instance-prompt",
        default="a photo of yamazaki shishi",
        help="Shared training prompt for all images; customize for your dataset",
    )
    parser.add_argument("--resolution", type=int, default=1024)
    parser.add_argument("--rank", type=int, default=16)
    parser.add_argument("--max-train-steps", type=int, default=1000)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--train-batch-size", type=int, default=1)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=1)
    parser.add_argument("--checkpointing-steps", type=int, default=500)
    parser.add_argument(
        "--skip-install", action="store_true",
        help="Do not pip-install dependencies (use only in a prepared environment)",
    )
    parser.add_argument(
        "--skip-training", action="store_true",
        help="Only validate dataset and prepare the training script/data",
    )
    return parser.parse_args()


def install_dependencies() -> None:
    # Kaggle usually has torch preinstalled; preserve its CUDA-compatible build.
    run([
        sys.executable, "-m", "pip", "install", "--upgrade",
        "diffusers", "transformers", "accelerate", "peft", "safetensors",
    ])


def collect_images(dataset: Path, destination: Path) -> int:
    if not dataset.is_dir():
        raise FileNotFoundError(
            f"Dataset directory not found: {dataset}\n"
            "Attach the Kaggle dataset to this notebook and check its input path."
        )

    images = sorted(
        p for p in dataset.rglob("*")
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    )
    if not images:
        raise RuntimeError(f"No supported images found under: {dataset}")

    destination.mkdir(parents=True, exist_ok=True)
    copied = 0
    for index, source in enumerate(images):
        # Unique names avoid collisions when different folders contain image.png.
        target = destination / f"{index:06d}{source.suffix.lower()}"
        shutil.copy2(source, target)
        copied += 1

    print(f"Dataset: {dataset}")
    print(f"Images found/copied: {len(images)} / {copied}")
    print(f"Training image directory: {destination}")
    return copied


def download_training_script(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        TRAIN_SCRIPT_URL,
        headers={"User-Agent": "bonsai-lora-maker/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            script = response.read()
    except Exception as exc:
        raise RuntimeError(
            "Could not download the Diffusers SDXL LoRA training example. "
            "Enable Internet in Kaggle or download the script manually from: "
            + TRAIN_SCRIPT_URL
        ) from exc

    if b"train_dreambooth_lora_sdxl" not in script:
        raise RuntimeError("Downloaded training script did not pass a basic sanity check.")
    path.write_bytes(script)
    print(f"Training script saved: {path}")


def main() -> int:
    args = parse_args()
    if args.resolution < 256 or args.rank < 1 or args.max_train_steps < 1:
        raise ValueError("resolution must be >=256; rank and max_train_steps must be positive.")

    if not args.skip_install:
        install_dependencies()

    try:
        import torch
    except ImportError as exc:
        raise RuntimeError("PyTorch is unavailable. Select a Kaggle GPU notebook image.") from exc

    if not args.skip_training:
        if not torch.cuda.is_available():
            raise RuntimeError(
                "CUDA GPU not detected. In Kaggle, select Settings > Accelerator > GPU, "
                "then rerun."
            )
        print(f"GPU: {torch.cuda.get_device_name(0)}")

    work_dir = Path("/kaggle/working/lora-maker")
    image_dir = work_dir / "instance-images"
    train_script = work_dir / "train_dreambooth_lora_sdxl.py"
    args.output.mkdir(parents=True, exist_ok=True)

    count = collect_images(args.dataset, image_dir)
    download_training_script(train_script)

    if args.skip_training:
        print(f"Preparation complete. {count} images ready; training was skipped.")
        return 0

    command = [
        sys.executable, str(train_script),
        "--pretrained_model_name_or_path", args.model,
        "--instance_data_dir", str(image_dir),
        "--output_dir", str(args.output),
        "--instance_prompt", args.instance_prompt,
        "--resolution", str(args.resolution),
        "--train_batch_size", str(args.train_batch_size),
        "--gradient_accumulation_steps", str(args.gradient_accumulation_steps),
        "--learning_rate", str(args.learning_rate),
        "--lr_scheduler", "constant",
        "--lr_warmup_steps", "0",
        "--max_train_steps", str(args.max_train_steps),
        "--checkpointing_steps", str(args.checkpointing_steps),
        "--rank", str(args.rank),
        "--gradient_checkpointing",
        "--enable_xformers_memory_efficient_attention",
    ]

    # xFormers may not be installed in every Kaggle image. Retry without the
    # optional flag if the training script reports that it is unavailable.
    print("\nStarting SDXL DreamBooth LoRA training.", flush=True)
    result = subprocess.run(command)
    if result.returncode != 0:
        print(
            "Training failed. If the error mentions xformers, install xformers "
            "or remove --enable_xformers_memory_efficient_attention from the command.",
            file=sys.stderr,
        )
        return result.returncode

    adapter_files = [
        p for p in args.output.rglob("*")
        if p.is_file() and p.name in {"pytorch_lora_weights.safetensors", "pytorch_lora_weights.bin"}
    ]
    if not adapter_files:
        raise RuntimeError(
            "Training command exited successfully, but no LoRA adapter weight file "
            f"was found under {args.output}. Inspect the training logs."
        )

    print("\nLoRA training finished. Adapter artifact(s):")
    for path in adapter_files:
        print(f"  {path} ({path.stat().st_size:,} bytes)")
    print(f"Output directory: {args.output}")
    print("Note: run an inference test with the base model plus this adapter before publishing.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(f"Command failed with exit code {exc.returncode}: {exc.cmd}", file=sys.stderr)
        raise SystemExit(exc.returncode)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
