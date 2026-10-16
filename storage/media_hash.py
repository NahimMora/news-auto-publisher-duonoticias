from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

import cv2
import numpy as np


def file_sha1(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha1()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def image_phash(image: np.ndarray, hash_size: int = 8) -> str:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA)
    dct = cv2.dct(np.float32(resized))
    low_freq = dct[: hash_size, : hash_size]
    median = np.median(low_freq[1:, 1:])
    bits = low_freq > median
    return "".join("1" if value else "0" for value in bits.flatten())


def video_first_frame_phash(path: str | Path) -> str:
    capture = cv2.VideoCapture(str(path))
    ok, frame = capture.read()
    capture.release()
    if not ok or frame is None:
        raise RuntimeError(f"No se pudo leer el primer frame de {path}")
    return image_phash(frame)


def image_file_phash(path: str | Path) -> str:
    image = cv2.imread(str(path))
    if image is None:
        raise RuntimeError(f"No se pudo leer la imagen {path}")
    return image_phash(image)


def perceptual_hash_for_asset(path: str | Path, kind: str) -> Optional[str]:
    suffix = Path(path).suffix.lower()
    if kind == "video" or suffix in {".mp4", ".mov", ".m4v", ".webm"}:
        return video_first_frame_phash(path)
    if suffix in {".jpg", ".jpeg", ".png", ".webp"}:
        return image_file_phash(path)
    return None


def hamming_distance(left: str, right: str) -> int:
    if not left or not right or len(left) != len(right):
        return max(len(left), len(right), 64)
    return sum(1 for lch, rch in zip(left, right) if lch != rch)
