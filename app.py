"""Single-user web app for CSRT video tracking.

The browser handles upload and ROI selection. OpenCV performs tracking in one
background worker, and each completed run is packaged as a downloadable ZIP.
"""

from __future__ import annotations

import csv
import json
import os
import shutil
import threading
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
os.environ.setdefault("MPLCONFIGDIR", str(BASE_DIR / ".matplotlib-web"))

import cv2
import matplotlib
import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

matplotlib.use("Agg")
import matplotlib.pyplot as plt


WEB_DIR = BASE_DIR / "web"
RUNTIME_DIR = Path(os.getenv("RUNTIME_DIR", BASE_DIR / "runtime_data")).resolve()
VIDEO_DIR = RUNTIME_DIR / "videos"
JOB_DIR = RUNTIME_DIR / "jobs"
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_MB", "250")) * 1024 * 1024
RETENTION_SECONDS = int(os.getenv("RETENTION_HOURS", "6")) * 60 * 60
ALLOWED_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".m4v"}

STATE_LOCK = threading.Lock()
VIDEOS: dict[str, dict[str, Any]] = {}
JOBS: dict[str, dict[str, Any]] = {}
EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tracker")


class TrackRequest(BaseModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(ge=3)
    height: int = Field(ge=3)


def safe_display_name(filename: str | None) -> str:
    name = Path(filename or "video.mp4").name
    return name[:160] or "video.mp4"


def safe_stem(filename: str) -> str:
    cleaned = "".join(character if character.isalnum() else "_" for character in Path(filename).stem)
    return cleaned.strip("_")[:80] or "video"


def create_tracker():
    if hasattr(cv2, "TrackerCSRT_create"):
        return cv2.TrackerCSRT_create()
    if hasattr(cv2, "legacy") and hasattr(cv2.legacy, "TrackerCSRT_create"):
        return cv2.legacy.TrackerCSRT_create()
    raise RuntimeError("The installed OpenCV build does not include the CSRT tracker.")


def video_metadata(video_path: Path) -> tuple[dict[str, Any], np.ndarray]:
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise ValueError("OpenCV could not open this video.")
    try:
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        ok, frame = capture.read()
    finally:
        capture.release()

    if not ok or frame is None:
        raise ValueError("The first frame could not be decoded.")
    if frame_count <= 0 or fps <= 0 or width <= 0 or height <= 0:
        raise ValueError("The video metadata is incomplete or invalid.")
    return (
        {
            "frame_count": frame_count,
            "fps": fps,
            "width": width,
            "height": height,
            "duration_seconds": frame_count / fps,
        },
        frame,
    )


def update_job(job_id: str, **values: Any) -> None:
    with STATE_LOCK:
        if job_id in JOBS:
            JOBS[job_id].update(values)


def remove_stale_runtime_files() -> None:
    cutoff = time.time() - RETENTION_SECONDS
    for parent in (VIDEO_DIR, JOB_DIR):
        if not parent.exists():
            continue
        for child in parent.iterdir():
            try:
                if child.stat().st_mtime >= cutoff:
                    continue
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
            except OSError:
                pass


def write_trajectory_plot(csv_path: Path, output_path: Path, title: str) -> None:
    data = np.genfromtxt(csv_path, delimiter=",", names=True, dtype=float)
    data = np.atleast_1d(data)
    success = data["tracking_success"] == 1
    if not np.any(success):
        raise RuntimeError("The tracker did not produce any successful positions.")

    elapsed = data["time_seconds"] - data["time_seconds"][0]
    x_position = data["center_x_px"].copy()
    y_position = data["center_y_px"].copy()
    x_position[~success] = np.nan
    y_position[~success] = np.nan
    accent = "#20B15A"

    figure, axes = plt.subplots(1, 3, figsize=(15, 4.8))
    axes[0].plot(x_position, y_position, color=accent, linewidth=2.2)
    axes[0].invert_yaxis()
    axes[0].set_aspect("equal", adjustable="box")
    axes[0].set_title("Tracked path")
    axes[0].set_xlabel("X position (pixels)")
    axes[0].set_ylabel("Y position (pixels)")

    axes[1].plot(elapsed, x_position, color=accent, linewidth=2.0)
    axes[1].set_title("Horizontal position")
    axes[1].set_xlabel("Elapsed time (s)")
    axes[1].set_ylabel("X position (pixels)")

    axes[2].plot(elapsed, y_position, color=accent, linewidth=2.0)
    axes[2].invert_yaxis()
    axes[2].set_title("Vertical position")
    axes[2].set_xlabel("Elapsed time (s)")
    axes[2].set_ylabel("Y position (pixels)")

    for axis in axes:
        axis.grid(True, alpha=0.22)
    figure.suptitle(f"Motion tracking — {title}", y=0.99, fontsize=15)
    figure.tight_layout(rect=(0, 0, 1, 0.93))
    figure.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(figure)


def process_tracking_job(job_id: str, video_record: dict[str, Any], bbox: tuple[int, int, int, int]) -> None:
    job_path = JOB_DIR / job_id
    job_path.mkdir(parents=True, exist_ok=True)
    source_path = Path(video_record["path"])
    display_name = str(video_record["filename"])
    stem = safe_stem(display_name)
    video_output = job_path / f"{stem}_tracked.mp4"
    csv_output = job_path / f"{stem}_tracking.csv"
    plot_output = job_path / f"{stem}_trajectory.png"
    settings_output = job_path / f"{stem}_settings.json"
    zip_output = job_path / f"{stem}_tracking_results.zip"

    capture: cv2.VideoCapture | None = None
    writer: cv2.VideoWriter | None = None
    try:
        update_job(job_id, status="processing", message="Opening video", progress=1)
        capture = cv2.VideoCapture(str(source_path))
        if not capture.isOpened():
            raise RuntimeError("The uploaded video could not be reopened.")

        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        ok, first_frame = capture.read()
        if not ok or first_frame is None:
            raise RuntimeError("The first frame could not be decoded.")

        x, y, box_width, box_height = bbox
        if x + box_width > width or y + box_height > height:
            raise RuntimeError("The selected box extends outside the video frame.")

        tracker = create_tracker()
        tracker.init(first_frame, bbox)
        writer = cv2.VideoWriter(
            str(video_output),
            cv2.VideoWriter_fourcc(*"mp4v"),
            fps,
            (width, height),
        )
        if not writer.isOpened():
            raise RuntimeError("The annotated MP4 output could not be created.")

        successful_frames = 0
        failed_frames = 0
        with csv_output.open("w", newline="", encoding="utf-8") as csv_file:
            csv_writer = csv.writer(csv_file)
            csv_writer.writerow(
                [
                    "frame_number",
                    "time_seconds",
                    "center_x_px",
                    "center_y_px",
                    "box_x_px",
                    "box_y_px",
                    "box_width_px",
                    "box_height_px",
                    "tracking_success",
                ]
            )

            frame_number = 0
            frame = first_frame
            while True:
                if frame_number == 0:
                    success = True
                    current_bbox = tuple(float(value) for value in bbox)
                else:
                    success, current_bbox = tracker.update(frame)

                if success:
                    current_x, current_y, current_width, current_height = current_bbox
                    center_x = current_x + current_width / 2
                    center_y = current_y + current_height / 2
                    successful_frames += 1
                    csv_writer.writerow(
                        [
                            frame_number,
                            frame_number / fps,
                            center_x,
                            center_y,
                            current_x,
                            current_y,
                            current_width,
                            current_height,
                            1,
                        ]
                    )
                    cv2.rectangle(
                        frame,
                        (round(current_x), round(current_y)),
                        (round(current_x + current_width), round(current_y + current_height)),
                        (50, 220, 95),
                        3,
                    )
                else:
                    failed_frames += 1
                    csv_writer.writerow([frame_number, frame_number / fps] + [""] * 6 + [0])
                    cv2.putText(
                        frame,
                        "TRACKING FAILURE",
                        (30, 72),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        1.0,
                        (0, 0, 255),
                        3,
                        cv2.LINE_AA,
                    )

                cv2.putText(
                    frame,
                    f"Frame {frame_number + 1} / {frame_count}",
                    (30, 36),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.78,
                    (50, 220, 95),
                    2,
                    cv2.LINE_AA,
                )
                writer.write(frame)

                completed = frame_number + 1
                if completed == frame_count or completed % 5 == 0:
                    progress = min(92, 3 + round(89 * completed / frame_count))
                    update_job(
                        job_id,
                        progress=progress,
                        current_frame=completed,
                        total_frames=frame_count,
                        message=f"Tracking frame {completed} of {frame_count}",
                    )

                ok, next_frame = capture.read()
                if not ok or next_frame is None:
                    break
                frame_number += 1
                frame = next_frame

        capture.release()
        capture = None
        writer.release()
        writer = None

        update_job(job_id, progress=94, message="Creating plots")
        write_trajectory_plot(csv_output, plot_output, display_name)
        settings = {
            "source_filename": display_name,
            "tracker": "CSRT",
            "initial_bbox_xywh": list(bbox),
            "fps": fps,
            "frame_count": frame_count,
            "frame_width": width,
            "frame_height": height,
            "successful_frames": successful_frames,
            "failed_frames": failed_frames,
        }
        settings_output.write_text(json.dumps(settings, indent=2), encoding="utf-8")

        update_job(job_id, progress=97, message="Packaging results")
        with zipfile.ZipFile(zip_output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for result_path in (video_output, csv_output, plot_output, settings_output):
                archive.write(result_path, arcname=result_path.name)

        update_job(
            job_id,
            status="complete",
            progress=100,
            message="Results ready",
            successful_frames=successful_frames,
            failed_frames=failed_frames,
            zip_path=str(zip_output),
            download_name=zip_output.name,
        )
    except Exception as error:
        update_job(job_id, status="error", message=str(error), error=str(error))
    finally:
        if capture is not None:
            capture.release()
        if writer is not None:
            writer.release()


@asynccontextmanager
async def lifespan(_: FastAPI):
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    JOB_DIR.mkdir(parents=True, exist_ok=True)
    remove_stale_runtime_files()
    yield
    EXECUTOR.shutdown(wait=False, cancel_futures=True)


app = FastAPI(title="Motion Tracker", version="1.0.0", lifespan=lifespan)
app.mount("/assets", StaticFiles(directory=WEB_DIR), name="assets")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/healthz")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/videos")
async def upload_video(file: UploadFile = File(...)) -> dict[str, Any]:
    remove_stale_runtime_files()
    filename = safe_display_name(file.filename)
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Please upload an MP4, MOV, AVI, MKV, or M4V video.")

    video_id = uuid.uuid4().hex
    video_folder = VIDEO_DIR / video_id
    video_folder.mkdir(parents=True, exist_ok=False)
    source_path = video_folder / f"source{extension}"
    size = 0
    try:
        with source_path.open("wb") as destination:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Video exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB upload limit.",
                    )
                destination.write(chunk)
        metadata, first_frame = video_metadata(source_path)
        preview_path = video_folder / "first_frame.jpg"
        if not cv2.imwrite(str(preview_path), first_frame, [cv2.IMWRITE_JPEG_QUALITY, 92]):
            raise ValueError("The first-frame preview could not be created.")
    except HTTPException:
        shutil.rmtree(video_folder, ignore_errors=True)
        raise
    except Exception as error:
        shutil.rmtree(video_folder, ignore_errors=True)
        raise HTTPException(status_code=422, detail=str(error)) from error
    finally:
        await file.close()

    record = {
        "id": video_id,
        "filename": filename,
        "path": str(source_path),
        "preview_path": str(preview_path),
        "size_bytes": size,
        **metadata,
    }
    with STATE_LOCK:
        VIDEOS[video_id] = record

    return {
        "video_id": video_id,
        "filename": filename,
        "preview_url": f"/api/videos/{video_id}/frame",
        "size_bytes": size,
        **metadata,
    }


