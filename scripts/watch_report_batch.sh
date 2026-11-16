#!/bin/bash
# Watch the report analysis batch: print a snapshot every 60s until all 52 are
# terminal (completed/failed), then exit. notify_on_complete=true fires then.
REF="b4c319228b363dc55611ca3e78cb1f8a"
while true; do
  counts=$(docker exec apoema-postgres psql -U apoema -d apoema_db -t -A -c \
    "SELECT status, COUNT(*) FROM analysis WHERE report_reference='$REF' GROUP BY status ORDER BY status;" 2>/dev/null)
  now=$(date '+%H:%M:%S')
  echo "== $now =="
  echo "$counts"
  # Exit when nothing is pending/processing anymore
  remaining=$(docker exec apoema-postgres psql -U apoema -d apoema_db -t -A -c \
    "SELECT COUNT(*) FROM analysis WHERE report_reference='$REF' AND status IN ('pending','processing','queued');" 2>/dev/null)
  if [ "$remaining" = "0" ]; then
    echo "All analyses terminal."
    break
  fi
  sleep 60
done
