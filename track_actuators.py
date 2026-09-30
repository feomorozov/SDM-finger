"""Interactive local tracker for the firm and soft actuator videos.

Run this file from the project folder. For each video, choose the frame range
in the terminal and draw a tight box around the feature you want to track.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
os.environ.setdefault("MPLCONFIGDIR", str(PROJECT_DIR / ".matplotlib"))

import cv2
import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt


DEFAULT_VIDEOS = ("firmTrim.mp4", "softTrim.mp4")
OUTPUT_DIR = PROJECT_DIR / "tracking_outputs"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Track one selected actuator feature in each video."
    )
    parser.add_argument(
        "videos",
        nargs="*",
        default=list(DEFAULT_VIDEOS),
        help="Video filenames or paths (defaults: firmTrim.mp4 and softTrim.mp4)",
    )
    parser.add_argument(
        "--start-frame",
        type=int,
        help="Use this starting frame for every video instead of prompting.",
    )
    parser.add_argument(
        "--end-frame",
        type=int,
        help="Use this inclusive ending frame for every video instead of prompting.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check the installation and videos without opening the ROI selector.",
    )
    return parser.parse_args()


def resolve_video(path_text: str) -> Path:
    path = Path(path_text)
    if not path.is_absolute():
        path = PROJECT_DIR / path
    return path.resolve()


def open_video(path: Path) -> cv2.VideoCapture:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open video: {path}")
    return capture


def video_info(capture: cv2.VideoCapture) -> dict[str, float | int]:
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if frame_count <= 0 or fps <= 0 or width <= 0 or height <= 0:
        raise RuntimeError("The video metadata is incomplete or invalid.")
    return {
        "frame_count": frame_count,
        "fps": fps,
        "width": width,
        "height": height,
        "duration_seconds": frame_count / fps,
    }


def prompt_frame(label: str, default: int, minimum: int, maximum: int) -> int:
    while True:
        response = input(f"{label} [{default}]: ").strip()
        if not response:
            return default
        try:
            value = int(response)
        except ValueError:
            print("Please enter a whole-number frame index.")
            continue
        if minimum <= value <= maximum:
            return value
        print(f"Please choose a frame from {minimum} through {maximum}.")


def choose_frame_range(
    info: dict[str, float | int],
    requested_start: int | None,
    requested_end: int | None,
) -> tuple[int, int]:
    last_frame = int(info["frame_count"]) - 1
    if requested_start is None:
        start_frame = prompt_frame("Starting frame", 0, 0, last_frame)
    else:
        start_frame = requested_start
    if not 0 <= start_frame <= last_frame:
        raise ValueError(f"Start frame must be between 0 and {last_frame}.")

    if requested_end is None:
        end_frame = prompt_frame("Ending frame (inclusive)", last_frame, start_frame, last_frame)
    else:
        end_frame = requested_end
    if not start_frame <= end_frame <= last_frame:
        raise ValueError(
            f"End frame must be between the start frame ({start_frame}) and {last_frame}."
        )
    return start_frame, end_frame


def read_frame(capture: cv2.VideoCapture, frame_number: int) -> np.ndarray:
    capture.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
    ok, frame = capture.read()
    if not ok or frame is None:
        raise RuntimeError(f"Could not read frame {frame_number}.")
    return frame


def scaled_for_screen(
    frame: np.ndarray, max_width: int = 1200, max_height: int = 800
) -> tuple[np.ndarray, float]:
    height, width = frame.shape[:2]
    scale = min(max_width / width, max_height / height, 1.0)
    if scale == 1.0:
        return frame.copy(), scale
    display = cv2.resize(
        frame,
        (round(width * scale), round(height * scale)),
        interpolation=cv2.INTER_AREA,
    )
    return display, scale


def select_tracking_box(frame: np.ndarray, video_name: str, frame_number: int) -> tuple[int, int, int, int]:
    display, scale = scaled_for_screen(frame)
    instructions = "Drag box; ENTER/SPACE accepts; C cancels"
    cv2.putText(
        display,
        instructions,
        (12, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (0, 255, 255),
        2,
        cv2.LINE_AA,
    )
    title = f"Select target - {video_name} - frame {frame_number}"

    while True:
        selected = cv2.selectROI(title, display, showCrosshair=True, fromCenter=False)
        cv2.destroyWindow(title)
        x, y, width, height = (int(value) for value in selected)
        if width == 0 or height == 0:
            raise KeyboardInterrupt("ROI selection was cancelled.")

        original = (
            round(x / scale),
            round(y / scale),
            max(1, round(width / scale)),
            max(1, round(height / scale)),
        )
        print(f"Selected box in original pixels: {original}")
        response = input("Use this tracking box? [Y/n]: ").strip().lower()
        if response in ("", "y", "yes"):
            return original
        print("Select the box again.")


def create_tracker():
    if hasattr(cv2, "TrackerCSRT_create"):
        return cv2.TrackerCSRT_create()
    if hasattr(cv2, "legacy") and hasattr(cv2.legacy, "TrackerCSRT_create"):
        return cv2.legacy.TrackerCSRT_create()
    raise RuntimeError(
        "This OpenCV installation does not include the CSRT tracker. "
        "Install opencv-contrib-python, not opencv-python-headless."
    )


def write_plot(csv_path: Path, plot_path: Path, video_name: str) -> None:
    data = np.genfromtxt(csv_path, delimiter=",", names=True, dtype=float)
    if data.size == 0:
        return
    data = np.atleast_1d(data)
    good = data["tracking_success"] == 1
    if not np.any(good):
        return

    time_seconds = data["time_seconds"][good]
    x_position = data["center_x_px"][good]
    y_position = data["center_y_px"][good]

    figure, axes = plt.subplots(1, 3, figsize=(15, 4.5))
    scatter = axes[0].scatter(x_position, y_position, c=time_seconds, s=10, cmap="viridis")
    axes[0].invert_yaxis()
    axes[0].set_aspect("equal", adjustable="box")
    axes[0].set_title("Tracked path")
    axes[0].set_xlabel("X position (pixels)")
    axes[0].set_ylabel("Y position (pixels)")
    figure.colorbar(scatter, ax=axes[0], label="Time (s)")

    axes[1].plot(time_seconds, x_position)
    axes[1].set_title("Horizontal position")
    axes[1].set_xlabel("Time (s)")
    axes[1].set_ylabel("X position (pixels)")

    axes[2].plot(time_seconds, y_position)
    axes[2].invert_yaxis()
    axes[2].set_title("Vertical position")
    axes[2].set_xlabel("Time (s)")
    axes[2].set_ylabel("Y position (pixels)")

    for axis in axes:
        axis.grid(True, alpha=0.3)
    figure.suptitle(f"CSRT tracking: {video_name}")
    figure.tight_layout()
    figure.savefig(plot_path, dpi=180)
    plt.close(figure)


def write_combined_plot(video_paths: list[Path], plot_path: Path) -> bool:
    """Overlay completed tracking results in the same three-panel layout."""
    preferred_styles = {
        "firmtrim": ("Firm", "#D55E00"),
        "softtrim": ("Soft", "#0072B2"),
    }
    series: list[dict[str, object]] = []

    for index, video_path in enumerate(video_paths):
        csv_path = OUTPUT_DIR / f"{video_path.stem}_tracking.csv"
        if not csv_path.is_file():
            print(f"Skipping combined plot; tracking CSV is missing: {csv_path.name}")
            return False

        data = np.genfromtxt(csv_path, delimiter=",", names=True, dtype=float)
        data = np.atleast_1d(data)
        if data.size == 0:
            print(f"Skipping combined plot; tracking CSV is empty: {csv_path.name}")
            return False

        success = data["tracking_success"] == 1
        if not np.any(success):
            print(f"Skipping combined plot; no successful points: {csv_path.name}")
            return False

        key = video_path.stem.lower()
        default_colors = ("#009E73", "#CC79A7", "#E69F00", "#56B4E9")
        label, color = preferred_styles.get(
            key, (video_path.stem, default_colors[index % len(default_colors)])
        )
        time_seconds = data["time_seconds"].copy()
        time_seconds -= time_seconds[0]
        x_position = data["center_x_px"].copy()
        y_position = data["center_y_px"].copy()
        x_position[~success] = np.nan
        y_position[~success] = np.nan
        series.append(
            {
                "label": label,
                "color": color,
                "time": time_seconds,
                "x": x_position,
                "y": y_position,
            }
        )

    figure, axes = plt.subplots(1, 3, figsize=(15, 4.8))
    for item in series:
        label = str(item["label"])
        color = str(item["color"])
        time_seconds = np.asarray(item["time"])
        x_position = np.asarray(item["x"])
        y_position = np.asarray(item["y"])

        axes[0].plot(x_position, y_position, color=color, linewidth=2.2, label=label)
        axes[1].plot(time_seconds, x_position, color=color, linewidth=2.0, label=label)
        axes[2].plot(time_seconds, y_position, color=color, linewidth=2.0, label=label)

    axes[0].invert_yaxis()
    axes[0].set_aspect("equal", adjustable="box")
    axes[0].set_title("Tracked path")
    axes[0].set_xlabel("X position (pixels)")
    axes[0].set_ylabel("Y position (pixels)")

    axes[1].set_title("Horizontal position")
    axes[1].set_xlabel("Elapsed time (s)")
    axes[1].set_ylabel("X position (pixels)")

    axes[2].invert_yaxis()
    axes[2].set_title("Vertical position")
    axes[2].set_xlabel("Elapsed time (s)")
    axes[2].set_ylabel("Y position (pixels)")

    for axis in axes:
        axis.grid(True, alpha=0.3)
    handles, labels = axes[0].get_legend_handles_labels()
    figure.suptitle("Firm vs. Soft Actuator Tracking", y=0.99, fontsize=15)
    figure.legend(
        handles,
        labels,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.945),
        ncol=len(series),
        frameon=False,
    )
    figure.tight_layout(rect=(0, 0, 1, 0.86))
    figure.savefig(plot_path, dpi=200, bbox_inches="tight")
    plt.close(figure)
    return True


def track_video(
    video_path: Path,
    start_frame: int | None,
    end_frame: int | None,
) -> dict[str, object]:
    capture = open_video(video_path)
    info = video_info(capture)
    print(
        f"\n{video_path.name}: {info['width']} x {info['height']}, "
        f"{info['frame_count']} frames, {info['fps']:.3f} fps, "
        f"{info['duration_seconds']:.2f} seconds"
    )

    selected_start, selected_end = choose_frame_range(info, start_frame, end_frame)
    first_frame = read_frame(capture, selected_start)
    print("A selection window will open. Draw a tight box around a distinctive target.")
    bbox = select_tracking_box(first_frame, video_path.name, selected_start)

    tracker = create_tracker()
    tracker.init(first_frame, bbox)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = video_path.stem
    video_output = OUTPUT_DIR / f"{stem}_tracked.mp4"
    csv_output = OUTPUT_DIR / f"{stem}_tracking.csv"
    plot_output = OUTPUT_DIR / f"{stem}_trajectory.png"
    settings_output = OUTPUT_DIR / f"{stem}_settings.json"

    writer = cv2.VideoWriter(
        str(video_output),
        cv2.VideoWriter_fourcc(*"mp4v"),
        float(info["fps"]),
        (int(info["width"]), int(info["height"])),
    )
    if not writer.isOpened():
        capture.release()
        raise RuntimeError(f"Could not create output video: {video_output}")

    total_selected = selected_end - selected_start + 1
    success_count = 0
    failure_count = 0

    try:
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

            capture.set(cv2.CAP_PROP_POS_FRAMES, selected_start)
            for offset in range(total_selected):
                frame_number = selected_start + offset
                ok, frame = capture.read()
                if not ok or frame is None:
                    print(f"Stopped early: could not read frame {frame_number}.")
                    break

                if offset == 0:
                    success = True
                    current_bbox = tuple(float(value) for value in bbox)
                else:
                    success, current_bbox = tracker.update(frame)

                if success:
                    x, y, width, height = current_bbox
                    center_x = x + width / 2
                    center_y = y + height / 2
                    success_count += 1
                    cv2.rectangle(
                        frame,
                        (round(x), round(y)),
                        (round(x + width), round(y + height)),
                        (255, 0, 0),
                        3,
                    )
                    row = [
                        frame_number,
                        frame_number / float(info["fps"]),
                        center_x,
                        center_y,
                        x,
                        y,
                        width,
                        height,
                        1,
                    ]
                else:
                    failure_count += 1
                    cv2.putText(
                        frame,
                        "TRACKING FAILURE",
                        (30, 70),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        1.0,
                        (0, 0, 255),
                        3,
                        cv2.LINE_AA,
                    )
                    row = [frame_number, frame_number / float(info["fps"])] + [""] * 6 + [0]

                cv2.putText(
                    frame,
                    f"Frame {frame_number} / {selected_end}",
                    (30, 35),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (50, 220, 50),
                    2,
                    cv2.LINE_AA,
                )
                csv_writer.writerow(row)
                writer.write(frame)

                completed = offset + 1
                if completed % 50 == 0 or completed == total_selected:
                    print(f"Processed {completed}/{total_selected} frames")
    finally:
        capture.release()
        writer.release()
        cv2.destroyAllWindows()

    settings = {
        "source_video": str(video_path),
        "tracker": "CSRT",
        "start_frame": selected_start,
        "end_frame": selected_end,
        "initial_bbox_xywh": list(bbox),
        "fps": info["fps"],
        "frame_width": info["width"],
        "frame_height": info["height"],
        "successful_frames": success_count,
        "failed_frames": failure_count,
    }
    settings_output.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    write_plot(csv_output, plot_output, video_path.name)

    print(f"Finished {video_path.name}: {success_count} successful, {failure_count} failed")
    print(f"  Video:    {video_output}")
    print(f"  CSV:      {csv_output}")
    print(f"  Plot:     {plot_output}")
    print(f"  Settings: {settings_output}")
    return settings


def check_setup(video_paths: list[Path]) -> int:
    print(f"Python: {sys.version.split()[0]}")
    print(f"OpenCV: {cv2.__version__}")
    print(f"NumPy: {np.__version__}")
    create_tracker()
    print("CSRT tracker: available")

    all_ok = True
    for path in video_paths:
        if not path.is_file():
            print(f"MISSING: {path}")
            all_ok = False
            continue
        try:
            capture = open_video(path)
            info = video_info(capture)
            frame = read_frame(capture, 0)
            capture.release()
            print(
                f"OK: {path.name} | {info['width']}x{info['height']} | "
                f"{info['frame_count']} frames | {info['fps']:.3f} fps | "
                f"first frame {frame.shape[1]}x{frame.shape[0]}"
            )
        except Exception as error:
            print(f"ERROR: {path.name}: {error}")
            all_ok = False
    return 0 if all_ok else 1


def main() -> int:
    args = parse_args()
    video_paths = [resolve_video(value) for value in args.videos]
    if args.check:
        return check_setup(video_paths)

    missing = [path for path in video_paths if not path.is_file()]
    if missing:
        for path in missing:
            print(f"Video not found: {path}", file=sys.stderr)
        return 1

    print("Interactive CSRT actuator tracking")
    print("Frame numbering starts at 0. Press Enter to accept each default.")
    try:
        for video_path in video_paths:
            track_video(video_path, args.start_frame, args.end_frame)
    except KeyboardInterrupt:
        cv2.destroyAllWindows()
        print("\nTracking cancelled. No remaining videos were processed.")
        return 130
    except Exception as error:
        cv2.destroyAllWindows()
        print(f"\nERROR: {error}", file=sys.stderr)
        return 1

    if len(video_paths) > 1:
        combined_plot = OUTPUT_DIR / "firm_vs_soft_three_panel.png"
        if write_combined_plot(video_paths, combined_plot):
            print(f"Combined panel: {combined_plot}")

    print(f"\nAll requested videos are complete. Results are in: {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
