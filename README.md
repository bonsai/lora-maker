# lora-maker

Local-first, approval-gated workflow for preparing a private SDXL LoRA dataset.

## MVP scope

The MVP ends at a **human-reviewed dataset ZIP**, with optional private Kaggle registration only after separate explicit approval. It does not train a LoRA, publish media or weights, or automatically upload anything.

## Acquisition policy

The runner uses **manual local placement only**. Put only permission-cleared source files in `data/local-videos/`, record their provenance and permitted uses in the approval evidence, and reference the exact local paths in `selected-videos.yml`. The runner does not download videos, invoke an acquisition adapter, or access the network.

## Workflow and safety

- Workflow policy lives in `workflows/*.yml`; the runner is `run_workflow.py` (see `LOCAL_RUNNER.md`).
- Rights and permission review requirements are in `docs/RIGHTS_REVIEW.md`.
- YAML-to-runner scope and deliberate exclusions are mapped in `docs/WORKFLOW_RUNNER_PARITY.md`.
- Execution is dry-run by default. Human approval records must be based on real evidence; templates are not approvals.
- Packaging is blocked until the contact sheet and captions are reviewed and the manifest/content hashes are approved.
- Private visibility only. No training, public release, or remote side effect is authorized by this MVP.