@app.get("/api/videos/{video_id}/frame")
def first_frame(video_id: str) -> FileResponse:
    with STATE_LOCK:
        record = VIDEOS.get(video_id)
    if not record:
        raise HTTPException(status_code=404, detail="Video session not found. Please upload the video again.")
    preview_path = Path(record["preview_path"])
    if not preview_path.is_file():
        raise HTTPException(status_code=404, detail="First-frame preview not found.")
    return FileResponse(preview_path, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.post("/api/videos/{video_id}/track", status_code=202)
def start_tracking(video_id: str, request: TrackRequest) -> dict[str, str]:
    with STATE_LOCK:
        record = VIDEOS.get(video_id)
    if not record:
        raise HTTPException(status_code=404, detail="Video session not found. Please upload the video again.")
    if request.x + request.width > int(record["width"]) or request.y + request.height > int(record["height"]):
        raise HTTPException(status_code=422, detail="The selected box extends outside the video frame.")

    job_id = uuid.uuid4().hex
    job = {
        "id": job_id,
        "video_id": video_id,
        "status": "queued",
        "progress": 0,
        "message": "Waiting to start",
        "current_frame": 0,
        "total_frames": int(record["frame_count"]),
        "created_at": time.time(),
    }
    with STATE_LOCK:
        JOBS[job_id] = job
    EXECUTOR.submit(
        process_tracking_job,
        job_id,
        dict(record),
        (request.x, request.y, request.width, request.height),
    )
    return {"job_id": job_id, "status_url": f"/api/jobs/{job_id}"}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> dict[str, Any]:
    with STATE_LOCK:
        job = dict(JOBS.get(job_id, {}))
    if not job:
        raise HTTPException(status_code=404, detail="Tracking job not found.")
    job.pop("zip_path", None)
    if job["status"] == "complete":
        job["download_url"] = f"/api/jobs/{job_id}/download"
    return job


@app.get("/api/jobs/{job_id}/download")
def download_results(job_id: str) -> FileResponse:
    with STATE_LOCK:
        job = dict(JOBS.get(job_id, {}))
    if not job:
        raise HTTPException(status_code=404, detail="Tracking job not found.")
    if job.get("status") != "complete":
        raise HTTPException(status_code=409, detail="Tracking results are not ready yet.")
    zip_path = Path(job["zip_path"])
    if not zip_path.is_file():
        raise HTTPException(status_code=404, detail="The results archive has expired.")
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=str(job["download_name"]),
    )


if __name__ == "__main__":
    import uvicorn

    if os.getenv("OPEN_BROWSER") == "1":
        import webbrowser

        threading.Timer(1.2, lambda: webbrowser.open("http://127.0.0.1:8000")).start()
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
