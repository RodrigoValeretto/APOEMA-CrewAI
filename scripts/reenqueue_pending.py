"""Re-enqueue orphaned pending analyses whose RabbitMQ messages were lost.

A zombie-kill purged the whole 'default' queue (not just the orphan message),
orphaning the 51 pending report analyses. This rebuilds their input paths from
analysis_file_mapping and re-enqueues each through the FIFO gate.
"""
import os

from api import database
from api.constants import FileType
from tasks import enqueue_analysis_for_sequential_processing

REPORT_REF = "b4c319228b363dc55611ca3e78cb1f8a"


def main():
    rows = database.get_analyses_by_report(REPORT_REF)
    pending = [a for a in rows if a["status"] == "pending"]
    print(f"Found {len(pending)} pending analyses to re-enqueue")

    for a in pending:
        files = database.get_analysis_files(a["id"])
        paths = {}
        knowledge_files = []
        for f in files:
            ft = f["file_type"]
            if ft == "attachment":
                knowledge_files.append(f["file_path"])
            elif ft not in paths:
                paths[ft] = f["file_path"]

        assessment_file = paths.get(FileType.ASSESSMENT.value)
        if not assessment_file:
            print(f"  [skip {a['id']}] no assessment mapping")
            continue
        if not all(os.path.exists(p) for p in paths.values() if p):
            print(f"  [skip {a['id']}] missing file on disk")
            continue

        enqueue_analysis_for_sequential_processing.send(
            analysis_id=a["id"],
            assessment_file=assessment_file,
            pdf_file=paths.get(FileType.PDF.value) or "",
            png_file=paths.get(FileType.PNG.value) or "",
            csv_file=paths.get(FileType.CSV.value) or "",
            output_prefix=f"analysis_{a['id']}",
            model=a.get("model") or "ollama",
            important_programs=a.get("important_programs") or [],
            knowledge_files=knowledge_files,
        )
        print(f"  [ok {a['id']}] re-enqueued")

    print("Done.")


if __name__ == "__main__":
    main()
