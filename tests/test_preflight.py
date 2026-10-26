"""Fail-closed tests for approval gating. No media, network, or Kaggle access."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import run_workflow as rw  # noqa: E402


def domain_record(**overrides) -> dict:
    record = {
        "schema_version": 1,
        "kind": "domain_decision",
        "approved": True,
        "project": "yamazaki-shishi",
        "subject_name": "ヤマザキシシ",
        "subject_type": "fictional_character",
        "rights_holder": "Example Rights Holder",
        "intended_use": "private_experiment",
        "publication_scope": "private_dataset",
        "source_urls": ["https://example.com/source"],
        "permission_evidence": [
            {
                "reference": "data/approvals/evidence/permission.txt",
                "checked_at": "2026-10-01",
                "covers": ["frame_extraction", "dataset_creation"],
            }
        ],
        "reviewed_by": "bons",
        "reviewed_at": "2026-10-01",
        "notes": "",
    }
    record.update(overrides)
    return record


def selection_record(**overrides) -> dict:
    record = {
        "schema_version": 1,
        "kind": "video_selection",
        "approved": True,
        "project": "yamazaki-shishi",
        "selected_video_ids": ["vid01"],
        "approved_uses": ["acquisition", "frame_extraction", "dataset_creation"],
        "excluded_time_ranges": [],
        "reason_each_video_is_representative": {"vid01": "representative appearance"},
        "reviewed_by": "bons",
        "reviewed_at": "2026-10-01",
        "notes": "",
    }
    record.update(overrides)
    return record


def video_entry(**overrides) -> dict:
    row = {
        "video_id": "vid01",
        "source_url": "https://example.com/v1",
        "local_path": "data/local-videos/vid01.mp4",
        "creator_or_rights_holder": "Example Rights Holder",
        "terms_url": "https://example.com/terms",
        "rights_basis": "written_permission",
        "permitted_uses": ["acquisition", "frame_extraction", "dataset_creation"],
        "permission_status": "approved",
        "reviewed_by": "bons",
        "reviewed_at": "2026-10-01",
        "notes": "",
    }
    row.update(overrides)
    return row


def dataset_record(**overrides) -> dict:
    record = {
        "schema_version": 1,
        "kind": "dataset_review",
        "approved": True,
        "captions_reviewed": True,
        "contact_sheet_reviewed": True,
        "manifest_sha256": "a" * 64,
        "content_sha256": "b" * 64,
        "reviewed_by": "bons",
        "reviewed_at": "2026-10-01",
        "notes": "",
    }
    record.update(overrides)
    return record


def write_fixture(root: Path, domain=None, selection=None, videos=None) -> None:
    approvals = root / "data/approvals"
    approvals.mkdir(parents=True, exist_ok=True)
    if domain is not None:
        (approvals / "domain-decision.json").write_text(json.dumps(domain), encoding="utf-8")
    if selection is not None:
        (approvals / "approval-record.json").write_text(json.dumps(selection), encoding="utf-8")
    if videos is not None:
        import yaml

        (root / "selected-videos.yml").write_text(yaml.safe_dump({"videos": videos}), encoding="utf-8")


class TemplateTests(unittest.TestCase):
    def test_templates_are_not_approvals(self):
        root = rw.ROOT / "data/approvals"
        domain = json.loads((root / "domain-decision.template.json").read_text(encoding="utf-8"))
        selection = json.loads((root / "approval-record.template.json").read_text(encoding="utf-8"))
        dataset = json.loads((root / "dataset-approval.template.json").read_text(encoding="utf-8"))
        for record, validator in (
            (domain, rw.validate_domain_decision),
            (selection, rw.validate_selection_record),
            (dataset, rw.validate_dataset_approval),
        ):
            problems = validator(record)
            self.assertTrue(problems, "template must not validate as an approval")
            self.assertIn("approved is not true", problems)


class DateTests(unittest.TestCase):
    def test_rejects_impossible_dates(self):
        for value in ("2026-02-31", "2026-13-01", "2026-00-10", "2026-2-1", "not-a-date", ""):
            self.assertFalse(rw.valid_date(value), value)

    def test_accepts_real_dates(self):
        for value in ("2024-02-29", "2026-10-01"):
            self.assertTrue(rw.valid_date(value), value)

    def test_accepts_yaml_date_objects(self):
        import datetime

        self.assertTrue(rw.valid_date(datetime.date(2026, 10, 1)))
        self.assertFalse(rw.valid_date(datetime.datetime(2026, 10, 1, 12, 0)))


class DomainDecisionTests(unittest.TestCase):
    def test_valid_record_passes(self):
        self.assertEqual(rw.validate_domain_decision(domain_record()), [])

    def test_public_scope_is_blocked(self):
        problems = rw.validate_domain_decision(domain_record(publication_scope="public_dataset"))
        self.assertTrue(any("publication_scope" in item for item in problems))

    def test_unknown_rights_holder_is_blocked(self):
        problems = rw.validate_domain_decision(domain_record(rights_holder="unknown"))
        self.assertTrue(any("rights_holder" in item for item in problems))

    def test_evidence_is_required(self):
        problems = rw.validate_domain_decision(domain_record(permission_evidence=[]))
        self.assertTrue(any("permission_evidence" in item for item in problems))

    def test_evidence_needs_reference_and_coverage(self):
        problems = rw.validate_domain_decision(
            domain_record(permission_evidence=[{"reference": "", "checked_at": "2026-10-01", "covers": []}])
        )
        self.assertTrue(any("reference" in item for item in problems))
        self.assertTrue(any("covers" in item for item in problems))

    def test_reviewer_is_required(self):
        problems = rw.validate_domain_decision(domain_record(reviewed_by="", reviewed_at=""))
        self.assertTrue(any("reviewed_by" in item for item in problems))
        self.assertTrue(any("reviewed_at" in item for item in problems))


class SelectionTests(unittest.TestCase):
    def test_valid_record_passes(self):
        self.assertEqual(rw.validate_selection_record(selection_record()), [])

    def test_missing_use_scope_is_blocked(self):
        problems = rw.validate_selection_record(selection_record(approved_uses=["acquisition"]))
        self.assertTrue(any("approved_uses" in item for item in problems))

    def test_excluded_ranges_must_be_explicit(self):
        problems = rw.validate_selection_record(selection_record(excluded_time_ranges=None))
        self.assertTrue(any("excluded_time_ranges" in item for item in problems))

    def test_duplicate_ids_are_blocked(self):
        problems = rw.validate_selection_record(
            selection_record(
                selected_video_ids=["vid01", "vid01"],
                reason_each_video_is_representative={"vid01": "reason"},
            )
        )
        self.assertTrue(any("duplicates" in item for item in problems))

    def test_reason_for_unselected_id_is_blocked(self):
        problems = rw.validate_selection_record(
            selection_record(reason_each_video_is_representative={"vid01": "reason", "vid99": "stale"})
        )
        self.assertTrue(any("not in selected_video_ids" in item for item in problems))


class VideoManifestTests(unittest.TestCase):
    def test_valid_entry_passes(self):
        self.assertEqual(rw.validate_videos([video_entry()], {"vid01"}), [])

    def test_pending_permission_is_blocked(self):
        problems = rw.validate_videos([video_entry(permission_status="pending")])
        self.assertTrue(any("permission_status" in item for item in problems))

    def test_vague_rights_basis_is_blocked(self):
        problems = rw.validate_videos([video_entry(rights_basis="publicly_visible")])
        self.assertTrue(any("rights_basis" in item for item in problems))

    def test_per_use_scope_is_required(self):
        problems = rw.validate_videos([video_entry(permitted_uses=["acquisition"])])
        self.assertTrue(any("dataset_creation" in item for item in problems))

    def test_video_must_be_listed_in_approval(self):
        problems = rw.validate_videos([video_entry()], {"other"})
        self.assertTrue(any("approval-record.json" in item for item in problems))

    def test_duplicates_are_blocked(self):
        problems = rw.validate_videos([video_entry(), video_entry()])
        self.assertTrue(any("duplicates video_id" in item for item in problems))


class DatasetApprovalTests(unittest.TestCase):
    def test_valid_record_passes(self):
        self.assertEqual(rw.validate_dataset_approval(dataset_record()), [])

    def test_review_flags_must_be_true(self):
        problems = rw.validate_dataset_approval(dataset_record(captions_reviewed=False))
        self.assertTrue(any("captions_reviewed" in item for item in problems))

    def test_manifest_hash_is_required(self):
        problems = rw.validate_dataset_approval(dataset_record(manifest_sha256=""))
        self.assertTrue(any("manifest_sha256" in item for item in problems))

    def test_content_hash_is_required(self):
        problems = rw.validate_dataset_approval(dataset_record(content_sha256=""))
        self.assertTrue(any("content_sha256" in item for item in problems))


class PreflightTests(unittest.TestCase):
    def test_missing_artifacts_are_all_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            blockers, _ = rw.preflight(Path(tmp))
        self.assertEqual(len(blockers), 3)
        self.assertTrue(any("domain-decision.json" in item for item in blockers))
        self.assertTrue(any("approval-record.json" in item for item in blockers))
        self.assertTrue(any("selected-videos.yml" in item for item in blockers))

    def test_complete_fixture_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_fixture(root, domain_record(), selection_record(), [video_entry()])
            blockers, warnings = rw.preflight(root)
        self.assertEqual(blockers, [])
        self.assertEqual(warnings, [])

    def test_manifest_without_selection_approval_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_fixture(root, domain_record(), None, [video_entry()])
            blockers, _ = rw.preflight(root)
        self.assertTrue(any("approval-record.json" in item for item in blockers))

    def test_unlisted_video_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_fixture(root, domain_record(), selection_record(selected_video_ids=["other"]), [video_entry()])
            blockers, _ = rw.preflight(root)
        self.assertTrue(any("not covered by approval-record.json" in item for item in blockers))

    def test_approved_id_missing_from_manifest_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            selection = selection_record(
                selected_video_ids=["vid01", "vid02"],
                reason_each_video_is_representative={"vid01": "a", "vid02": "b"},
            )
            write_fixture(root, domain_record(), selection, [video_entry()])
            blockers, _ = rw.preflight(root)
        self.assertTrue(any("approved video ids missing from" in item for item in blockers))
        self.assertTrue(any("vid02" in item for item in blockers))

    def test_malformed_json_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_fixture(root, None, selection_record(), [video_entry()])
            (root / "data/approvals/domain-decision.json").write_text("{not json", encoding="utf-8")
            blockers, _ = rw.preflight(root)
        self.assertTrue(any("approval unreadable" in item for item in blockers))

    def test_count_difference_is_a_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_fixture(root, domain_record(), selection_record(), [video_entry()])
            blockers, warnings = rw.preflight(root, target_count=7)
        self.assertEqual(blockers, [])
        self.assertTrue(any("target is 7" in item for item in warnings))


class DatasetIntegrityTests(unittest.TestCase):
    def make_dataset(self, root: Path):
        images = root / "data/dataset/images"
        images.mkdir(parents=True, exist_ok=True)
        image = images / "vid01_000000.png"
        image.write_bytes(b"\x89PNG\r\n\x1a\n")
        caption = images / "vid01_000000.txt"
        caption.write_text("placeholder caption\n", encoding="utf-8")
        row = {
            "image_path": "data/dataset/images/vid01_000000.png",
            "caption_path": "data/dataset/images/vid01_000000.txt",
            "image_sha256": rw.sha256_file(image),
            "caption_sha256": rw.sha256_file(caption),
        }
        manifest = {"content_sha256": rw.content_digest([row]), "images": [row]}
        return caption, row, manifest

    def test_untouched_dataset_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, row, manifest = self.make_dataset(root)
            self.assertEqual(rw.dataset_integrity_problems(root, [row], manifest), [])

    def test_edited_caption_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            caption, row, manifest = self.make_dataset(root)
            caption.write_text("edited after approval\n", encoding="utf-8")
            problems = rw.dataset_integrity_problems(root, [row], manifest)
        self.assertTrue(any("caption_path changed after extraction" in item for item in problems))

    def test_manifest_content_digest_mismatch_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, row, manifest = self.make_dataset(root)
            manifest = dict(manifest, content_sha256="d" * 64)
            problems = rw.dataset_integrity_problems(root, [row], manifest)
        self.assertTrue(any("content digest" in item for item in problems))

    def test_content_digest_tracks_caption_hash(self):
        row = {
            "image_path": "i",
            "image_sha256": "a" * 64,
            "caption_path": "c",
            "caption_sha256": "b" * 64,
        }
        changed = dict(row, caption_sha256="c" * 64)
        self.assertNotEqual(rw.content_digest([row]), rw.content_digest([changed]))

    def test_existing_outputs_are_detected(self):
        config = rw.load_workflows()["03"]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(rw.existing_dataset_outputs(root, config), [])
            (root / "data/dataset/images").mkdir(parents=True)
            (root / "data/dataset/images/x.png").write_bytes(b"x")
            found = rw.existing_dataset_outputs(root, config)
        self.assertTrue(any(path.name == "x.png" for path in found))


class OverwriteTests(unittest.TestCase):
    def setUp(self):
        self.config = rw.load_workflows()["03"]

    def test_stale_files_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            images = root / "data/dataset/images"
            images.mkdir(parents=True)
            for name in ("a.png", "a.txt", "old.png", "old.txt", "notes.md"):
                (images / name).write_text("x", encoding="utf-8")
            rows = [{"image_path": "data/dataset/images/a.png", "caption_path": "data/dataset/images/a.txt"}]
            stale = [path.name for path in rw.stale_dataset_files(root, self.config, rows)]
        self.assertEqual(stale, ["old.png", "old.txt"])

    def test_clear_removes_only_images_and_captions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            images = root / "data/dataset/images"
            images.mkdir(parents=True)
            for name in ("a.png", "a.txt", "notes.md"):
                (images / name).write_text("x", encoding="utf-8")
            removed = [path.name for path in rw.clear_dataset_images(root, self.config)]
            remaining = sorted(path.name for path in images.iterdir())
        self.assertEqual(removed, ["a.png", "a.txt"])
        self.assertEqual(remaining, ["notes.md"])

    def test_clear_is_noop_without_images_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(rw.clear_dataset_images(Path(tmp), self.config), [])


if __name__ == "__main__":
    unittest.main()
