# Local actuator tracking

The original class notebook is preserved unchanged. The local tracker processes:

- `firmTrim.mp4`
- `softTrim.mp4`

## Run it

Double-click **Run Tracking.cmd**.

For each video:

1. Enter a starting frame, or press Enter to start at frame 0.
2. Enter an ending frame, or press Enter to use the entire video.
3. In the image window, drag a tight box around the feature to track.
4. Press Enter or Space to accept the box. Press C to cancel it.
5. Return to the terminal and confirm the box. Enter `n` to redraw it.

The script then tracks the selected feature with OpenCV's CSRT tracker.

## Results

Results are written to `tracking_outputs` with separate names for the firm and
soft actuators:

- an annotated MP4
- a CSV containing frame number, time, box coordinates, center coordinates,
  and tracking success
- a trajectory plot
- a JSON file recording the selected frame range and initial box

After both default videos finish, the script also creates
`firm_vs_soft_three_panel.png`, which overlays the firm and soft results in the
tracked-path, horizontal-position, and vertical-position panels.

The CSV keeps a row for every processed frame. Failed tracking frames have an
empty position and `tracking_success` equal to 0, so the data stays aligned with
the source video.

## Tips for the tracking box

- Select a small, distinctive, high-contrast feature attached to the moving
  part of the actuator.
- Keep the box tight, but include enough visual texture for the tracker.
- Avoid including stationary background objects in the box.
- If the blue box drifts in the output video, rerun and choose a different
  target or a shorter frame range.

## Command-line options

From PowerShell in this folder:

```powershell
.\.venv\Scripts\python.exe .\track_actuators.py --check
.\.venv\Scripts\python.exe .\track_actuators.py --start-frame 10 --end-frame 180
```
