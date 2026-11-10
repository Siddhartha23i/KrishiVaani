"""
Command Line Review Interface for Agricultural Knowledge — Phase 7.4.

Provides administrative terminal commands to list, inspect, verify,
approve, and reject knowledge items with explicit reviewer accountability,
mandatory confirmation, and application-level append-only audit tracking.

SECURITY & IDENTITY NOTICE:
- Reviewer identity (--actor) and role (--role) parameters are self-asserted by the caller.
- They are NOT authenticated, signed, or cryptographically verified identities.
- Role checks enforced by the service are application-level safeguards against operational
  mistakes, NOT proof of genuine professional identity or qualifications.
- This CLI is intended strictly for trusted local administrative and development usage.
- This tool and underlying review service MUST NOT be exposed as an unauthenticated public HTTP endpoint.

AUDIT INTEGRITY NOTICE:
- Audit records in `knowledge_verification_audit` are append-only strictly by application-level contract.
- The underlying SQLite database does not enforce database-level immutability (e.g. triggers).

Usage:
  python -m app.knowledge.review_cli list [--status pending_verification] [--limit 20]
  python -m app.knowledge.review_cli show <knowledge_id>
  python -m app.knowledge.review_cli history <knowledge_id>
  python -m app.knowledge.review_cli verify <knowledge_id> --actor <id> --role <role> --notes <notes>
  python -m app.knowledge.review_cli approve <knowledge_id> --actor <id> --role <role> --notes <notes>
  python -m app.knowledge.review_cli reject <knowledge_id> --actor <id> --role <role> --reason <reason>
  python -m app.knowledge.review_cli interactive
"""

import sys
import argparse
from typing import Optional

from app.knowledge.review_service import (
    ReviewService,
    STATUS_PENDING,
    STATUS_VERIFIED,
    STATUS_APPROVED,
    STATUS_REJECTED,
    ROLE_TECHNICAL_REVIEWER,
    ROLE_AGRICULTURAL_EXPERT,
    ROLE_AGRONOMIST,
)


def confirm_action(prompt: str) -> bool:
    """Ask for interactive user confirmation before modifying status."""
    try:
        reply = input(f"{prompt} [y/N]: ").strip().lower()
        return reply in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False


def cmd_list(service: ReviewService, args: argparse.Namespace) -> None:
    records = service.list_records(
        status=args.status,
        category=args.category,
        district=args.district,
        limit=args.limit,
    )
    if not records:
        print(f"No records found matching status='{args.status or 'ALL'}'")
        return

    print("=" * 110)
    print(f"{'Knowledge ID':<26} | {'Status':<18} | {'Category':<16} | {'District':<12} | {'Crop':<10} | {'Dates':<20}")
    print("-" * 110)
    for r in records:
        kid = r["knowledge_id"]
        status = r["verification_status"]
        cat = r["category"] or "N/A"
        dist = r["district"] or "Statewide"
        crop = r["crop_name"] or "N/A"
        dates = f"{r['applicable_from'] or ''}..{r['applicable_until'] or ''}"
        print(f"{kid:<26} | {status:<18} | {cat:<16} | {dist:<12} | {crop:<10} | {dates:<20}")
        print(f"   Title: {r['title'][:80]}")
    print("=" * 110)
    print(f"Total shown: {len(records)}")


def cmd_show(service: ReviewService, args: argparse.Namespace) -> None:
    record = service.get_record_detail(args.knowledge_id)
    if not record:
        print(f"Error: Knowledge item '{args.knowledge_id}' not found.")
        sys.exit(1)

    print("=" * 90)
    print(f"RECORD DETAIL: {record['knowledge_id']}")
    print("=" * 90)
    print(f"Title:               {record['title']}")
    print(f"Status:              {record['verification_status'].upper()}")
    print(f"Category / Type:     {record['category']} / {record['knowledge_type']}")
    print(f"Crop / Season:       {record['crop_name'] or 'N/A'} (Variety: {record['crop_variety'] or 'N/A'}) / {record['season'] or 'N/A'}")
    print(f"Geography:           State={record['state']}, District={record['district'] or 'Statewide'}, Mandal={record['mandal'] or 'N/A'}")
    print(f"Applicability Dates: From {record['applicable_from'] or 'N/A'} To {record['applicable_until'] or 'N/A'}")
    print(f"Last Verified By:    {record['verified_by'] or 'Unverified'} at {record['verified_at'] or 'N/A'}")
    print("-" * 90)
    print(f"SOURCE PROVENANCE:")
    print(f"Source ID:           {record['source_id'] or 'N/A'}")
    print(f"Publisher:           {record['publisher'] or 'N/A'}")
    print(f"Document Title:      {record['document_title'] or 'N/A'}")
    print(f"Source URL:          {record['source_url'] or 'N/A'}")
    print(f"Reference Location:  {record['reference_location'] or 'N/A'}")
    print(f"Source Date:         {record['source_published_at'] or 'N/A'}")
    print("-" * 90)
    print("EXTRACTED CONTENT:")
    print(record["content"])
    print("=" * 90)


