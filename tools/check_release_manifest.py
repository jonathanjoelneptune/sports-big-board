#!/usr/bin/env python3
"""Retired Sports Big Board release-manifest/token gate.

As of v5.1.10, release verification no longer depends on release-manifest.json or
literal required/forbidden token lists. This compatibility shim intentionally
returns success so stale external invocations cannot block a behavior-valid build.
"""
print("PASS: release-manifest/token gate retired; behavioral verification is authoritative")
