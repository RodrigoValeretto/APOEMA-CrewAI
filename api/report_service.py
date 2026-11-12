"""Shared report-ingestion logic used by the single-report endpoint and the batch actor.

``ingest_report`` consumes one APOEMA report (by id) end-to-end: it resolves the
report's CAPES area to an informativo (assessment source), fetches the chart
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
from .fichas_catalog import area_code_from_name, ficha_key
from .models import ReportIngestItem, ReportIngestResponse

logger = logging.getLogger(__name__)


def _resolve_informativo_inputs(informativo_id: int):
    """Resolve an informativo into analysis inputs.

    Returns:
        (assessment_file, assessment_file_id, knowledge_files, mappings):
        the latest converted ficha becomes the assessment source and every
        completed anexo/adendo becomes an extra Knowledge file (retrieval).
    """
    informativo = database.get_informativo(informativo_id)  # 404 if missing
    fichas = database.get_completed_documents_by_kinds(
        informativo_id, [DocumentKind.FICHA.value]
    )
    if not fichas:
        raise InvalidAnalysisInput(
            f"Informativo '{informativo['nome']}' has no converted ficha (completed). "
            "Upload the ficha PDF and wait for the conversion job to finish."
        )
    ficha = fichas[-1]  # latest converted ficha
    extras = database.get_completed_documents_by_kinds(
        informativo_id, [DocumentKind.ANEXO.value, DocumentKind.ADENDO.value]
    )
    knowledge_files = [d["converted_file_path"] for d in extras]
    mappings = [(d["converted_file_id"], CONVERTED_EXTRA_FILE_TYPE) for d in extras]
    return ficha["converted_file_path"], ficha["converted_file_id"], knowledge_files, mappings


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

    # 2. Resolve the area to an informativo (assessment source).
    informativo_id = None
    informativo_key = None
    if area:
        code = area_code_from_name(area)
        if code:
            informativo_key = ficha_key(code)
            informativo = database.get_informativo_by_slug(informativo_key)
            if informativo:
                informativo_id = informativo["id"]
    if not informativo_id:
        raise InvalidAnalysisInput(
            f"Report area {area!r} could not be resolved to an ingested "
            "informativo. Ingest the corresponding ficha first "
            "(see POST /api/fichas/ingest) and retry."
        )

    assessment_file, converted_ficha_id, knowledge_files, informativo_mappings = (
        _resolve_informativo_inputs(informativo_id)
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
                informativo_id=informativo_id,
                report_reference=report_id,
            )

            # Map every input so retry / report aggregation can rebuild it.
            mappings = [(png_file_id, FileType.PNG.value), (csv_file_id, FileType.CSV.value)]
            if converted_ficha_id:
                mappings.append((converted_ficha_id, FileType.ASSESSMENT.value))
            mappings.extend(informativo_mappings)
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
        informativo_key=informativo_key,
        total_charts=len(charts),
        created=created,
        skipped=skipped,
        failed=failed,
        charts=items,
    )