def cmd_history(service: ReviewService, args: argparse.Namespace) -> None:
    history = service.get_audit_history(args.knowledge_id)
    if not history:
        print(f"No audit records found for '{args.knowledge_id}'.")
        return

    print("=" * 100)
    print(f"AUDIT TRAIL FOR: {args.knowledge_id}")
    print("-" * 100)
    for h in history:
        print(f"[{h['created_at']}] Action: {h['action']}")
        print(f"  Actor: {h['actor']} (Role: {h['actor_role']}) | Audit ID: {h['audit_id']}")
        print(f"  Notes: {h['notes']}")
        print("-" * 100)


def cmd_transition(service: ReviewService, knowledge_id: str, new_status: str, actor: str, role: str, notes: str, yes: bool) -> None:
    detail = service.get_record_detail(knowledge_id)
    if not detail:
        print(f"Error: Knowledge item '{knowledge_id}' not found.")
        sys.exit(1)

    curr_status = detail["verification_status"]
    print(f"Target Record:  {knowledge_id}")
    print(f"Title:          {detail['title']}")
    print(f"Current Status: {curr_status}")
    print(f"New Status:     {new_status.upper()}")
    print(f"Reviewer:       {actor} (Role: {role})")
    print(f"Review Notes:   {notes}")

    if not yes:
        if not confirm_action(f"Are you sure you want to transition '{knowledge_id}' to '{new_status}'?"):
            print("Operation cancelled by user.")
            return

    try:
        res = service.transition_status(
            knowledge_id=knowledge_id,
            new_status=new_status,
            actor=actor,
            actor_role=role,
            notes=notes,
        )
        print(f"\nSUCCESS: Record '{knowledge_id}' transitioned from '{res['previous_status']}' to '{res['new_status']}'.")
        print(f"Audit Record Created: {res['audit_id']}")
    except (ValueError, PermissionError) as e:
        print(f"\nREJECTED: {str(e)}")
        sys.exit(1)


