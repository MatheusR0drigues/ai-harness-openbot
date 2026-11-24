# Design Document

## Overview

`audit export` streams events from the local database to standard output.

## Threat Model

| Threat | Control | Verified by |
| :-- | :-- | :-- |
| Personal data in exported events | Redact the `email` field before writing | `test_export.py::test_redacts_email` |
