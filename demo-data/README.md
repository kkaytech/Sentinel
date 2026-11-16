# Demo datasets

Synthetic supplier invoice data for demonstrating Sentinel. Upload the two files of a folder
under the reporting period the folder is named after.

| Folder | What it shows |
|---|---|
| `2026-09/` | **Publishable after review.** One waivable blocking issue (invoices for unknown suppliers) and a few warnings. Request a waiver, approve, publish. |
| `2026-10/` | **Cannot be published.** Planted defects of every kind, including duplicate invoice IDs and unparseable amounts, which cannot be waived. Shows findings, drill-down and reporting impact. |
| `2026-11/` | **Clean.** No findings. |

Regenerate with `sh scripts/make_demo_data.sh` (deterministic).
