# Local-first Python runner

The workflow YAML files remain the canonical policy. This runner executes a limited subset locally; see `docs/WORKFLOW_RUNNER_PARITY.md` for implemented and intentionally excluded behavior.

## Setup (Windows PowerShell)

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-local.txt
```

## Commands

```powershell
python run_workflow.py validate     # YAML safety defaults (dry-run, private visibility)
python run_workflow.py preflight    # read-only list of unresolved approvals; exits 1 when blocked
python run_workflow.py dataset      # dry-run, prints blockers without opening media
python run_workflow.py dataset --execute
# 既存出力を作り直す場合だけ: python run_workflow.py dataset --execute --overwrite
python run_workflow.py package
python run_workflow.py kaggle-plan
```

- `validate`: checks the four workflow YAML files and their safety defaults.
- `preflight`: validates approval records and `selected-videos.yml` field by field. No media, no network.
- `dataset`: dry-run by default; runs the same preflight and lists every unresolved condition. It reads local files only and never downloads videos.
- `dataset --execute`: refuses to start unless preflight is clean and every `local_path` points inside the repository to an existing file. It never downloads media. Also refuses to replace existing images, captions, manifest, or contact sheet unless `--overwrite` is passed explicitly. `--overwrite` deletes previous `.png`/`.txt` files in the images directory before regenerating. Extracts frames at the interval in workflow 03, deduplicates, writes image/caption pairs, a manifest, and a contact sheet. Captions are placeholders; quality assessment and factual caption review are human tasks.
- `package`: requires a complete `data/approvals/dataset-approval.json`, including the `manifest_sha256` and `content_sha256` printed by `dataset --execute`. Re-hashes every image and caption, so edits after approval abort packaging. Also refuses to package when the images directory contains files absent from the manifest. Creates a ZIP without overwriting.
- `kaggle-plan`: creates a local dry-run upload plan. It never connects to Kaggle or uploads.

## Synthetic end-to-end check

```powershell
python tools/poc_synthetic_e2e.py          # temp sandbox, deleted afterwards
python tools/poc_synthetic_e2e.py --keep   # keep the sandbox and print its path
```

Builds a throwaway sandbox in the system temp directory, generates rights-free synthetic videos, and writes sandbox-only approval fixtures to exercise preflight, `dataset --execute`, the overwrite guard, `package`, caption tampering, stale files, `--overwrite` cleanup, and ZIP contents. It refuses to place the sandbox inside the repository and never writes to the repository's `data/approvals`, `data/local-videos`, or `dist`. The fixtures are not rights approvals; this check is not a substitute for the real-media verification in #5.

## Approval records are validated, not just flagged

`approved: true` alone is not enough. Records must also carry evidence references, review dates, and per-use scope. See `docs/RIGHTS_REVIEW.md` and `data/approvals/*.template.json`.

- `domain-decision.json`: rights holder, reviewed sources, evidence entries with `reference` / `checked_at` / `covers`, `private_experiment` + `local_only|private_dataset` scope.
- `approval-record.json`: `selected_video_ids`, `approved_uses` (acquisition / frame_extraction / dataset_creation), explicit `excluded_time_ranges`, a reason per video.
- `selected-videos.yml`: per-video `rights_basis`, `terms_url`, `permitted_uses`, `reviewed_by`, `reviewed_at`, `permission_status: approved`.
- `dataset-approval.json`: `captions_reviewed`, `contact_sheet_reviewed`, `manifest_sha256`, and `content_sha256`. The manifest does not carry a per-image `review_status`; human approval covers the exact hash-bound dataset.

Templates are never treated as approvals. `data/approvals/*.json` is git-ignored because evidence may contain names and private URLs.

## Expected local files

```text
workflows/01-domain-decision.yml
workflows/02-reference-video-selection.yml
workflows/03-dataset-preparation.yml
workflows/04-kaggle-integration.yml
selected-videos.yml                 # copy selected-videos.example.yml, then fill
data/local-videos/                 # manually placed, permission-cleared files only
data/approvals/domain-decision.json
data/approvals/approval-record.json
data/approvals/dataset-approval.json
```

Approval records must be written only after actual human review; do not treat examples as evidence of permission. Keep source videos and credentials out of the dataset ZIP. No media acquisition, Kaggle upload, training, or remote side effect is implemented. Kaggle registration is outside the local dataset-generation path and requires separate explicit approval.
