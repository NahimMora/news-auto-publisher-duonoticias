"""Lightweight video sanitizer for QR codes and static overlays."""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import cv2
import numpy as np


BBox = Tuple[int, int, int, int]


@dataclass
class SanitizerConfig:
    sample_fps: int = 1
    max_frames: int = 20
    max_mask_area: float = 0.35
    ffmpeg_bin: str = os.getenv("FFMPEG_BIN", "ffmpeg")
    ffmpeg_vcodec: str = os.getenv("FFMPEG_VCODEC", "libx264")
    ffmpeg_preset: str = os.getenv("FFMPEG_PRESET", "veryfast")
    ffmpeg_crf: str = os.getenv("FFMPEG_CRF", "23")

    @classmethod
    def from_env(cls) -> "SanitizerConfig":
        return cls(
            sample_fps=max(1, int(os.getenv("SANITIZER_SAMPLE_FPS", "1"))),
            max_frames=max(1, int(os.getenv("SANITIZER_FRAME_SAMPLES", "20"))),
            max_mask_area=float(os.getenv("SANITIZER_MAX_MASK_AREA", "0.35")),
            ffmpeg_bin=os.getenv("FFMPEG_BIN", "ffmpeg"),
            ffmpeg_vcodec=os.getenv("FFMPEG_VCODEC", "libx264"),
            ffmpeg_preset=os.getenv("FFMPEG_PRESET", "veryfast"),
            ffmpeg_crf=os.getenv("FFMPEG_CRF", "23"),
        )


def sample_frames(video_path: str, sample_fps: int = 1, max_frames: int = 20) -> List[np.ndarray]:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return []

    fps = cap.get(cv2.CAP_PROP_FPS) or 0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = (total_frames / fps) if fps > 0 and total_frames > 0 else 0
    target = min(max_frames, max(1, int(max(1.0, duration) * max(1, sample_fps))))

    frames: List[np.ndarray] = []
    if duration > 0 and fps > 0:
        times = np.linspace(0.0, max(duration - (1.0 / fps), 0.0), num=target)
        for second in times:
            cap.set(cv2.CAP_PROP_POS_MSEC, float(second) * 1000.0)
            ok, frame = cap.read()
            if ok and frame is not None:
                frames.append(frame)

    if not frames:
        step = max(1, int(round((fps or 25) / max(1, sample_fps))))
        idx = 0
        while len(frames) < max_frames:
            ok, frame = cap.read()
            if not ok:
                break
            if idx % step == 0:
                frames.append(frame)
            idx += 1

    cap.release()
    return frames[:max_frames]


def _clip_bbox(bbox: Sequence[int], width: int, height: int) -> Optional[BBox]:
    x, y, w, h = [int(v) for v in bbox]
    x = max(0, min(x, width - 1))
    y = max(0, min(y, height - 1))
    w = max(1, min(w, width - x))
    h = max(1, min(h, height - y))
    if w <= 0 or h <= 0:
        return None
    return (x, y, w, h)


def _bbox_from_points(points: np.ndarray, width: int, height: int, pad: int = 4) -> Optional[BBox]:
    if points is None or points.size == 0:
        return None
    pts = np.array(points, dtype=np.float32).reshape(-1, 2)
    x0 = max(0, int(np.floor(np.min(pts[:, 0])) - pad))
    y0 = max(0, int(np.floor(np.min(pts[:, 1])) - pad))
    x1 = min(width - 1, int(np.ceil(np.max(pts[:, 0])) + pad))
    y1 = min(height - 1, int(np.ceil(np.max(pts[:, 1])) + pad))
    bw = x1 - x0
    bh = y1 - y0
    if bw <= 2 or bh <= 2:
        return None
    return (x0, y0, bw, bh)


def detect_qr(frames: Sequence[np.ndarray]) -> List[Dict[str, Any]]:
    if not frames:
        return []

    detector = cv2.QRCodeDetector()
    detections: List[Dict[str, Any]] = []
    frame_h, frame_w = frames[0].shape[:2]

    for frame in frames:
        try:
            ok, decoded, points, _ = detector.detectAndDecodeMulti(frame)
        except Exception:
            ok, decoded, points = False, [], None

        if ok and points is not None:
            for idx, qpoints in enumerate(points):
                bbox = _bbox_from_points(np.array(qpoints), frame_w, frame_h)
                if not bbox:
                    continue
                text_value = ""
                if isinstance(decoded, (list, tuple)) and idx < len(decoded):
                    text_value = decoded[idx] or ""
                detections.append(
                    {
                        "type": "qr",
                        "bbox": list(bbox),
                        "confidence": 0.9 if text_value.strip() else 0.72,
                    }
                )
            continue

        try:
            decoded_text, points, _ = detector.detectAndDecode(frame)
        except Exception:
            decoded_text, points = "", None
        if points is not None:
            bbox = _bbox_from_points(np.array(points), frame_w, frame_h)
            if bbox:
                detections.append(
                    {
                        "type": "qr",
                        "bbox": list(bbox),
                        "confidence": 0.86 if (decoded_text or "").strip() else 0.68,
                    }
                )

    return detections


