# Local-first Python runner

The workflow YAML files remain the canonical policy. This runner executes a limited subset locally.

## Setup (Windows PowerShell)

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-local.txt
```

## Commands

```powershell
python run_workflow.py validate
python run_workflow.py dataset
python run_workflow.py dataset --execute
python run_workflow.py package
python run_workflow.py kaggle-plan
```

- `validate`: checks the four workflow YAML files and safety defaults.
- `dataset`: dry-run by default; requires approved source/domain and video-selection records. It reads local files only and never downloads videos.
- `dataset --execute`: extracts frames at the interval specified in workflow 03, deduplicates with a simple 64-bit average hash, and creates image/caption pairs plus a manifest and contact sheet. Captions are placeholders and require manual review.
- `package`: requires `data/approvals/dataset-approval.json` with `{"approved": true}`; validates image/caption pairs and creates a ZIP without overwriting an existing archive.
- `kaggle-plan`: creates a local dry-run upload plan. It never connects to Kaggle or uploads.

## Expected local files

```text
workflows/01-domain-decision.yml
workflows/02-reference-video-selection.yml
workflows/03-dataset-preparation.yml
workflows/04-kaggle-integration.yml
selected-videos.yml
data/local-videos/
data/approvals/domain-decision.json
data/approvals/approval-record.json
data/approvals/dataset-approval.json
```

Use `selected-videos.example.yml` as a template. Approval records must be written only after actual human review; do not treat examples as evidence of permission. Keep source videos and credentials out of the dataset ZIP. No Kaggle upload, training, or remote side effect is implemented.
