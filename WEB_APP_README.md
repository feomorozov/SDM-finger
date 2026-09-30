# Motion Tracker web app

A minimal single-video web interface for OpenCV CSRT tracking.

## User workflow

1. Upload a video that is already trimmed to the desired frame range.
2. Draw a tracking box on the first frame.
3. Press **Run tracking**.
4. Download a ZIP containing:
   - annotated MP4
   - frame-aligned CSV
   - three-panel trajectory PNG
   - settings JSON

## Run locally

On Windows, double-click `Setup Web App.cmd` once and then double-click
`Run Web App.cmd`. The launcher opens the site automatically; press Ctrl+C in
its server window when you are finished.

Or run it manually from PowerShell in this folder:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-web-local.txt
.\.venv\Scripts\python.exe .\app.py
```

Open <http://localhost:8000>.

The existing local desktop tracker uses the full OpenCV package. The Docker
deployment uses `opencv-contrib-python-headless`, because ROI selection happens
in the browser rather than through an OpenCV desktop window.

## Publish with Render

GitHub Pages cannot run this app because it only publishes static files. Put the
project in a GitHub repository, then connect that repository to Render. The
included `render.yaml` and `Dockerfile` define the service.

On Render:

1. Create a new Blueprint.
2. Connect the GitHub repository.
3. Select the repository and deploy the Blueprint.
4. Open the generated `onrender.com` URL.

Free services can sleep when idle, so the first visit after inactivity may take
longer. Temporary uploads and results are intentionally stored on ephemeral disk
and removed after the configured retention period.

## Configuration

- `PORT`: server port; defaults to `8000`
- `MAX_UPLOAD_MB`: maximum upload size; defaults to `250`
- `RETENTION_HOURS`: age at which temporary files are cleaned; defaults to `6`
- `RUNTIME_DIR`: temporary data directory; defaults to `runtime_data` locally

This implementation intentionally uses one background worker. It is designed for
a classroom tool with light, one-at-a-time usage—not a high-concurrency public
service.
