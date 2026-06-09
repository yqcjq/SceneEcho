"""KB (Knowledge Base) package — Phase 1B.

The KB is the persistent template library: every successfully extracted
TemplateIR is stored in the existing ``data/kb.sqlite`` under a new
``templates`` table. Each template optionally links back to the extract
task that produced it so the workbench replay endpoint can rebuild the
event stream by reading the JSONL referenced through
``tasks.events_jsonl_path``.
"""
