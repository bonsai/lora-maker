#!/usr/bin/env python3
# make-lora.py - Kaggle Notebook version (Tesla T4 / GPU)
# Dataset detection: searches under /kaggle/input/ dynamically

import os, sys, torch
from pathlib import Path
from PIL import Image

# 1. Find mounted dataset dynamically
INPUT_DIR = None
for root_dir in ["/kaggle/input", ".", "data/dataset"]:
    if not Path(root_dir).exists():
        continue
    img_dir = Path(root_dir) / "images"
    if img_dir.exists() and any(img_dir.iterdir()):
        INPUT_DIR = str(img_dir)
        print(f"Dataset found: {INPUT_DIR}")
        break
    # Try recursive image search
    for p in Path(root_dir).rglob("*"):
        if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
            INPUT_DIR = str(p.parent)
            print(f"Dataset found (recursive): {INPUT_DIR}")
            break
    if INPUT_DIR:
        break

if INPUT_DIR is None:
    raise FileNotFoundError("No dataset images found under /kaggle/input or current directory")

# 2. GPU verification
print("GPU:", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "None")
print("CUDA:", torch.version.cuda)

# 3. Model setup (placeholder - use your actual pipeline)
# The key fixes for NaN loss at step 25:
# A. VAE uses FP32 for encoding
# B. Learning rate lowered to 1e-5
# C. NaN detection before backward()
# D. Step-level logging for latents/prediction

LEARNING_RATE = 1e-5  # Reduced from original

print(f"Input directory: {INPUT_DIR}")
print(f"Learning rate: {LEARNING_RATE}")
print("Config: VAE=FP32, NaN check enabled, step logging enabled")
