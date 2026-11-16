#!/bin/bash
# Wait until analysis 185 (first report chart) saves its FIRST result, then
# print its result_json/result split. Exits as soon as 1+ task is done.
while true; do
  done=$(docker exec apoema-postgres psql -U apoema -d apoema_db -t -A -c \
    "SELECT COUNT(*) FROM analysis_results WHERE analysis_id=185;" 2>/dev/null)
  if [ "$done" != "0" ]; then
    echo "=== analysis 185: first result saved ==="
    docker exec apoema-postgres psql -U apoema -d apoema_db -c \
      "SELECT task_name, (result IS NULL) AS result_is_null, (result_json IS NOT NULL) AS has_json, jsonb_typeof(result_json) AS json_type, length(result_json::text) AS json_chars FROM analysis_results WHERE analysis_id=185 ORDER BY id;" 2>/dev/null
    break
  fi
  sleep 30
done
