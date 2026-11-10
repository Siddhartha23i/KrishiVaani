"""
Command Line Interface for PJTAU Agromet Bulletin Ingestion.
Run via:
    python -m app.knowledge.pjtau.cli [--dry-run] [--limit N] [--file PATH] [--incremental]
Phase 6.3 - Automatic PJTAU Bulletin Ingestion.
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.knowledge.pjtau.adapter import PJTAUSourceAdapter
from app.knowledge.pjtau.extractor import PJTAUBulletinExtractor
from app.knowledge.pjtau.ingestion_service import PJTAUIngestionService


def configure_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main(args: Optional[list] = None):
    parser = argparse.ArgumentParser(
        description="KrishiVaani - PJTAU Agromet Advisory Bulletin Ingestion CLI",
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
        help="Maximum number of discovered bulletins to download and process (e.g. 2 for initial verification).",
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=None,
        help="Path to a local PDF file for manual import fallback.",
    )
    parser.add_argument(
        "--archive-url",
        type=str,
        default=None,
        help="Override the default PJTAU agromet advisories archive URL.",
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
    print("KrishiVaani - PJTAU Agromet Advisory Bulletin Ingestion")
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
    adapter = PJTAUSourceAdapter(archive_url=parsed.archive_url)
    extractor = PJTAUBulletinExtractor()
    service = PJTAUIngestionService(db_path=db_path, adapter=adapter, extractor=extractor)

    if parsed.file:
        print(f"Executing manual import for: {parsed.file}")
        try:
            doc, stored = service.ingest_local_file(parsed.file, dry_run=parsed.dry_run)
            print("\n[SUCCESS] Local File Ingestion Complete:")
            print(f"  Bulletin Number: {doc.pdf_bulletin_number or 'UNKNOWN'}")
            print(f"  Issue Date:      {doc.pdf_issue_date or 'UNKNOWN'}")
            print(f"  Validity:        {doc.validity_start_date} to {doc.validity_end_date}")
            print(f"  Warnings:        {len(doc.warnings)}")
            print(f"  Advisories:      {len(doc.advisories)}")
            print(f"  Items Stored:    {stored} (Pending Review)")
            print(f"  Telugu Quality:  {doc.telugu_extraction_quality.value} ({doc.broken_telugu_characters_count} broken chars)")
            print(f"  English Quality: {doc.english_extraction_quality.value}")
            return 0
        except Exception as exc:
            print(f"\n[ERROR] Failed to ingest local file: {exc}", file=sys.stderr)
            return 1

    # Web archive discovery & ingestion
    print(f"Scanning PJTAU Archive: {adapter.archive_url} ...")
    summary = service.ingest_archive(
        limit=parsed.limit,
        dry_run=parsed.dry_run,
        incremental=parsed.incremental,
    )

    print("\n" + "=" * 70)
    print("INGESTION SUMMARY")
    print("=" * 70)
    print(f"  Discovered on Archive: {summary.discovered_count}")
    print(f"  Newly Downloaded:      {summary.downloaded_count}")
    print(f"  Unchanged / Skipped:   {summary.unchanged_count}")
    print(f"  Successfully Extracted:{summary.extracted_count}")
    print(f"  Failed:                {summary.failed_count}")
    print(f"  Candidate Items Stored:{summary.items_stored_count} (Status: PENDING_VERIFICATION)")
    print(f"  Dry Run:               {summary.dry_run}")

    if summary.errors:
        print("\nErrors Encountered:")
        for err in summary.errors:
            print(f"  - {err}")

    print("=" * 70)
    return 0 if summary.failed_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