def detect_static_overlays(frames: Sequence[np.ndarray]) -> List[Dict[str, Any]]:
    if len(frames) < 2:
        return []

    gray_frames = [cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32) for frame in frames]
    stack = np.stack(gray_frames, axis=0)
    variance_map = np.var(stack, axis=0)
    median_frame = np.median(stack, axis=0).astype(np.uint8)
    edges = cv2.Canny(median_frame, threshold1=60, threshold2=150)

    h, w = median_frame.shape
    edge_mask = (edges > 0).astype(np.uint8)
    variance_threshold = max(3.0, float(np.percentile(variance_map, 28)))
    low_variance_mask = (variance_map <= variance_threshold).astype(np.uint8)
    candidate = (low_variance_mask & edge_mask).astype(np.uint8) * 255

    # Static overlays in social videos are usually in corners and top/bottom bands.
    positional_prior = np.zeros((h, w), dtype=np.uint8)
    band_h = max(1, int(h * 0.24))
    side_w = max(1, int(w * 0.22))
    positional_prior[:band_h, :] = 1
    positional_prior[h - band_h :, :] = 1
    positional_prior[:, :side_w] = 1
    positional_prior[:, w - side_w :] = 1
    candidate = ((candidate > 0) & (positional_prior > 0)).astype(np.uint8) * 255

    k3 = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    k5 = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    candidate = cv2.morphologyEx(candidate, cv2.MORPH_CLOSE, k5, iterations=2)
    candidate = cv2.morphologyEx(candidate, cv2.MORPH_OPEN, k3, iterations=1)
    candidate = cv2.dilate(candidate, k3, iterations=1)

    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(candidate, connectivity=8)
    frame_area = float(w * h)
    global_variance = float(np.mean(variance_map)) + 1e-6

    detections: List[Dict[str, Any]] = []
    for label in range(1, num_labels):
        x, y, bw, bh, area = [int(v) for v in stats[label]]
        if area < frame_area * 0.00045 or area > frame_area * 0.22:
            continue
        aspect_ratio = bw / max(float(bh), 1.0)
        if aspect_ratio < 0.2 or aspect_ratio > 14.0:
            continue

        region_edges = edge_mask[y : y + bh, x : x + bw]
        region_variance = variance_map[y : y + bh, x : x + bw]
        edge_density = float(np.mean(region_edges))
        variance_ratio = float(np.mean(region_variance) / global_variance)
        temporal_stability = max(0.0, min(1.0, 1.0 - variance_ratio))

        confidence = 0.45 + (0.35 * edge_density) + (0.2 * temporal_stability)
        margin_x = int(w * 0.18)
        margin_y = int(h * 0.18)
        if x <= margin_x or y <= margin_y or (x + bw) >= (w - margin_x) or (y + bh) >= (h - margin_y):
            confidence += 0.05
        confidence = float(max(0.0, min(0.98, confidence)))
        if confidence < 0.55:
            continue

        pad = int(max(4, round(max(bw, bh) * 0.06)))
        bbox = _clip_bbox((x - pad, y - pad, bw + (2 * pad), bh + (2 * pad)), w, h)
        if not bbox:
            continue

        detections.append(
            {
                "type": "static_overlay",
                "bbox": list(bbox),
                "confidence": round(confidence, 3),
            }
        )

    return detections


def _bbox_iou(a: Sequence[int], b: Sequence[int]) -> float:
    ax, ay, aw, ah = [int(v) for v in a]
    bx, by, bw, bh = [int(v) for v in b]
    ax2, ay2 = ax + aw, ay + ah
    bx2, by2 = bx + bw, by + bh

    inter_x1 = max(ax, bx)
    inter_y1 = max(ay, by)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)

    inter_w = max(0, inter_x2 - inter_x1)
    inter_h = max(0, inter_y2 - inter_y1)
    inter = float(inter_w * inter_h)
    if inter <= 0:
        return 0.0

    a_area = float(max(1, aw * ah))
    b_area = float(max(1, bw * bh))
    union = a_area + b_area - inter
    if union <= 0:
        return 0.0
    return inter / union


