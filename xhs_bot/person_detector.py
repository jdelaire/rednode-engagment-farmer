"""Lightweight person detection helpers.

Detection relies on OpenCV's Haar cascades when available; if OpenCV is not
installed we fall back to returning ``None`` (unknown).
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Optional

try:
    import cv2  # type: ignore
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    cv2 = None  # type: ignore
    np = None  # type: ignore


@dataclass
class DetectionResult:
    has_person: Optional[bool]
    faces_detected: int
    backend: str
    error: Optional[str] = None

    @property
    def label(self) -> str:
        if self.has_person is True:
            return "yes"
        if self.has_person is False:
            return "no"
        return "unknown"


def detect_person(image_bytes: bytes) -> DetectionResult:
    """Return best-effort detection result for the provided image."""
    if not image_bytes:
        return DetectionResult(has_person=None, faces_detected=0, backend="none", error="empty-bytes")

    if cv2 is None or np is None:
        return DetectionResult(has_person=None, faces_detected=0, backend="none", error="opencv-missing")

    try:
        np_arr = np.frombuffer(image_bytes, dtype=np.uint8)
        img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        if img is None:
            return DetectionResult(has_person=None, faces_detected=0, backend="opencv", error="decode-failed")
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")  # type: ignore[attr-defined]
        if cascade.empty():
            return DetectionResult(has_person=None, faces_detected=0, backend="opencv", error="cascade-missing")
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))
        return DetectionResult(has_person=len(faces) > 0, faces_detected=len(faces), backend="opencv")
    except Exception as exc:  # pragma: no cover - best effort
        return DetectionResult(has_person=None, faces_detected=0, backend="opencv", error=str(exc))


def data_url_to_bytes(data_url: str) -> Optional[bytes]:
    try:
        header, encoded = data_url.split(",", 1)
    except ValueError:
        return None
    try:
        return base64.b64decode(encoded)
    except Exception:
        return None
