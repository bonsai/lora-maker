# lora-maker

Local-first, approval-gated workflow for building a private SDXL LoRA dataset.

- Workflow policy lives in `workflows/*.yml` (dry-run by default, private visibility only).
- The local runner is `run_workflow.py`; see `LOCAL_RUNNER.md`.
- Rights and permission review requirements are in `docs/RIGHTS_REVIEW.md`.

Nothing here downloads media, uploads to Kaggle, or trains a model.