def _overlap_ratio(a: Sequence[int], b: Sequence[int]) -> float:
    ax, ay, aw, ah = [int(v) for v in a]
    bx, by, bw, bh = [int(v) for v in b]
    ax2, ay2 = ax + aw, ay + ah
    bx2, by2 = bx + bw, by + bh
    inter_x1 = max(ax, bx)
    inter_y1 = max(ay, by)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    inter_w = max(0, inter_x2 - inter_x1)
    inter_h = max(0, inter_y2 - inter_y1)
    inter = float(inter_w * inter_h)
    if inter <= 0:
        return 0.0
    min_area = float(min(max(1, aw * ah), max(1, bw * bh)))
    return inter / min_area


def _union_bbox(a: Sequence[int], b: Sequence[int]) -> BBox:
    ax, ay, aw, ah = [int(v) for v in a]
    bx, by, bw, bh = [int(v) for v in b]
    x1 = min(ax, bx)
    y1 = min(ay, by)
    x2 = max(ax + aw, bx + bw)
    y2 = max(ay + ah, by + bh)
    return (x1, y1, max(1, x2 - x1), max(1, y2 - y1))


def merge_bboxes(detections: Sequence[Dict[str, Any]], iou_threshold: float = 0.2) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    ordered = sorted(detections, key=lambda d: float(d.get("confidence", 0.0)), reverse=True)

    for raw in ordered:
        dtype = str(raw.get("type") or "static_overlay")
        bbox = [int(v) for v in (raw.get("bbox") or [])[:4]]
        if len(bbox) != 4:
            continue
        confidence = float(raw.get("confidence", 0.6))

        attached = False
        for existing in merged:
            if existing.get("type") != dtype:
                continue
            iou = _bbox_iou(existing["bbox"], bbox)
            overlap = _overlap_ratio(existing["bbox"], bbox)
            if iou >= iou_threshold or overlap >= 0.45:
                existing["bbox"] = list(_union_bbox(existing["bbox"], bbox))
                existing["confidence"] = round(max(float(existing.get("confidence", 0.0)), confidence), 3)
                attached = True
                break

        if not attached:
            merged.append(
                {
                    "type": dtype,
                    "bbox": bbox,
                    "confidence": round(confidence, 3),
                }
            )

    return merged


def build_mask(
    width: int,
    height: int,
    detections: Sequence[Dict[str, Any]],
    output_path: Optional[Path] = None,
) -> Path:
    mask = np.zeros((height, width), dtype=np.uint8)
    for det in detections:
        bbox = det.get("bbox") if isinstance(det, dict) else det
        if not bbox:
            continue
        clipped = _clip_bbox(bbox, width, height)
        if not clipped:
            continue
        x, y, w, h = clipped
        mask[y : y + h, x : x + w] = 255

    if output_path is None:
        temp_file = tempfile.NamedTemporaryFile(prefix="sanitizer_mask_", suffix=".png", delete=False)
        output_path = Path(temp_file.name)
        temp_file.close()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_path), mask)
    return output_path


def apply_blur_ffmpeg(
    input_path: str,
    mask_path: str,
    output_path: str,
    cfg: Optional[SanitizerConfig] = None,
) -> bool:
    cfg = cfg or SanitizerConfig.from_env()
    cmd = [
        cfg.ffmpeg_bin,
        "-y",
        "-i",
        str(input_path),
        "-loop",
        "1",
        "-i",
        str(mask_path),
        "-filter_complex",
        (
            "[0:v]split=2[base][tmp];"
            "[tmp]boxblur=luma_radius=18:luma_power=2:chroma_radius=18:chroma_power=2[blur];"
            "[1:v]format=gray[mask];"
            "[base][blur][mask]maskedmerge[vout]"
        ),
        "-map",
        "[vout]",
        "-map",
        "0:a?",
        "-c:v",
        cfg.ffmpeg_vcodec,
        "-preset",
        cfg.ffmpeg_preset,
        "-crf",
        str(cfg.ffmpeg_crf),
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        "-shortest",
        str(output_path),
    ]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        logging.error("ffmpeg sanitizer failed: %s", (proc.stderr or "").strip()[-400:])
        return False
    return True


