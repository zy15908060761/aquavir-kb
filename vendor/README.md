# Local frontend vendor files

The app serves this directory under `/static/vendor/` because `backend.py` mounts the
project root at `/static`.

Place these files here to run the web UI without CDN access:

- `tailwindcss.min.js`
- `htmx.min.js`
- `echarts.min.js`

The templates load CDN versions first and automatically fall back to these local
files when the CDN request fails.
