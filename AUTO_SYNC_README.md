# Auto Sync

## Files

- `scheduled_sync_runner.py`: runs the full sync pipeline with locking and notifications
- `run_scheduled_sync.bat`: Windows Task Scheduler entrypoint
- `install_daily_sync_task.ps1`: create a daily scheduled task
- `notification_config.example.json`: notification config template
- `sync_runtime/sync_status.json`: latest sync status
- `sync_runtime/sync_history.jsonl`: sync history
- `sync_runtime/notification_log.jsonl`: notification attempts
- `sync_runtime/scheduled_sync.log`: scheduled run console log

## Create a daily task

PowerShell:

```powershell
Set-Location "F:\甲壳动物数据库"
Copy-Item notification_config.example.json notification_config.json
.\install_daily_sync_task.ps1 -DailyTime "02:00"
```

Local-only mode without NCBI:

```powershell
.\install_daily_sync_task.ps1 -DailyTime "02:00" -SkipNcbi
```

## Manual run

```powershell
python scheduled_sync_runner.py
```

## API

- `GET /api/sync/status`
- `GET /api/sync/history`
- `GET /api/sync/notifications`
