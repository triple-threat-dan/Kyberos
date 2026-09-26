"""
HeartbeatManager: The Pulse of Kyberos.

Tracks user activity to determine "idle" states and manages the triggering
of the "Dream Cycle" (maintenance/summarization and scheduled checks).
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from uuid import uuid4

from pydantic import Field, create_model

from kyberos.brain.decision_engine import DecisionEngine
from kyberos.core.config import KYBEROS_ROOT, load_config
from kyberos.core.database import AuditLogger
from kyberos.memory import timeline

logger = logging.getLogger("kyberos.core.heartbeat")


def _heartbeat_tasks(content: str) -> list[dict[str, str]]:
    """Read task bullets while ignoring examples inside HTML comments."""
    visible_content = re.sub(r"<!--.*?-->", "", content, flags=re.DOTALL)
    section = "Tasks"
    tasks = []
    for line in visible_content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            section = stripped.lstrip("#").strip()
        elif stripped.startswith("- "):
            tasks.append({"section": section, "line": stripped})
    return tasks


async def _actionable_heartbeat_tasks(
    tasks: list[dict[str, str]], config
) -> tuple[list[dict[str, str]], bool]:
    """Classify each task against one captured local time; retain all on failure."""
    if not config.keys.typesafe:
        return tasks, False

    questions = {
        f"task_{index}": (
            bool,
            Field(description=(
                f"Is `tasks[{index}]` actionable at `current_time`? Check its date, day, "
                "recurrence, completion tag, and time window. Future or elapsed windows "
                "are not actionable; an untimed pending task is actionable."
            )),
        )
        for index in range(len(tasks))
    }
    schema = create_model("HeartbeatTaskDecisions", **questions)
    try:
        decision = await DecisionEngine(config).decide(
            schema,
            {"tasks": tasks, "current_time": datetime.now().astimezone().isoformat()},
        )
        return [task for index, task in enumerate(tasks) if getattr(decision, f"task_{index}")], True
    except Exception as e:
        logger.warning("Heartbeat task triage failed; retaining all tasks: %s", e)
        return tasks, False


class HeartbeatManager:
    """
    Tracks user activity to determine if the agent is 'idle'.
    """
    _instance: Optional['HeartbeatManager'] = None

    def __init__(self, audit_logger: Optional[AuditLogger] = None):
        self._last_active_timestamp: datetime = datetime.now()
        self.audit_logger = audit_logger
        logger.debug(f"HeartbeatManager initialized at {self._last_active_timestamp}")

    @classmethod
    def get_instance(cls) -> 'HeartbeatManager':
        """Singleton accessor."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def touch(self) -> None:
        """Updates the last active timestamp to now."""
        self._last_active_timestamp = datetime.now()

    def is_idle(self, threshold_minutes: int = 30) -> bool:
        """Returns True if no activity has been detected for the threshold."""
        delta = datetime.now() - self._last_active_timestamp
        is_idle = delta > timedelta(minutes=threshold_minutes)
        if is_idle:
            logger.debug(f"Heartbeat: System is idle (inactive for {delta}).")
        return is_idle

    @property
    def last_active(self) -> datetime:
        return self._last_active_timestamp


# ==============================================================================
# Dream Cycle Logic
# ==============================================================================

def can_dream() -> bool:
    """
    Determines if conditions are right to enter the Dream Cycle.
    
    Conditions:
    1. User is idle (Collision Avoidance).
    2. Data is available (Session log has content).
    """
    hb = HeartbeatManager.get_instance()
    
    if not hb.is_idle(threshold_minutes=30):
        logger.info("Skipping Dream Cycle: User is active.")
        return False

    log_path = KYBEROS_ROOT / "logs" / "current_session.log"
    
    if not log_path.exists() or log_path.stat().st_size == 0:
        logger.debug("Skipping Dream Cycle: No session log found or log is empty.")
        return False
        
    return True

async def run_dream_cycle_task():
    """APScheduler task wrapper for the Dream Cycle."""
    logger.debug("Heartbeat: Checking Dream Cycle conditions...")
    
    if can_dream():
        logger.info("Heartbeat: Conditions met. Entering Dream Cycle... 💤")
        try:
            await timeline.perform_dream_cycle()
            logger.info("Heartbeat: Woke up from Dream Cycle.")
        except Exception as e:
            logger.error(f"Heartbeat: Nightmare detected (Dream Cycle failed): {e}")


# ==============================================================================
# Periodic Check Logic
# ==============================================================================

