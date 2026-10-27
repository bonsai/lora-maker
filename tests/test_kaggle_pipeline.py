"""Offline tests for the Kaggle CLI/CD LoRA pipeline.

No network, no Kaggle account, no GPU: everything here either renders a bundle
into a temporary directory or runs the fail-closed gates against synthetic data.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import tempfile
import tomllib
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import run_workflow as rw  # noqa: E402
from tools import kaggle_pipeline as kp  # noqa: E402

POLICY = kp.load_policy(ROOT / "workflows/05-lora-training.yml")
IMAGE = b"\x89PNG\r\n\x1a\nnot-a-real-png"
CAPTION = "yamazaki_shishi, standing, white fur\n"


def manifest_row(name: str) -> dict:
    return {
        "image_path": f"images/{name}.png",
        "caption_path": f"images/{name}.txt",
        "image_sha256": hashlib.sha256(IMAGE).hexdigest(),
        "caption": CAPTION,
    }


def synthetic_dataset(tmp: Path, rows: list[dict]) -> tuple[Path, Path]:
    """Create a ZIP + approval record that satisfies dataset_gate."""
    zip_path = tmp / "dataset.zip"
    manifest = {
        "schema_version": 1,
        "images": rows,
        "content_sha256": rw.content_digest(rows),
    }
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False) + "\n").encode("utf-8")
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("manifest.json", manifest_bytes)
        for row in rows:
            archive.writestr(f"images/{Path(row['image_path']).name}", IMAGE)
            archive.writestr(f"images/{Path(row['caption_path']).name}", CAPTION)
    approval = {
        "schema_version": 1,
        "kind": "dataset_review",
        "approved": True,
        "project": "yamazaki-shishi",
        "captions_reviewed": True,
        "contact_sheet_reviewed": True,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "content_sha256": manifest["content_sha256"],
        "reviewed_by": "test reviewer",
        "reviewed_at": "2026-10-27",
    }
    approval_path = tmp / "dataset-approval.json"
    approval_path.write_text(json.dumps(approval), encoding="utf-8")
    return zip_path, approval_path


class PolicyTests(unittest.TestCase):
    def test_policy_is_dry_run_private_t4(self) -> None:
        self.assertEqual(POLICY["execution"]["mode"], "dry_run")
        self.assertEqual(POLICY["kaggle"]["accelerator"], "NvidiaTeslaT4")
        self.assertIs(POLICY["kaggle"]["is_private"], True)
        self.assertIs(POLICY["kaggle"]["enable_internet"], True)

    def test_load_policy_rejects_public(self) -> None:
        broken = json.loads(json.dumps(POLICY))
        broken["kaggle"]["is_private"] = False
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "policy.yml"
            import yaml

            path.write_text(yaml.safe_dump(broken), encoding="utf-8")
            with self.assertRaises(ValueError):
                kp.load_policy(path)

    def test_recipe_matches_reqs(self) -> None:
        training = POLICY["training"]
        self.assertEqual(training["resolution"], [1024, 1024])
        self.assertEqual(training["network_dim"], 32)
        self.assertEqual(training["network_alpha"], 16)
        self.assertEqual(training["max_train_epochs"], 10)
        self.assertIs(training["no_half_vae"], True)
        self.assertEqual(training["min_snr_gamma"], 5)
        self.assertEqual(POLICY["expected"]["steps"], 360)

    def test_framework_is_pinned(self) -> None:
        framework = POLICY["framework"]
        self.assertRegex(framework["commit"], r"^[0-9a-f]{40}$")
        self.assertEqual(framework["script"], "sdxl_train_network.py")


class RenderTests(unittest.TestCase):
    def test_kernel_metadata_is_private_gpu_script(self) -> None:
        metadata = kp.render_kernel_metadata(POLICY, "tyokouchi")
        self.assertEqual(metadata["id"], "tyokouchi/yamazaki-shishi-sdxl-lora")
        self.assertEqual(metadata["kernel_type"], "script")
        self.assertEqual(metadata["code_file"], "train_lora.py")
        self.assertIs(metadata["is_private"], True)
        self.assertIs(metadata["enable_gpu"], True)
        self.assertIs(metadata["enable_tpu"], False)
        self.assertEqual(metadata["dataset_sources"], [POLICY["kaggle"]["dataset_slug"]])
        self.assertEqual(metadata["kernel_sources"], [])

    def test_kernel_id_validation(self) -> None:
        self.assertEqual(kp.validate_kernel_id("owner/slug"), "owner/slug")
        for bad in ("Owner/slug", "owner", "owner/slug/extra", "o/s", "owner/sl ug"):
            with self.assertRaises(ValueError):
                kp.validate_kernel_id(bad)

    def test_dataset_toml_paths_and_buckets(self) -> None:
        text = kp.render_dataset_toml(POLICY)
        config = tomllib.loads(text)
        subset = config["datasets"][0]["subsets"][0]
        self.assertEqual(subset["image_dir"], kp.TRAIN_IMAGE_DIR)
        self.assertEqual(subset["caption_extension"], ".txt")
        self.assertEqual(config["datasets"][0]["batch_size"], 1)
        self.assertEqual(config["datasets"][0]["resolution"], [1024, 1024])
        self.assertIs(config["general"]["enable_bucket"], True)
        self.assertEqual(config["general"]["bucket_reso_steps"], 64)

    def test_run_config_steps_and_overrides(self) -> None:
        base = kp.render_run_config(POLICY)
        self.assertEqual(base["training"]["steps_expected"], 360)
        self.assertEqual(base["sd_scripts"]["ref"], "v0.12.3")

        tweaked = kp.render_run_config(POLICY, epochs=4, dim=16)
        self.assertEqual(tweaked["training"]["max_train_epochs"], 4)
        self.assertEqual(tweaked["training"]["network_dim"], 16)
        self.assertEqual(tweaked["training"]["steps_expected"], 144)

    def test_build_kernel_writes_bundle_and_changes_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            build_dir = Path(tmp) / "bundle"
            first = kp.build_kernel(POLICY, "tyokouchi", build_dir=build_dir)
            for name in ("train_lora.py", "dataset.toml", "run_config.json", "kernel-metadata.json"):
                self.assertTrue((build_dir / name).is_file(), name)
            written = json.loads((build_dir / "run_config.json").read_text(encoding="utf-8"))
            self.assertEqual(written["training"]["network_dim"], 32)

            second = kp.build_kernel(POLICY, "tyokouchi", dim=8, build_dir=build_dir)
            self.assertNotEqual(first["bundle_sha256"], second["bundle_sha256"])
            self.assertEqual(second["network_dim"], 8)

    def test_cmd_train_always_rebuilds_with_overrides(self) -> None:
        calls: list[dict] = []

        def fake_build(policy, **kwargs):
            calls.append(kwargs)
            return {"bundle_sha256": "a" * 64, "steps_expected": 72, "network_dim": kwargs.get("dim")}

        args = argparse.Namespace(
            execute=False, kernel="tyokouchi/yamazaki-shishi-sdxl-lora",
            owner=None, epochs=2, dim=16, timeout=600,
        )
        with mock.patch.object(kp, "load_policy", return_value=POLICY), \
                mock.patch.object(kp, "resolve_kernel", return_value=args.kernel), \
                mock.patch.object(kp, "build_kernel", side_effect=fake_build):
            self.assertEqual(kp.cmd_train(args), 0)
        self.assertEqual(calls[0]["epochs"], 2)
        self.assertEqual(calls[0]["dim"], 16)
        self.assertEqual(calls[0]["kernel_id"], args.kernel)


class GateTests(unittest.TestCase):
    def test_gate_accepts_matching_zip(self) -> None:
        rows = [manifest_row("a"), manifest_row("b")]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            zip_path, approval = synthetic_dataset(root, rows)
            result = kp.dataset_gate(zip_path, approval, root / "missing-summary.json", root=root)
            expected = hashlib.sha256(zip_path.read_bytes()).hexdigest()
        self.assertEqual(result["images"], 2)
        self.assertEqual(result["sha256"], expected)

    def test_gate_rejects_tampered_manifest(self) -> None:
        rows = [manifest_row("a")]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            zip_path, approval = synthetic_dataset(root, rows)
            record = json.loads(approval.read_text(encoding="utf-8"))
            record["manifest_sha256"] = "0" * 64
            approval.write_text(json.dumps(record), encoding="utf-8")
            with self.assertRaises(RuntimeError) as ctx:
                kp.dataset_gate(zip_path, approval, root / "missing.json", root=root)
        self.assertIn("manifest.json changed", str(ctx.exception))

    def test_gate_rejects_changed_zip(self) -> None:
        rows = [manifest_row("a")]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            zip_path, approval = synthetic_dataset(root, rows)
            summary = root / "summary.json"
            summary.write_text(json.dumps({"sha256": "f" * 64}), encoding="utf-8")
            with self.assertRaises(RuntimeError) as ctx:
                kp.dataset_gate(zip_path, approval, summary, root=root)
        self.assertIn("no longer matches", str(ctx.exception))

    def test_gate_rejects_missing_approval(self) -> None:
        rows = [manifest_row("a")]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            zip_path, _ = synthetic_dataset(root, rows)
            with self.assertRaises(RuntimeError):
                kp.dataset_gate(zip_path, root / "absent.json", root / "missing.json", root=root)

    def test_gate_rejects_source_media(self) -> None:
        rows = [manifest_row("a")]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            zip_path, approval = synthetic_dataset(root, rows)
            with zipfile.ZipFile(zip_path, "a") as archive:
                archive.writestr("source_videos/clip.mp4", b"video")
            with self.assertRaises(RuntimeError) as ctx:
                kp.dataset_gate(zip_path, approval, root / "missing.json", root=root)
        self.assertIn("source media", str(ctx.exception))

    def test_stage_dataset_rejects_zip_slip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            zip_path = root / "evil.zip"
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr("../escaped.txt", "no")
            with self.assertRaises(RuntimeError):
                kp.stage_dataset(zip_path, root / "stage")
            self.assertFalse((root / "escaped.txt").exists())

    def test_real_dataset_gate_when_approval_present(self) -> None:
        zip_path = ROOT / POLICY["kaggle"]["dataset_zip"]
        approval = ROOT / "data/approvals/dataset-approval.json"
        if not zip_path.is_file() or not approval.is_file():
            self.skipTest("approved dataset artifacts are not present in this checkout")
        result = kp.dataset_gate(zip_path, approval, ROOT / "runs/summary.json")
        self.assertEqual(result["images"], POLICY["expected"]["dataset_images"])


class SecretTests(unittest.TestCase):
    def test_redact_strips_token_shapes(self) -> None:
        text = "token KGAT_abcdef123456 and header Bearer abc.def-ghi"
        cleaned = kp.redact(text)
        self.assertNotIn("abcdef123456", cleaned)
        self.assertNotIn("abc.def-ghi", cleaned)
        self.assertIn("[redacted]", cleaned)

    def test_redact_strips_environment_values(self) -> None:
        with mock.patch.dict(os.environ, {"KAGGLE_KEY": "super-secret-value"}, clear=False):
            cleaned = kp.redact("key=super-secret-value")
        self.assertEqual(cleaned, "key=[redacted]")

    def test_run_cli_error_never_echoes_token(self) -> None:
        completed = mock.Mock(returncode=1, stdout="", stderr="failed with KGAT_leaked123")
        with mock.patch.object(kp.subprocess, "run", return_value=completed):
            with self.assertRaises(RuntimeError) as ctx:
                kp.run_cli(["true"])
        self.assertNotIn("leaked123", str(ctx.exception))


class StatusTests(unittest.TestCase):
    def test_parse_status(self) -> None:
        self.assertEqual(kp.parse_status("KernelWorkerStatus.RUNNING"), "RUNNING")
        self.assertEqual(kp.parse_status("KernelWorkerStatus.COMPLETE"), "COMPLETE")
        self.assertIsNone(kp.parse_status("no status here"))

    def test_terminal_sets(self) -> None:
        for status in ("COMPLETE", "ERROR", "CANCEL_ACKNOWLEDGED"):
            self.assertTrue(kp.is_terminal(status))
        for status in ("RUNNING", "QUEUED", None):
            self.assertFalse(kp.is_terminal(status))

    def test_remote_dataset_refs_parses_csv(self) -> None:
        completed = mock.Mock(
            returncode=0,
            stdout="ref,title,size\ntyokouchi/one,one,0\nother/two,two,0\n",
            stderr="",
        )
        with mock.patch.object(kp.subprocess, "run", return_value=completed):
            refs = kp.remote_dataset_refs()
        self.assertEqual(refs, {"tyokouchi/one", "other/two"})

    def test_status_command_only_fails_on_bad_terminal(self) -> None:
        args = argparse.Namespace(owner=None, kernel="tyokouchi/yamazaki-shishi-sdxl-lora")
        with mock.patch.object(kp, "load_policy", return_value=POLICY), \
                mock.patch.object(kp, "kernel_status", return_value="RUNNING"):
            self.assertEqual(kp.cmd_status(args), 0)
        with mock.patch.object(kp, "load_policy", return_value=POLICY), \
                mock.patch.object(kp, "kernel_status", return_value="ERROR"):
            self.assertEqual(kp.cmd_status(args), 1)


class TrainingScriptTests(unittest.TestCase):
    def test_training_script_is_syntax_valid_and_has_no_credentials(self) -> None:
        source = (ROOT / "kaggle/train_lora.py").read_text(encoding="utf-8")
        compile(source, "kaggle/train_lora.py", "exec")
        lowered = source.lower()
        for forbidden in ("kaggle_key", "kaggle_api_token", "kaggle.json", "kgat_"):
            self.assertNotIn(forbidden, lowered)

    def test_training_command_contains_safe_flags(self) -> None:
        config = kp.render_run_config(POLICY)
        command = kp_source_command(config)
        for flag in (
            "--network_train_unet_only",
            "--cache_latents_to_disk",
            "--cache_text_encoder_outputs_to_disk",
            "--no_half_vae",
            "--gradient_checkpointing",
            "--sdpa",
        ):
            self.assertIn(flag, command)
        self.assertIn("--dataset_config", command)
        self.assertNotIn("--no_half_vae", command[command.index("--min_snr_gamma"):])


def kp_source_command(config: dict) -> list[str]:
    """Extract build_command from the training script without importing bpy/torch."""
    namespace: dict = {"__name__": "train_lora_under_test", "__file__": str(ROOT / "kaggle/train_lora.py")}
    source = (ROOT / "kaggle/train_lora.py").read_text(encoding="utf-8")
    exec(compile(source, "kaggle/train_lora.py", "exec"), namespace)  # noqa: S102
    return namespace["build_command"](config)


if __name__ == "__main__":
    unittest.main()
