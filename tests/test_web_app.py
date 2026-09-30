import time
import zipfile
from io import BytesIO
from pathlib import Path
import sys

import cv2
import numpy as np
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as tracker_app


def make_test_video(path: Path) -> None:
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        20.0,
        (320, 240),
    )
    assert writer.isOpened()
    for index in range(30):
        frame = np.full((240, 320, 3), 245, dtype=np.uint8)
        x = 40 + index
        cv2.rectangle(frame, (x, 90), (x + 44, 134), (20, 170, 70), -1)
        cv2.line(frame, (x, 90), (x + 44, 134), (0, 0, 0), 3)
        cv2.line(frame, (x + 44, 90), (x, 134), (0, 0, 0), 3)
        writer.write(frame)
    writer.release()


def test_complete_tracking_workflow(tmp_path: Path) -> None:
    video_path = tmp_path / "synthetic.mp4"
    make_test_video(video_path)

    with TestClient(tracker_app.app) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        assert "Motion Tracker" in client.get("/").text

        with video_path.open("rb") as video_file:
            upload = client.post(
                "/api/videos",
                files={"file": (video_path.name, video_file, "video/mp4")},
            )
        assert upload.status_code == 200, upload.text
        uploaded = upload.json()
        assert uploaded["frame_count"] == 30
        assert client.get(uploaded["preview_url"]).status_code == 200

        start = client.post(
            f"/api/videos/{uploaded['video_id']}/track",
            json={"x": 36, "y": 86, "width": 53, "height": 53},
        )
        assert start.status_code == 202, start.text
        job_id = start.json()["job_id"]

        deadline = time.time() + 45
        status = {}
        while time.time() < deadline:
            status_response = client.get(f"/api/jobs/{job_id}")
            assert status_response.status_code == 200
            status = status_response.json()
            if status["status"] in {"complete", "error"}:
                break
            time.sleep(0.1)

        assert status["status"] == "complete", status
        assert status["progress"] == 100
        assert status["successful_frames"] > 0

        plot = client.get(status["plot_url"])
        assert plot.status_code == 200
        assert plot.headers["content-type"] == "image/png"
        assert len(plot.content) > 1_000

        download = client.get(status["download_url"])
        assert download.status_code == 200
        with zipfile.ZipFile(BytesIO(download.content)) as archive:
            names = set(archive.namelist())
        assert names == {
            "synthetic_tracked.mp4",
            "synthetic_tracking.csv",
            "synthetic_trajectory.png",
            "synthetic_settings.json",
        }
