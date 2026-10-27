#!/usr/bin/env python3
"""Resize Shishi images to max 720px for faster VLM review."""
from pathlib import Path
from PIL import Image
import sys

SRC_DIR = Path("data/shishi/images-shishi")
DST_DIR = Path("data/shishi/images-shishi-720")

def main():
    if not SRC_DIR.exists():
        print(f"Source not found: {SRC_DIR}")
        return
    
    DST_DIR.mkdir(parents=True, exist_ok=True)
    
    images = list(SRC_DIR.glob("*.png"))
    print(f"Found {len(images)} images")
    
    for i, img_path in enumerate(images):
        dst_path = DST_DIR / img_path.name
        
        if dst_path.exists():
            continue
        
        try:
            with Image.open(img_path) as im:
                w, h = im.size
                if max(w, h) > 720:
                    if w > h:
                        new_w = 720
                        new_h = int(h * 720 / w)
                    else:
                        new_h = 720
                        new_w = int(w * 720 / h)
                    im = im.resize((new_w, new_h), Image.LANCZOS)
                im.save(dst_path, optimize=True)
            
            if (i + 1) % 20 == 0:
                print(f"  {i+1}/{len(images)}")
        except Exception as e:
            print(f"Error on {img_path.name}: {e}")
    
    print(f"Done. Resized images in {DST_DIR}")

if __name__ == "__main__":
    main()