def cmd_interactive(service: ReviewService) -> None:
    print("=" * 80)
    print("KrishiVaani Agricultural Knowledge Human Review Tool (Interactive Mode)")
    print("=" * 80)

    while True:
        print("\nOptions:")
        print("  1. List pending records")
        print("  2. Show record detail")
        print("  3. View record audit history")
        print("  4. Verify record (Technical Authenticity Check)")
        print("  5. Approve record (Agricultural Expert Farmer-Facing Sign-Off)")
        print("  6. Reject record")
        print("  7. Exit")

        try:
            choice = input("\nEnter choice [1-7]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break

        if choice == "1":
            records = service.list_records(status=STATUS_PENDING, limit=20)
            print(f"\nFound {len(records)} pending items:")
            for r in records:
                print(f"  {r['knowledge_id']} | {r['category']} | {r['district'] or 'Statewide'} | {r['title'][:60]}")
        elif choice == "2":
            kid = input("Enter knowledge_id: ").strip()
            if kid:
                cmd_show(service, argparse.Namespace(knowledge_id=kid))
        elif choice == "3":
            kid = input("Enter knowledge_id: ").strip()
            if kid:
                cmd_history(service, argparse.Namespace(knowledge_id=kid))
        elif choice == "4":
            kid = input("Enter knowledge_id: ").strip()
            actor = input("Enter reviewer identity (e.g. qa_siddharth): ").strip()
            notes = input("Enter verification notes: ").strip()
            if kid and actor and notes:
                cmd_transition(service, kid, STATUS_VERIFIED, actor, ROLE_TECHNICAL_REVIEWER, notes, False)
        elif choice == "5":
            kid = input("Enter knowledge_id: ").strip()
            actor = input("Enter agronomist identity (e.g. dr_ramana_pjtau): ").strip()
            notes = input("Enter agronomic approval notes: ").strip()
            if kid and actor and notes:
                cmd_transition(service, kid, STATUS_APPROVED, actor, ROLE_AGRICULTURAL_EXPERT, notes, False)
        elif choice == "6":
            kid = input("Enter knowledge_id: ").strip()
            actor = input("Enter reviewer identity: ").strip()
            role = input("Enter reviewer role [technical_reviewer/agricultural_expert]: ").strip() or ROLE_TECHNICAL_REVIEWER
            reason = input("Enter substantive rejection reason: ").strip()
            if kid and actor and reason:
                cmd_transition(service, kid, STATUS_REJECTED, actor, role, reason, False)
        elif choice == "7":
            print("Exiting.")
            break
        else:
            print("Invalid choice.")


def main():
    parser = argparse.ArgumentParser(description="KrishiVaani Evidence Review & Approval CLI")
    subparsers = parser.add_subparsers(dest="command")

    # list
    p_list = subparsers.add_parser("list", help="List knowledge records")
    p_list.add_argument("--status", choices=[STATUS_PENDING, STATUS_VERIFIED, STATUS_APPROVED, STATUS_REJECTED], default=None)
    p_list.add_argument("--category", default=None)
    p_list.add_argument("--district", default=None)
    p_list.add_argument("--limit", type=int, default=20)

    # show
    p_show = subparsers.add_parser("show", help="Display full record details")
    p_show.add_argument("knowledge_id")

    # history
    p_hist = subparsers.add_parser("history", help="Show chronological audit trail")
    p_hist.add_argument("knowledge_id")

    # verify
    p_ver = subparsers.add_parser("verify", help="Mark item verified (technical check)")
    p_ver.add_argument("knowledge_id")
    p_ver.add_argument("--actor", required=True, help="Reviewer identifier")
    p_ver.add_argument("--role", default=ROLE_TECHNICAL_REVIEWER, help="Reviewer role")
    p_ver.add_argument("--notes", required=True, help="Verification notes")
    p_ver.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt")

    # approve
    p_app = subparsers.add_parser("approve", help="Approve item for farmer-facing LLM retrieval")
    p_app.add_argument("knowledge_id")
    p_app.add_argument("--actor", required=True, help="Agricultural expert identifier")
    p_app.add_argument("--role", default=ROLE_AGRICULTURAL_EXPERT, help="Reviewer role (must be agricultural_expert or agronomist)")
    p_app.add_argument("--notes", required=True, help="Approval notes")
    p_app.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt")

    # reject
    p_rej = subparsers.add_parser("reject", help="Reject item")
    p_rej.add_argument("knowledge_id")
    p_rej.add_argument("--actor", required=True, help="Reviewer identifier")
    p_rej.add_argument("--role", default=ROLE_TECHNICAL_REVIEWER, help="Reviewer role")
    p_rej.add_argument("--reason", required=True, help="Rejection rationale")
    p_rej.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt")

    # interactive
    subparsers.add_parser("interactive", help="Launch interactive review menu")

    args = parser.parse_args()
    service = ReviewService()

    if args.command == "list":
        cmd_list(service, args)
    elif args.command == "show":
        cmd_show(service, args)
    elif args.command == "history":
        cmd_history(service, args)
    elif args.command == "verify":
        cmd_transition(service, args.knowledge_id, STATUS_VERIFIED, args.actor, args.role, args.notes, args.yes)
    elif args.command == "approve":
        cmd_transition(service, args.knowledge_id, STATUS_APPROVED, args.actor, args.role, args.notes, args.yes)
    elif args.command == "reject":
        cmd_transition(service, args.knowledge_id, STATUS_REJECTED, args.actor, args.role, args.reason, args.yes)
    elif args.command == "interactive" or not args.command:
        cmd_interactive(service)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

