#!/bin/bash
# Resource alert: disk usage >80% or available memory <500MB
LOG=/var/log/aquavir/alert.log
mkdir -p /var/log/aquavir
DISK=$(df / | awk 'NR==2 {gsub(/%/,"",$5); print $5}')
MEM_AVAIL=$(free -m | awk '/Mem:/ {print $7}')
[ "$DISK" -gt 80 ] && echo "$(date +%F_%T) WARN disk=${DISK}%" >> "$LOG"
[ "$MEM_AVAIL" -lt 500 ] && echo "$(date +%F_%T) WARN mem_avail=${MEM_AVAIL}MB" >> "$LOG"
exit 0
