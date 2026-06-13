#!/usr/bin/env python3
"""Deprecated virulence/temperature prediction step.

This project no longer publishes or maintains virulence/temperature prediction
tables. The previous implementation trained on mostly family-inferred labels
and must not be used for database claims, exports, or manuscript figures.
"""

raise SystemExit(
    "DEPRECATED: virulence/temperature prediction has been removed. "
    "Use manually reviewed evidence records only."
)
