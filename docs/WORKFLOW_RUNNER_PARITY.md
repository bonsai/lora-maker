# Workflow 03 / local runner parity

This table records the implemented MVP contract. The YAML is the policy source; the Python runner intentionally implements only the local, approval-gated subset.

| Workflow declaration / behavior | MVP status | Runner behavior |
| --- | --- | --- |
| Domain and video-selection approvals | Implemented | `preflight` validates evidence, use scopes, selected IDs, dates, and local paths before execution. |
| Video acquisition adapter | Excluded | Manual placement only: the human places permission-cleared files under `data/local-videos/`. No download, network call, or adapter is invoked. |
| `frames.output_dir` | Aligned by configuration | Set to `data/dataset/images`, the runner's actual output location. |
| Interval extraction / source timestamps | Implemented | OpenCV reads approved local files and records timestamps. |
| Perceptual deduplication | Implemented | Hamming-distance threshold is applied across selected videos. Duplicate count/report is not currently emitted. |
| Blur, tiny/occluded subject, and automatic quality filters | Excluded | No automatic quality classifier or resize pass. Human reviews the contact sheet and every image/caption. No automatic deletion. |
| Corrupt source/video read | Fail closed where detectable | An unopenable local video or failed image write stops execution. The runner does not produce a separate rejected-frame report. |
| Captions | Partially implemented | Writes a placeholder caption per image. Factual descriptions are not generated or automatically verified; human correction/review is mandatory. |
| Image/caption pairs, non-empty captions, source approval | Implemented at generation/package gates | Packaging checks files exist, captions are non-empty, source approval is present, and hashes still match. |
| Per-image `review_status` | Removed from MVP schema | No status field is emitted. Human dataset approval must confirm the complete contact sheet and captions and bind to `manifest_sha256` + `content_sha256`. |
| Contact sheet | Implemented | Generates `data/review/contact-sheet.jpg` for human inspection. |
| Package ZIP and integrity | Implemented | Requires dataset approval, re-hashes files, rejects stale unmanifested images/captions, refuses ZIP overwrite, and verifies the archive. |
| Kaggle | Plan only | `kaggle-plan` writes a local plan with `visibility: private` and `upload_executed: false`; it does not upload. |
| LoRA training / public release | Out of scope | No training or public-release implementation in this workflow. Separate future scope and explicit approval required. |

## Manual acceptance checklist

- [ ] Rights and source evidence are human-reviewed; no template is treated as approval.
- [ ] Only manually placed, permitted local files are selected.
- [ ] Contact sheet and every caption are reviewed before dataset approval.
- [ ] Dataset approval records the current manifest and content hashes.
- [ ] CI tests the fail-closed gates on Ubuntu and Windows.
- [ ] No real-media execution, remote upload, training, or public release is performed by CI.
