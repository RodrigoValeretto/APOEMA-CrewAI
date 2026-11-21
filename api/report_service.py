"""Shared report-ingestion logic used by the single-report endpoint and the batch actor.

``ingest_report`` consumes one APOEMA report (by id) end-to-end: it resolves the
report's CAPES area to a corpus (assessment source), fetches the chart
list, downloads each chart's PNG + CSV, creates one ``png_csv`` analysis per
chart (all under ``report_reference`` = report id) and enqueues it through the
sequential-processing gate. It is fully synchronous so the Dramatiq batch actor
can call it directly; the single-report endpoint offloads it to a thread.

The Dramatiq enqueue is imported lazily inside ``ingest_report`` to avoid a
module-level import cycle (``tasks`` imports this module for the batch actor).
"""
import logging
from typing import List, Optional

from . import database, file_manager, report_ingestion
from .constants import (
    AnalysisStatus,
    AnalysisType,
    CONVERTED_EXTRA_FILE_TYPE,
    DocumentKind,
    FileType,
)
from .exceptions import InvalidAnalysisInput
from .areas_catalog import area_code_from_name, area_key
from .models import (
    ReportIngestItem,
    ReportIngestResponse,
)
from retry_utils import checkpoint_path

logger = logging.getLogger(__name__)


def _resolve_corpus_inputs(corpus_id: int):
    """Resolve a corpus into analysis inputs.

    Returns:
        (assessment_file, assessment_file_id, knowledge_files, mappings):
        the latest converted form becomes the assessment source and every
        completed attachment/addendum becomes an extra Knowledge file (retrieval).
    """
    corpus = database.get_corpus(corpus_id)  # 404 if missing
    forms = database.get_completed_documents_by_kinds(
        corpus_id, [DocumentKind.FORM.value]
    )
    if not forms:
        raise InvalidAnalysisInput(
            f"Corpus '{corpus['name']}' has no converted form (completed). "
            "Upload the form PDF and wait for the conversion job to finish."
        )
    form = forms[-1]  # latest converted form
    extras = database.get_completed_documents_by_kinds(
        corpus_id, [DocumentKind.ATTACHMENT.value, DocumentKind.ADDENDUM.value]
    )
    knowledge_files = [d["converted_file_path"] for d in extras]
    mappings = [(d["converted_file_id"], CONVERTED_EXTRA_FILE_TYPE) for d in extras]
    return form["converted_file_path"], form["converted_file_id"], knowledge_files, mappings


def ingest_report(
    report_id: str,
    model: str,
    important_programs: Optional[List[str]] = None,
) -> ReportIngestResponse:
    """Consume one published APOEMA report into per-chart ``png_csv`` analyses.

    Idempotent per report: charts that already have an analysis under this
    ``report_reference`` are skipped. Per-chart failures (e.g. the PNG route
    behind the USP VPN) are recorded as ``failed`` and do not abort the report.
    """
    # Lazy import: tasks imports this module for the batch actor.
    from tasks import enqueue_analysis_for_sequential_processing

    if not report_ingestion.validate_report_id(report_id):
        raise InvalidAnalysisInput(
            f"Invalid report id: {report_id!r} (expected an md5-style hex token)"
        )

    # 1. Report info -> CAPES area name.
    info = report_ingestion.fetch_report_info(report_id)
    area = report_ingestion.report_area_name(info)

    # 2. Resolve the area to a corpus (assessment source).
    corpus_id = None
    corpus_key = None
    if area:
        code = area_code_from_name(area)
        if code:
            corpus_key = area_key(code)
            corpus = database.get_corpus_by_slug(corpus_key)
            if corpus:
                corpus_id = corpus["id"]
    if not corpus_id:
        raise InvalidAnalysisInput(
            f"Report area {area!r} could not be resolved to an ingested "
            "corpus. Ingest the corresponding form first "
            "(see POST /api/areas/ingest) and retry."
        )

    assessment_file, converted_form_id, knowledge_files, corpus_mappings = (
        _resolve_corpus_inputs(corpus_id)
    )

    # 3. List charts.
    charts = report_ingestion.fetch_charts(report_id)
    already_analyzed = database.get_report_png_urls(report_id)

    created = skipped = failed = 0
    items: List[ReportIngestItem] = []

    for chart in charts:
        chart_id = chart.get("id") or chart.get("url_n") or ""
        has_file = bool(chart.get("hasfile"))

        if not has_file:
            skipped += 1
            items.append(
                ReportIngestItem(chart_id=chart_id, png_url="", status="skipped")
            )
            continue
        if not report_ingestion.validate_chart_id(chart_id):
            failed += 1
            items.append(
                ReportIngestItem(chart_id=chart_id, png_url="", status="failed")
            )
            continue

        png_url = report_ingestion.chart_png_url(report_id, chart_id)
        if png_url in already_analyzed:
            skipped += 1
            items.append(
                ReportIngestItem(chart_id=chart_id, png_url=png_url, status="skipped")
            )
            continue

        try:
            # CSV (chart data) first — a chart without data can't be analyzed.
            csv_payload = report_ingestion.fetch_chart_csv(png_url)
            csv_text = report_ingestion.chart_csv_text(csv_payload)
            if not csv_text:
                skipped += 1
                items.append(
                    ReportIngestItem(chart_id=chart_id, png_url=png_url, status="skipped")
                )
                continue

            # Download PNG + save CSV to disk (both dedup by URL).
            png_file_id, png_path = file_manager.download_file_from_url_sync(
                png_url, FileType.PNG, timeout=report_ingestion.chart_png_timeout()
            )
            csv_file_id, csv_path = file_manager.save_text_file(
                csv_text,
                FileType.CSV,
                chart_id,
                url=report_ingestion.chart_csv_url(png_url),
            )

            analysis_id = database.create_analysis(
                analysis_type=AnalysisType.PNG_CSV.value,
                status=AnalysisStatus.PENDING.value,
                model=model,
                important_programs=important_programs,
                corpus_id=corpus_id,
                report_reference=report_id,
            )

            # Map every input so retry / report aggregation can rebuild it.
            mappings = [(png_file_id, FileType.PNG.value), (csv_file_id, FileType.CSV.value)]
            if converted_form_id:
                mappings.append((converted_form_id, FileType.ASSESSMENT.value))
            mappings.extend(corpus_mappings)
            for file_id, file_type in mappings:
                database.create_analysis_file_mapping(
                    analysis_id=analysis_id,
                    file_id=file_id,
                    file_type=file_type,
                )

            enqueue_analysis_for_sequential_processing.send(
                analysis_id=analysis_id,
                assessment_file=assessment_file,
                pdf_file=None,
                png_file=png_path,
                csv_file=csv_path,
                output_prefix=f"analysis_{analysis_id}",
                model=model,
                important_programs=important_programs,
                knowledge_files=knowledge_files,
            )

            created += 1
            items.append(
                ReportIngestItem(
                    chart_id=chart_id,
                    png_url=png_url,
                    analysis_id=analysis_id,
                    status="created",
                )
            )
        except Exception as e:
            # Per-chart isolation: one unreachable chart (e.g. the PNG route
            # behind the USP VPN, or a chart without data) must not abort the
            # whole report — record it as failed and move on.
            logger.warning(
                "Failed to ingest chart %s of report %s: %s",
                chart_id,
                report_id,
                e,
            )
            failed += 1
            items.append(
                ReportIngestItem(chart_id=chart_id, png_url=png_url, status="failed")
            )

    return ReportIngestResponse(
        report_id=report_id,
        report_reference=report_id,
        area=area or None,
        corpus_key=corpus_key,
        total_charts=len(charts),
        created=created,
        skipped=skipped,
        failed=failed,
        charts=items,
    )


