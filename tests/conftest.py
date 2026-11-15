"""Pytest fixtures and test isolation hooks for KrishiVaani test suites."""

from __future__ import annotations

import sqlite3
import importlib

# Test classes that create isolated temporary databases and require empty knowledge tables
CLEAN_ISOLATED_CLASSES = [
    ("tests.test_knowledge_adapter", "TestApprovedKnowledgeAdapter"),
    ("tests.test_pjtau_ingestion", "TestPJTAUBulletinIngestionSuite"),
    ("tests.test_tgdps_ingestion", "TestTGDPSIngestionSuite"),
    ("tests.test_review_workflow", "TestHumanReviewWorkflow"),
]


def _patch_isolated_test_setups() -> None:
    """
    Ensure unit test suites that create isolated temporary databases start with
    a clean slate (without pre-seeded knowledge items from Phase 8.7).
    """
    for mod_name, cls_name in CLEAN_ISOLATED_CLASSES:
        try:
            mod = importlib.import_module(mod_name)
            cls = getattr(mod, cls_name)
            orig_setup = cls.setUp

            def make_clean_setup(orig, target_cls):
                def clean_setup(self):
                    orig(self)
                    if hasattr(self, "db_path") and self.db_path and self.db_path.exists():
                        conn = sqlite3.connect(self.db_path)
                        conn.execute("DELETE FROM knowledge_items")
                        conn.execute("DELETE FROM knowledge_item_sources")
                        if "ReviewWorkflow" not in target_cls:
                            conn.execute("DELETE FROM knowledge_sources")
                        conn.execute("DELETE FROM knowledge_verification_audit")
                        conn.commit()
                        conn.close()

                return clean_setup

            cls.setUp = make_clean_setup(orig_setup, cls_name)
        except (ImportError, AttributeError):
            pass


_patch_isolated_test_setups()

