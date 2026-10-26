---
name: Prepare private Yamazaki Shishi dataset
description: Review approved reference videos and prepare a private SDXL LoRA dataset plan.
on:
  workflow_dispatch:
    inputs:
      mode:
        description: "dry-run only; actual acquisition requires separate explicit approval"
        required: true
        default: "dry-run"
        type: choice
        options:
          - dry-run
          - review-plan
tools:
  github:
    toolsets:
      - repos
      - issues
      - pull_requests
safe-outputs:
  create-issue:
    max: 1
  add-comment:
    max: 3
---

# Dataset Preparation — ヤマザキシシ

Prepare a reviewable plan for a **private experiment only**. This workflow must not download videos, extract frames, create or upload a dataset, train a model, or change dataset visibility. Those actions require a separately implemented deterministic worker and explicit human approval.

## Canonical inputs

Read these repository files before making recommendations:

- `workflows/01-domain-decision.yml`
- `workflows/02-reference-video-selection.yml`
- `workflows/03-dataset-preparation.yml`
- `workflows/04-kaggle-integration.yml`

Treat the YAML files as the detailed pipeline specification. This AW workflow provides reasoning, validation, and a human-review handoff; it does not replace deterministic media-processing code.

## Required procedure

1. Confirm the domain decision is approved and the intended use remains `private_experiment` with `private_dataset` visibility.
2. Inspect whether `selected-videos.yml`, `approval-record.json`, and `domain-decision.json` exist in the repository. Do not fabricate missing artifacts or approvals.
3. If approved video selections or evidence are missing, stop the preparation stage and create a concise review issue listing the missing inputs. Ask the owner to confirm which videos are representative and whether their sources and terms permit the intended use.
4. If inputs exist, validate that every candidate has a source URL, video ID, provenance, permission status, and a human-review decision. Treat unknown permission as not approved.
5. Produce a dry-run plan only: target 7 approved videos; OpenCV PNG extraction at 1-second intervals; preserve aspect ratio; perceptual-hash deduplication; one reviewed caption sidecar per image; manifest and contact sheet; ZIP excludes source videos, caches, logs, temporary files, and credentials.
6. Flag any uncertainty, missing permission evidence, identity ambiguity, or proposed public exposure. Do not infer identity from appearance alone.
7. Report the exact next steps and required human approvals. Use a GitHub issue or comment only for the review handoff.

## Hard safety rules

- Never download or process media in this AW run.
- Never bypass access controls or platform restrictions.
- Public availability is not proof of permission for training.
- Never expose credentials, cookies, tokens, or secrets.
- Never upload to Kaggle, start training, publish assets, or switch visibility.
- Never overwrite existing artifacts or remote datasets without a reviewed diff and explicit approval.
- If the run mode is `dry-run`, perform inspection and reporting only.
- If required evidence is absent or contradictory, stop and report the blocker.

## Expected report

Provide:
- input-artifact status;
- approval and provenance gaps;
- a dry-run processing plan;
- privacy and permission risks;
- the exact human decision needed to proceed.

Keep the report concise, factual, and auditable.
