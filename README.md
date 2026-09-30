# Motion Tracker

Motion Tracker is a focused web app for extracting the pixel trajectory of one
feature in a trimmed actuator video. The user uploads a clip, draws a box on its
first frame, runs OpenCV CSRT tracking, and downloads all results as a ZIP.

## Launch locally

1. Double-click `Setup Web App.cmd` once.
2. Double-click `Run Web App.cmd` whenever you want to use the app.
3. Press Ctrl+C in the server window when finished.

See [`WEB_APP_README.md`](WEB_APP_README.md) for deployment, configuration, and
output details.

## Deploy

The recommended classroom deployment is a GitHub repository connected to a
Render web service. `Dockerfile` and `render.yaml` are included, so Render can
build and host the Python/OpenCV backend and the browser interface together.

GitHub Pages alone is not sufficient because it only serves static files; the
tracker requires a running Python process.
