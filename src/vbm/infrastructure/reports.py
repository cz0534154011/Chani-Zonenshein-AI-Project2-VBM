"""VBM report files: saving the final report as Markdown (infrastructure layer)."""

from datetime import datetime
from pathlib import Path


# שמירת הדוח לקובץ Markdown
def save_report(text: str, seed: int, out_dir: str = "reports") -> Path:
    """Write the report to <out_dir>/report_<time>_seed<seed>.md and return the path."""
    folder = Path(out_dir)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"report_{datetime.now():%Y%m%d_%H%M%S}_seed{seed}.md"
    path.write_text(text, encoding="utf-8")
    return path
