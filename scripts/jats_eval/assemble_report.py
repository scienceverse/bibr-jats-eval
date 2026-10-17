#!/usr/bin/env python3
"""REPORT.template.md + work/report_parts/{results,throughput}.md + work/agreement.md -> REPORT.md.
Usage: assemble_report.py HEADLINE_FILE"""
import os
import sys
from pathlib import Path
W = Path(os.environ.get("JATS_WORK", "~/dev/jats-eval-2026-10-15")).expanduser()
s = (W / "REPORT.template.md").read_text()
part = lambda p, d: (W / p).read_text().strip() if (W / p).is_file() else d
s = s.replace("{{HEADLINE}}", part(sys.argv[1], "**Headline:** pending.") if len(sys.argv) > 1 else "**Headline:** pending.")
s = s.replace("{{AGREEMENT}}", part("work/agreement.md", "(missing)"))
s = s.replace("{{RESULTS}}", part("work/report_parts/results.md", "(missing)") + "\n\n"
              + part("work/report_parts/scan_vs_born.md", ""))
s = s.replace("{{THROUGHPUT}}", part("work/report_parts/throughput.md", "The throughput run has not finished yet."))
(W / "REPORT.md").write_text(s)
print("wrote", W / "REPORT.md", len(s), "chars")
