"""
Command Line Interface for TGDPS Daily Weather Report Ingestion.
Run via:
    python -m app.knowledge.tgdps.cli [--dry-run] [--limit N] [--file PATH] [--incremental]
Phase 6.4 - TGDPS Daily Weather Report Discovery & Ingestion.
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.knowledge.tgdps.adapter import TGDPSSourceAdapter
from app.knowledge.tgdps.extractor import TGDPSReportExtractor
from app.knowledge.tgdps.ingestion_service import TGDPSReportIngestionService


def configure_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main(args: Optional[list] = None):
    parser = argparse.ArgumentParser(
        description="KrishiVaani - TGDPS Daily Weather Report Ingestion CLI",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate ingestion, discovery, and extraction without writing changes to the database.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of discovered reports to download and process.",
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=None,
        help="Path to a local TGDPS PDF file for manual import fallback.",
    )
    parser.add_argument(
        "--portal-url",
        type=str,
        default=None,
        help="Override the default TGDPS portal URL.",
    )
    parser.add_argument(
        "--report-date",
        type=str,
        default=None,
        help="Explicit ISO report date (YYYY-MM-DD) for local file import.",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=None,
        help="Path to SQLite database file.",
    )
    parser.add_argument(
        "--no-incremental",
        dest="incremental",
        action="store_false",
        default=True,
        help="Force re-processing of already ingested documents.",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable detailed debug logging.",
    )

    parsed = parser.parse_args(args)
    configure_logging(parsed.verbose)

    print("=" * 70)
    print("KrishiVaani - TGDPS Daily Weather Report Ingestion")
    print("=" * 70)
    print(f"Mode: {'DRY RUN (No DB writes)' if parsed.dry_run else 'LIVE INGESTION'}")
    print(f"Database: {parsed.db_path or settings.DATABASE_PATH}")
    print(f"Incremental: {parsed.incremental}")
    if parsed.limit:
        print(f"Download Limit: {parsed.limit}")
    if parsed.file:
        print(f"Local File: {parsed.file}")
    print("-" * 70)

    db_path = parsed.db_path or settings.DATABASE_PATH
    adapter = TGDPSSourceAdapter(portal_url=parsed.portal_url)
    extractor = TGDPSReportExtractor()
    service = TGDPSReportIngestionService(db_path=db_path, adapter=adapter, extractor=extractor)

    if parsed.file:
        print(f"Executing manual import for: {parsed.file}")
        try:
            doc, stored = service.ingest_local_file(
                parsed.file,
                report_date=parsed.report_date,
                dry_run=parsed.dry_run,
            )
            print("\n[SUCCESS] Local File Ingestion Complete:")
            print(f"  Title: {doc.report_title}")
            print(f"  Date: {doc.report_date}")
            print(f"  Observation Period: {doc.observation_period}")
            print(f"  Districts Extracted: {len(doc.district_summaries)}")
            print(f"  Station Observations: {len(doc.station_observations)}")
            print(f"  Items Stored (Pending Review): {stored}")
            sys.exit(0)
        except Exception as exc:
            print(f"\n[ERROR] Local File Ingestion Failed: {exc}")
            sys.exit(1)

    print(f"Starting TGDPS portal ingestion from {adapter.portal_url}...")
    summary = service.ingest_reports(
        limit=parsed.limit,
        dry_run=parsed.dry_run,
        incremental=parsed.incremental,
    )

    print("\n" + "=" * 70)
    print("INGESTION EXECUTION SUMMARY")
    print("=" * 70)
    print(f"Discovered:   {summary.discovered_count}")
    print(f"Downloaded:   {summary.downloaded_count}")
    print(f"Unchanged:    {summary.unchanged_count}")
    print(f"Extracted:    {summary.extracted_count}")
    print(f"Items Stored: {summary.items_stored_count} (all marked pending_verification)")
    print(f"Failed:       {summary.failed_count}")
    if summary.errors:
        print("\nErrors encountered:")
        for err in summary.errors:
            print(f"  - {err}")
    print("=" * 70)

    sys.exit(1 if summary.failed_count > 0 and summary.extracted_count == 0 else 0)


if __name__ == "__main__":
    main()

