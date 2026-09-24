import re
import threading
from enum import Enum
from pathlib import Path
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from kyberos.core.config import KYBEROS_ROOT


class ContextStaleError(Exception):
    """Raised when the agent's context is invalid due to user intervention."""


class ThreadState(str, Enum):
    NEW = "NEW"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"


class ThreadModel(BaseModel):
    prime_directive: str = Field(description="The high-level goal or 'Why'.")
    plan_steps: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of steps, e.g., [{'step': 'Do X', 'completed': False}]"
    )
    working_memory: str = Field(default="", description="Scratchpad notes.")
    thread_path: Path = Field(
        default_factory=lambda: KYBEROS_ROOT / "memories" / "THREAD.md",
        description="Path to the thread file."
    )
    state: ThreadState = Field(default=ThreadState.NEW, description="Derived state of the thread.")

    def get_active_step(self) -> Optional[str]:
        """Returns the text of the first incomplete step."""
        for step in self.plan_steps:
            if not step.get("completed", False):
                return step.get("step")
        return None


class ThreadManager:
    """
    Manages the 'Working Memory' of the agent by syncing with a Markdown file.
    Acts as a synchronization primitive between Human and AI.
    """

    DEFAULT_TEMPLATE = """# 🔮 THE THREAD (Current State)

## 🎯 Prime Directive (The "Why")
(Waiting for command...)

## 📋 Plan of Action (The "How")
- [ ] Await instructions

## 🧠 Working Memory (Scratchpad)
- System initialized.
"""

    # Pre-compiled regex patterns — avoids recompilation on every parse call.
    _RE_PRIME = re.compile(r'## 🎯 Prime Directive.*?\n(.*?)(?=\n##|\Z)', re.DOTALL | re.IGNORECASE)
    _RE_PLAN = re.compile(r'## 📋 Plan of Action.*?\n(.*?)(?=\n##|\Z)', re.DOTALL | re.IGNORECASE)
    _RE_MEMORY = re.compile(r'## 🧠 Working Memory.*?\n(.*?)(?=\n##|\Z)', re.DOTALL | re.IGNORECASE)
    _RE_STEP = re.compile(r'-\s*\[([ xX])\]\s*(.*)')

    def __init__(self, thread_file_path: Path):
        self._thread_file_path = thread_file_path
        self._is_stale = False
        self._lock = threading.Lock()

    def notify_user_edit(self):
        """Signal that the user has modified the thread file manually."""
        with self._lock:
            self._is_stale = True

    def check_for_interrupt(self):
        """Checks if the context is stale. If so, raises ContextStaleError to restart reasoning."""
        with self._lock:
            if self._is_stale:
                self._is_stale = False
                raise ContextStaleError("Thread file was modified by user. Restarting context.")

    def clear(self):
        """Resets the thread file to the default idle state."""
        self._write_to_file(self.DEFAULT_TEMPLATE)

    def load(self) -> ThreadModel:
        """Parses the THREAD.md file into a structured model. Robust to missing sections."""
        return self._parse_markdown(self._read_from_file())

    def update_plan(self, new_plan: ThreadModel):
        """Serializes the model to Markdown and overwrites THREAD.md."""
        self._write_to_file(self._serialize_model(new_plan))

    def _read_from_file(self) -> str:
        if not self._thread_file_path.exists():
            return ""
        return self._thread_file_path.read_text(encoding="utf-8")

    def _write_to_file(self, content: str):
        self._thread_file_path.parent.mkdir(parents=True, exist_ok=True)
        self._thread_file_path.write_text(content, encoding="utf-8")

    def _parse_markdown(self, content: str) -> ThreadModel:
        """Parses raw markdown content into a ThreadModel."""
        prime_match = self._RE_PRIME.search(content)
        plan_match = self._RE_PLAN.search(content)
        memory_match = self._RE_MEMORY.search(content)

        prime_directive = prime_match.group(1).strip() if prime_match else ""
        raw_plan = plan_match.group(1).strip() if plan_match else ""
        working_memory = memory_match.group(1).strip() if memory_match else ""

        # Parse plan steps from checkbox lines
        steps = []
        for line in raw_plan.split('\n'):
            match = self._RE_STEP.match(line.strip())
            if match:
                steps.append({
                    "step": match.group(2).strip(),
                    "completed": match.group(1).lower() == 'x',
                })

        # Derive state in a single pass over the completed flags
        if not steps:
            state = ThreadState.NEW
        else:
            completed = {s['completed'] for s in steps}
            if completed == {True}:
                state = ThreadState.COMPLETE
            elif completed == {False}:
                state = ThreadState.NEW
            else:
                state = ThreadState.IN_PROGRESS

        return ThreadModel(
            prime_directive=prime_directive,
            plan_steps=steps,
            working_memory=working_memory,
            state=state,
        )

    def _serialize_model(self, model: ThreadModel) -> str:
        """Converts ThreadModel back to the specific Markdown format."""
        directive = model.prime_directive or "(No directive set)"
        memory = model.working_memory or "(Empty)"

        if model.plan_steps:
            plan_lines = [
                f"- [{'x' if s['completed'] else ' '}] {s['step']}"
                for s in model.plan_steps
            ]
        else:
            plan_lines = ["- [ ] (No steps defined)"]

        return "\n".join([
            '# 🔮 THE THREAD (Current State)',
            '',
            '## 🎯 Prime Directive (The "Why")',
            directive,
            '',
            '## 📋 Plan of Action (The "How")',
            *plan_lines,
            '',
            '## 🧠 Working Memory (Scratchpad)',
            memory,
            '',
        ])
