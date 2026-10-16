"""Canonical pytest test-ids (E5/O1).

One canonical nodeid per test: ``path::Class::method[param]``. The backend's
``TestSymbol.name`` is already a collected nodeid (``path::Class::method[param]``)
and is also returned as ``test_file`` (the ``path`` part), so blindly
concatenating produces the historical ``path::path::Class::method`` double
prefix. ``canonical_nodeid`` combines the two parts without duplicating the file.
"""
from __future__ import annotations

import os


def canonical_nodeid(test_file: str, test_name: str) -> str:
    """Return the single canonical pytest nodeid for a (file, name) pair.

    - Empty name -> the file itself (module-scope run, e.g. fallback).
    - ``name`` already qualified with the file (exact or basename match,
      absolute-vs-relative insensitive) -> returned unchanged, so the full
      ``path::Class::method[param]`` (including parametrization markers) is
      preserved and never doubled.
    - Otherise -> ``"path::name"`` (covers ``method`` and ``Class::method``).
    """
    f = (test_file or "").strip()
    n = (test_name or "").strip()
    if not f:
        return n
    if not n:
        return f
    nf = n.replace("\\", "/").lstrip("/")
    ff = f.replace("\\", "/").lstrip("/")
    if nf == ff or ff.endswith("/" + nf) or nf.endswith("/" + ff):
        return f
    if "::" in n:
        first = n.split("::", 1)[0].lstrip("/")
        if (first == f.lstrip("/")
                or os.path.basename(first) == os.path.basename(f)):
            return n
    return f"{f}::{n}"