def is_within_active_hours(window_str: str) -> bool:
    """Checks if the current time falls within the HH:MM-HH:MM window."""
    try:
        start_str, end_str = window_str.split('-')
        now = datetime.now()
        current_minutes = now.hour * 60 + now.minute
        
        sh, sm = map(int, start_str.split(':'))
        eh, em = map(int, end_str.split(':'))
        
        start_minutes = sh * 60 + sm
        end_minutes = eh * 60 + em
        
        if end_minutes < start_minutes:  # Crosses midnight
            return current_minutes >= start_minutes or current_minutes <= end_minutes
        
        return start_minutes <= current_minutes <= end_minutes
    except Exception as e:
         logger.warning(f"Heartbeat: Could not parse active hours '{window_str}': {e}")
         return True  # Fail open

async def run_heartbeat_task(command_bus: Optional[asyncio.Queue] = None):
    """
    APScheduler task for periodic pulse checks.
    
    Checks for pending tasks in HEARTBEAT.md during active hours.
    """
    logger.info("Heartbeat: Pulse triggered.")

    hb = HeartbeatManager.get_instance()
    config = load_config()
    active_window = config.agents.defaults.heartbeat.active_hours
    
    in_hours = is_within_active_hours(active_window)
    status = "ALIVE" if in_hours else "SKIPPED"

    if not in_hours:
        logger.info(f"Heartbeat: Outside active hours ({active_window}). Pulse skipped.")

    heartbeat_file = KYBEROS_ROOT / "HEARTBEAT.md"
    
    if hb.audit_logger:
        await hb.audit_logger.log_heartbeat(status=status, meta={
            "active_window": active_window, 
            "in_hours": in_hours,
            "has_heartbeat_file": heartbeat_file.exists()
        })

    if status == "SKIPPED" or not heartbeat_file.exists():
        return

    content = heartbeat_file.read_text(encoding="utf-8")
    tasks = _heartbeat_tasks(content)
    if tasks:
        if not command_bus:
            logger.warning("Heartbeat: No command_bus connection!")
            return

        actionable_tasks, triage_verified = await _actionable_heartbeat_tasks(tasks, config)
        if not actionable_tasks:
            logger.info("Heartbeat: No tasks actionable in the current time window.")
            return

        logger.info("Heartbeat: %d actionable tasks detected. Waking agent...", len(actionable_tasks))
        
        heartbeat_path = str(heartbeat_file.resolve())
        session_id = f"heartbeat-{uuid4()}"
        
        selected_content = "\n".join(
            f"### {task['section']}\n{task['line']}" for task in actionable_tasks
        )
        time_guidance = "" if triage_verified else (
            f"Time prefilter unavailable. Current local time: {datetime.now().astimezone().isoformat()}. "
            "Check each candidate's time condition before acting; skip future, elapsed, or completed tasks.\n"
        )
        prompt = (
            "🔴 **SYSTEM HEARTBEAT TRIGGERED**\n\n"
            f"The system heartbeat has activated. Review the tasks from `{heartbeat_path}`.\n\n"
            f"{time_guidance}"
            "**RULES & STATE TRACKING:**\n"
            "1. **Clean Thread**: You are starting with a clean thread for this heartbeat. Ignore your main background tasks.\n"
            "2. **Recurring Task Tracking**: When you complete a **Recurring Task**, you MUST mutate the `HEARTBEAT.md` file to append a timestamp tag to the end of that specific task line: `[LAST COMPLETED: YYYY-MM-DD]`. Example: `- Between 10am and 11am... [LAST COMPLETED: 2026-02-21]`\n"
            "3. **One-time Tasks**: After completing a one-time reminder, remove it from the `One-time Reminders` section as usual.\n"
            "4. **No History**: Do NOT track heartbeat task progress in HEARTBEAT.md — use it ONLY for final completion tags.\n\n"
            f"**{'SELECTED' if triage_verified else 'CANDIDATE'} TASKS:**\n```markdown\n{selected_content}\n```\n\n"
            "**EXECUTION INSTRUCTIONS:**\n"
            "Execute listed tasks that are due using the available tools. Only update HEARTBEAT.md with final completion tags or removal of completed one-time tasks.\n"
        )
        
        try:
            await command_bus.put({
                "level": "USER",
                "message": prompt,
                "source": "HEARTBEAT",
                "session_id": session_id,
                "heartbeat_source_content": selected_content,
                "heartbeat_prechecked": True,
            })
        except Exception as ex:
            logger.error(f"Heartbeat Bus Error: {ex}")
    else:
        logger.debug("Heartbeat: No pending tasks found in HEARTBEAT.md.")