def _copy_video(input_path: Path, output_path: Path, ffmpeg_bin: str) -> bool:
    cmd = [ffmpeg_bin, "-y", "-i", str(input_path), "-c", "copy", str(output_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode == 0 and output_path.exists():
        return True
    try:
        shutil.copy2(input_path, output_path)
        return output_path.exists()
    except Exception:
        return False


def _mask_area_fraction(width: int, height: int, detections: Sequence[Dict[str, Any]]) -> float:
    if width <= 0 or height <= 0:
        return 0.0
    mask = np.zeros((height, width), dtype=np.uint8)
    for det in detections:
        bbox = det.get("bbox") if isinstance(det, dict) else None
        if not bbox:
            continue
        clipped = _clip_bbox(bbox, width, height)
        if not clipped:
            continue
        x, y, w, h = clipped
        mask[y : y + h, x : x + w] = 1
    return float(mask.mean())


def _save_report(report: Dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def sanitize_video(
    input_path: str,
    output_dir: str | Path,
    cfg: Optional[SanitizerConfig] = None,
) -> Dict[str, Any]:
    cfg = cfg or SanitizerConfig.from_env()
    in_path = Path(input_path).resolve()
    out_dir = Path(output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    output_path = out_dir / f"{in_path.stem}_sanitized.mp4"
    report_path = out_dir / f"{in_path.stem}_sanitizer_report.json"

    report: Dict[str, Any] = {
        "input": str(in_path),
        "output": str(output_path),
        "status": "error",
        "detections": [],
        "frames_sampled": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    if not in_path.exists():
        report["error"] = "input_not_found"
        report["output"] = ""
        report["report_path"] = str(report_path)
        _save_report(report, report_path)
        return report

    frames = sample_frames(str(in_path), sample_fps=cfg.sample_fps, max_frames=cfg.max_frames)
    report["frames_sampled"] = len(frames)
    if not frames:
        report["error"] = "frames_not_sampled"
        report["output"] = ""
        report["report_path"] = str(report_path)
        _save_report(report, report_path)
        return report

    h, w = frames[0].shape[:2]
    qr_detections = detect_qr(frames)
    overlay_detections = detect_static_overlays(frames)
    detections = merge_bboxes([*qr_detections, *overlay_detections], iou_threshold=0.2)

    report["detections"] = detections
    mask_area = _mask_area_fraction(w, h, detections)
    report["mask_area"] = round(mask_area, 4)

    if not detections:
        copied = _copy_video(in_path, output_path, cfg.ffmpeg_bin)
        report["status"] = "clean" if copied else "error"
        if not copied:
            report["error"] = "copy_failed"
            report["output"] = ""
    elif mask_area > cfg.max_mask_area:
        report["status"] = "blocked"
        report["output"] = ""
        report["blocked_reason"] = "mask_area_exceeded"
    else:
        mask_path: Optional[Path] = None
        try:
            mask_path = build_mask(w, h, detections)
            blurred = apply_blur_ffmpeg(str(in_path), str(mask_path), str(output_path), cfg=cfg)
            if blurred and output_path.exists():
                report["status"] = "sanitized"
            else:
                report["status"] = "error"
                report["output"] = ""
                report["error"] = "ffmpeg_blur_failed"
        finally:
            if mask_path and mask_path.exists():
                try:
                    mask_path.unlink()
                except Exception:
                    pass

    report["report_path"] = str(report_path)
    _save_report(report, report_path)
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sanitize a video by blurring risky regions only.")
    parser.add_argument("--input", required=True, help="Input MP4 path")
    parser.add_argument("--output-dir", required=True, help="Output folder for sanitized MP4 and report")
    parser.add_argument("--sample-fps", type=int, help="Frame sampling fps")
    parser.add_argument("--max-frames", type=int, help="Maximum sampled frames")
    parser.add_argument("--max-mask-area", type=float, help="Maximum allowed ROI area fraction")
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(message)s")
    args = _parse_args()
    cfg = SanitizerConfig.from_env()
    if args.sample_fps:
        cfg.sample_fps = max(1, int(args.sample_fps))
    if args.max_frames:
        cfg.max_frames = max(1, int(args.max_frames))
    if args.max_mask_area is not None:
        cfg.max_mask_area = float(args.max_mask_area)

    report = sanitize_video(args.input, args.output_dir, cfg=cfg)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
