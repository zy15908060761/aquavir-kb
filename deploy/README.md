# Deployment

The production service runs two Docker Compose services:

- `api`: FastAPI application (`../backend.py`) with the SQLite core database and
  read-only data directories mounted from `deploy/data/`.
- `nginx`: TLS termination and reverse proxy, serving `deploy/static/` and
  forwarding application traffic to `api:8000`.

## Files

| File | Purpose |
|---|---|
| `docker-compose.yml` | Service definitions and volume mounts |
| `nginx.conf` | Reverse proxy, TLS and caching configuration |
| `requirements.txt` | Python dependencies for the API image |
| `init_db.sql` | Core schema |
| `static/` | Static files served directly by nginx (`robots.txt`, `sitemap.xml`, vendor JS) |
| `maintenance/` | Backup, alerting and BLAST database rebuild scripts |

## Notes

- `deploy/data/` (database, sequences, BLAST databases, public downloads) is not
  tracked in this repository.
- TLS certificates and environment files are supplied outside version control.
- The database is mounted read-write because the BLAST index and download
  metadata are regenerated in place; application code opens it read-only where
  possible.
