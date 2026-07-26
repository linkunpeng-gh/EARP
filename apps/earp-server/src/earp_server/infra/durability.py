"""Durability modes — sync / async / exit (langgraph v1.1 §2.6)."""

from __future__ import annotations

from enum import StrEnum


class DurabilityMode(StrEnum):
    SYNC = "sync"  # wait for checkpoint write confirmation before next step
    ASYNC = "async"  # fire-and-forget checkpoint write (default)
    EXIT = "exit"  # only write checkpoint on Plan exit (last step or error)
