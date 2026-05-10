# Presentation draft

| File | Use |
|------|-----|
| `LOG_RCA_DRAFT.md` | Edit Mermaid source; renders on GitHub / VS Code |
| `LOG_RCA_DRAFT.html` | Open in browser → **Print → Save as PDF** (best diagram fidelity) |
| `LOG_RCA_DRAFT.pdf` | Pre-generated snapshot (re-run Chrome headless if you change the HTML) |

Regenerate PDF on Windows (Chrome installed):

```powershell
$html = "docs/presentation/LOG_RCA_DRAFT.html"
$pdf  = "docs/presentation/LOG_RCA_DRAFT.pdf"
& "$env:ProgramFiles\Google\Chrome\Application\chrome.exe" `
  --headless --disable-gpu --virtual-time-budget=8000 --no-pdf-header-footer `
  --print-to-pdf="$((Resolve-Path $pdf))" "file:///$((Resolve-Path $html) -replace '\\','/')"
```