def reprocess_report(
    report_id: str,
    model: str,
    important_programs: Optional[List[str]] = None,
    partial: bool = False,
) -> ReportIngestResponse:
    """Delete a report's analyses and re-ingest, then return the ingest summary.

    ``partial=False`` (default): delete EVERY analysis under ``report_reference``
    = report id (cascade clears their results + file mappings), drop their
    checkpoints and per-chart PNG/CSV assets, then re-run the normal ingest —
    every chart is recreated as a fresh ``pending`` analysis.

    ``partial=True``: delete only the NON-completed analyses (failed, pending,
    processing, cancelled) and keep ``completed`` intact, then re-run the
    ingest. Because the ingest is idempotent per chart URL, the completed charts
    are skipped and only the deleted ones are recreated as ``pending`` — so a
    partial reprocess re-runs exactly the charts that didn't finish.

    In both modes the corpus assessment/attachments are shared and left
    untouched.
    """
    if not report_ingestion.validate_report_id(report_id):
        raise InvalidAnalysisInput(
            f"Invalid report id: {report_id!r} (expected an md5-style hex token)"
        )

    keep_statuses = [AnalysisStatus.COMPLETED.value] if partial else None

    # 1. Collect the analyses we're about to delete (their per-chart files are
    #    only reachable through the mappings, which die with the cascade).
    analyses = database.get_analyses_by_report(report_id)
    to_delete_ids = {
        a["id"]
        for a in analyses
        if keep_statuses is None or a["status"] not in keep_statuses
    }

    chart_file_ids = []
    for a in analyses:
        if a["id"] not in to_delete_ids:
            continue
        for f in database.get_analysis_files(a["id"]):
            if f["file_type"] in (FileType.PNG.value, FileType.CSV.value):
                chart_file_ids.append(f["id"])

    # 2. Delete the analyses (cascade removes results + mappings).
    deleted_ids = database.delete_analyses_by_report(
        report_id, keep_statuses=keep_statuses
    )
    logger.info(
        "[Reports] %s reprocess (partial=%s): deleted %d analyses",
        report_id,
        partial,
        len(deleted_ids),
    )

    # 3. Drop the run checkpoints for the deleted analyses (fresh start).
    for analysis_id in deleted_ids:
        cp = checkpoint_path(f"analysis_{analysis_id}")
        if cp.exists():
            try:
                cp.unlink()
            except OSError:
                logger.warning(
                    "[Reports] %s reprocess: failed to remove checkpoint %s",
                    report_id,
                    cp,
                )

    # 4. Delete the per-chart PNG/CSV files (disk + tracking rows).
    for file_id in chart_file_ids:
        try:
            file_manager.delete_file(file_id)
        except Exception as e:  # per-file isolation
            logger.warning(
                "[Reports] %s reprocess: failed to delete file %s: %s",
                report_id,
                file_id,
                e,
            )

    # 5. Re-ingest. Idempotent per chart URL, so in partial mode the kept
    #    (completed) charts are skipped and only the deleted ones are recreated.
    return ingest_report(report_id, model, important_programs)
