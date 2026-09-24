"""
Unit tests for kyberos.memory.thread_manager.

Tests cover:
- ContextStaleError: exception identity and message propagation
- ThreadState: enum values, string behaviour, membership
- ThreadModel: defaults, get_active_step logic (none/partial/all complete)
- ThreadManager.notify_user_edit / check_for_interrupt: stale flag, reset,
  thread-safety, repeated calls, interleaving
- ThreadManager.clear: writes default template, creates parent dirs
- ThreadManager.load: round-trip from file, missing file, empty file,
  partial sections, multi-step plans, completed/mixed/new states
- ThreadManager.update_plan: serializes model correctly, empty steps,
  no directive, working memory, creates dirs
- ThreadManager._parse_markdown: edge cases — extra whitespace, upper-case
  checkbox marks, unicode content, sections in different orders, step text
  with special characters
- ThreadManager._serialize_model: round-trip consistency, empty model fields
- ThreadManager round-trip: clear ➜ load ➜ verify defaults, update ➜ load
"""

import re
import threading
import time
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# We patch KYBEROS_ROOT at import-time so the default ThreadModel.thread_path
# does not reference the real filesystem.
with patch("kyberos.core.config.KYBEROS_ROOT", Path("/fake/root")):
    from kyberos.memory.thread_manager import (
        ContextStaleError,
        ThreadState,
        ThreadModel,
        ThreadManager,
    )


# ===========================================================================
# Tests: ContextStaleError
# ===========================================================================


class TestContextStaleError:

    def test_is_exception(self):
        assert issubclass(ContextStaleError, Exception)

    def test_can_be_raised_and_caught(self):
        with pytest.raises(ContextStaleError, match="stale"):
            raise ContextStaleError("stale")

    def test_message_propagation(self):
        err = ContextStaleError("custom message")
        assert str(err) == "custom message"

    def test_no_message(self):
        err = ContextStaleError()
        assert str(err) == ""


# ===========================================================================
# Tests: ThreadState Enum
# ===========================================================================


class TestThreadState:

    def test_values(self):
        assert ThreadState.NEW == "NEW"
        assert ThreadState.IN_PROGRESS == "IN_PROGRESS"
        assert ThreadState.COMPLETE == "COMPLETE"

    def test_is_str_subclass(self):
        """ThreadState members should be usable as plain strings."""
        assert isinstance(ThreadState.NEW, str)

    def test_membership(self):
        assert "NEW" in [s.value for s in ThreadState]
        assert "IN_PROGRESS" in [s.value for s in ThreadState]
        assert "COMPLETE" in [s.value for s in ThreadState]

    def test_has_exactly_three_members(self):
        assert len(ThreadState) == 3

    def test_string_comparison(self):
        assert ThreadState.NEW == "NEW"
        assert ThreadState.COMPLETE != "NEW"

    def test_from_value(self):
        assert ThreadState("NEW") is ThreadState.NEW
        assert ThreadState("COMPLETE") is ThreadState.COMPLETE


# ===========================================================================
# Tests: ThreadModel
# ===========================================================================


class TestThreadModel:

    def test_defaults(self):
        model = ThreadModel(prime_directive="Test goal")
        assert model.prime_directive == "Test goal"
        assert model.plan_steps == []
        assert model.working_memory == ""
        assert model.state == ThreadState.NEW

    def test_get_active_step_with_no_steps(self):
        model = ThreadModel(prime_directive="Goal")
        assert model.get_active_step() is None

    def test_get_active_step_first_incomplete(self):
        model = ThreadModel(
            prime_directive="Goal",
            plan_steps=[
                {"step": "Step 1", "completed": False},
                {"step": "Step 2", "completed": False},
            ],
        )
        assert model.get_active_step() == "Step 1"

    def test_get_active_step_skips_completed(self):
        model = ThreadModel(
            prime_directive="Goal",
            plan_steps=[
                {"step": "Step 1", "completed": True},
                {"step": "Step 2", "completed": False},
                {"step": "Step 3", "completed": False},
            ],
        )
        assert model.get_active_step() == "Step 2"

    def test_get_active_step_all_completed(self):
        model = ThreadModel(
            prime_directive="Goal",
            plan_steps=[
                {"step": "Step 1", "completed": True},
                {"step": "Step 2", "completed": True},
            ],
        )
        assert model.get_active_step() is None

    def test_get_active_step_missing_completed_key(self):
        """Steps without a 'completed' key default to incomplete."""
        model = ThreadModel(
            prime_directive="Goal",
            plan_steps=[{"step": "Step 1"}],
        )
        assert model.get_active_step() == "Step 1"

    def test_custom_thread_path(self, tmp_path):
        custom = tmp_path / "THREAD.md"
        model = ThreadModel(prime_directive="X", thread_path=custom)
        assert model.thread_path == custom


# ===========================================================================
# Tests: ThreadManager — Interruption Logic
# ===========================================================================


class TestThreadManagerInterrupt:

    def _make_manager(self, tmp_path):
        return ThreadManager(tmp_path / "THREAD.md")

    def test_check_for_interrupt_no_edit(self, tmp_path):
        """No exception when no user edit has been signalled."""
        mgr = self._make_manager(tmp_path)
        mgr.check_for_interrupt()  # Should not raise

    def test_notify_then_check_raises(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        mgr.notify_user_edit()
        with pytest.raises(ContextStaleError):
            mgr.check_for_interrupt()

    def test_stale_flag_resets_after_check(self, tmp_path):
        """After catching the interrupt the flag should be cleared."""
        mgr = self._make_manager(tmp_path)
        mgr.notify_user_edit()
        with pytest.raises(ContextStaleError):
            mgr.check_for_interrupt()
        # Second call should NOT raise
        mgr.check_for_interrupt()

    def test_multiple_notify_single_raise(self, tmp_path):
        """Multiple notify calls still produce only one raise on the next check."""
        mgr = self._make_manager(tmp_path)
        mgr.notify_user_edit()
        mgr.notify_user_edit()
        mgr.notify_user_edit()
        with pytest.raises(ContextStaleError):
            mgr.check_for_interrupt()
        mgr.check_for_interrupt()  # Should not raise again

    def test_thread_safety_of_notify(self, tmp_path):
        """notify_user_edit called from another thread sets the flag correctly."""
        mgr = self._make_manager(tmp_path)
        barrier = threading.Barrier(2, timeout=5)

        def background():
            barrier.wait()
            mgr.notify_user_edit()

        t = threading.Thread(target=background)
        t.start()
        barrier.wait()
        t.join()

        with pytest.raises(ContextStaleError):
            mgr.check_for_interrupt()

    def test_interleaved_notify_and_check(self, tmp_path):
        """Notify ➜ check ➜ notify ➜ check should raise each time."""
        mgr = self._make_manager(tmp_path)

        mgr.notify_user_edit()
        with pytest.raises(ContextStaleError):
            mgr.check_for_interrupt()

        mgr.notify_user_edit()
        with pytest.raises(ContextStaleError):
            mgr.check_for_interrupt()


# ===========================================================================
# Tests: ThreadManager — clear()
# ===========================================================================


class TestThreadManagerClear:

    def test_clear_writes_default_template(self, tmp_path):
        thread_file = tmp_path / "memories" / "THREAD.md"
        mgr = ThreadManager(thread_file)
        mgr.clear()

        assert thread_file.exists()
        content = thread_file.read_text(encoding="utf-8")
        assert "🔮 THE THREAD" in content
        assert "Prime Directive" in content
        assert "Plan of Action" in content
        assert "Working Memory" in content
        assert "Await instructions" in content

    def test_clear_creates_parent_directories(self, tmp_path):
        thread_file = tmp_path / "deep" / "nested" / "THREAD.md"
        mgr = ThreadManager(thread_file)
        mgr.clear()
        assert thread_file.exists()

    def test_clear_overwrites_existing_content(self, tmp_path):
        thread_file = tmp_path / "THREAD.md"
        thread_file.write_text("old content", encoding="utf-8")
        mgr = ThreadManager(thread_file)
        mgr.clear()
        content = thread_file.read_text(encoding="utf-8")
        assert "old content" not in content
        assert "🔮 THE THREAD" in content


# ===========================================================================
# Tests: ThreadManager — load()
# ===========================================================================


class TestThreadManagerLoad:

    def _write_and_load(self, tmp_path, content):
        thread_file = tmp_path / "THREAD.md"
        thread_file.write_text(content, encoding="utf-8")
        mgr = ThreadManager(thread_file)
        return mgr.load()

    def test_load_missing_file_returns_empty_model(self, tmp_path):
        mgr = ThreadManager(tmp_path / "nonexistent.md")
        model = mgr.load()
        assert model.prime_directive == ""
        assert model.plan_steps == []
        assert model.working_memory == ""
        assert model.state == ThreadState.NEW

    def test_load_empty_file(self, tmp_path):
        model = self._write_and_load(tmp_path, "")
        assert model.prime_directive == ""
        assert model.plan_steps == []

    def test_load_default_template(self, tmp_path):
        model = self._write_and_load(tmp_path, ThreadManager.DEFAULT_TEMPLATE)
        assert model.prime_directive == "(Waiting for command...)"
        assert len(model.plan_steps) == 1
        assert model.plan_steps[0]["step"] == "Await instructions"
        assert model.plan_steps[0]["completed"] is False
        assert model.working_memory == "- System initialized."
        assert model.state == ThreadState.NEW

    def test_load_with_completed_steps_state_complete(self, tmp_path):
        content = """\
# 🔮 THE THREAD (Current State)

## 🎯 Prime Directive (The "Why")
Build the widget

## 📋 Plan of Action (The "How")
- [x] Design schema
- [x] Implement logic

## 🧠 Working Memory (Scratchpad)
All done!
"""
        model = self._write_and_load(tmp_path, content)
        assert model.state == ThreadState.COMPLETE
        assert all(s["completed"] for s in model.plan_steps)

    def test_load_with_mixed_steps_state_in_progress(self, tmp_path):
        content = """\
# 🔮 THE THREAD (Current State)

## 🎯 Prime Directive (The "Why")
Build the widget

## 📋 Plan of Action (The "How")
- [x] Design schema
- [ ] Implement logic
- [ ] Test

## 🧠 Working Memory (Scratchpad)
Working on it...
"""
        model = self._write_and_load(tmp_path, content)
        assert model.state == ThreadState.IN_PROGRESS
        assert model.plan_steps[0]["completed"] is True
        assert model.plan_steps[1]["completed"] is False

    def test_load_all_unchecked_state_new(self, tmp_path):
        content = """\
# 🔮 THE THREAD (Current State)

## 🎯 Prime Directive (The "Why")
Build something

## 📋 Plan of Action (The "How")
- [ ] Step A
- [ ] Step B

## 🧠 Working Memory (Scratchpad)
Nothing yet.
"""
        model = self._write_and_load(tmp_path, content)
        assert model.state == ThreadState.NEW

    def test_load_no_steps_state_new(self, tmp_path):
        content = """\
# 🔮 THE THREAD (Current State)

## 🎯 Prime Directive (The "Why")
Just an idea

## 📋 Plan of Action (The "How")
(no plan yet)

## 🧠 Working Memory (Scratchpad)
Thinking...
"""
        model = self._write_and_load(tmp_path, content)
        assert model.state == ThreadState.NEW
        assert model.plan_steps == []

    def test_load_upper_case_x_checked(self, tmp_path):
        """Upper-case 'X' in checkbox should count as completed."""
        content = """\
# 🔮 THE THREAD (Current State)

## 🎯 Prime Directive (The "Why")
Test

## 📋 Plan of Action (The "How")
- [X] Step done

## 🧠 Working Memory (Scratchpad)
n/a
"""
        model = self._write_and_load(tmp_path, content)
        assert model.plan_steps[0]["completed"] is True

    def test_load_missing_working_memory_section(self, tmp_path):
        content = """\
# 🔮 THE THREAD (Current State)

## 🎯 Prime Directive (The "Why")
Directive here

## 📋 Plan of Action (The "How")
- [ ] Todo
"""
        model = self._write_and_load(tmp_path, content)
        assert model.prime_directive == "Directive here"
        assert len(model.plan_steps) == 1
        assert model.working_memory == ""

    def test_load_missing_plan_section(self, tmp_path):
        content = """\
# 🔮 THE THREAD (Current State)

## 🎯 Prime Directive (The "Why")
Goal

## 🧠 Working Memory (Scratchpad)
Notes
"""
        model = self._write_and_load(tmp_path, content)
        assert model.prime_directive == "Goal"
        assert model.plan_steps == []
        assert model.working_memory == "Notes"

    def test_load_missing_prime_directive_section(self, tmp_path):
        content = """\
# 🔮 THE THREAD (Current State)

## 📋 Plan of Action (The "How")
- [ ] Only plan

## 🧠 Working Memory (Scratchpad)
Notes
"""
        model = self._write_and_load(tmp_path, content)
        assert model.prime_directive == ""
        assert len(model.plan_steps) == 1

    def test_load_multiline_prime_directive(self, tmp_path):
        content = """\
# 🔮 THE THREAD (Current State)

## 🎯 Prime Directive (The "Why")
Line one
Line two
Line three

## 📋 Plan of Action (The "How")
- [ ] Todo

## 🧠 Working Memory (Scratchpad)
Stuff
"""
        model = self._write_and_load(tmp_path, content)
        assert "Line one" in model.prime_directive
        assert "Line two" in model.prime_directive
        assert "Line three" in model.prime_directive

    def test_load_multiline_working_memory(self, tmp_path):
        content = """\
# 🔮 THE THREAD (Current State)

## 🎯 Prime Directive (The "Why")
Goal

## 📋 Plan of Action (The "How")
- [ ] Something

## 🧠 Working Memory (Scratchpad)
- Note 1
- Note 2
- Note 3
"""
        model = self._write_and_load(tmp_path, content)
        assert "Note 1" in model.working_memory
        assert "Note 2" in model.working_memory
        assert "Note 3" in model.working_memory

    def test_load_step_text_with_special_characters(self, tmp_path):
        content = """\
# 🔮 THE THREAD (Current State)

## 🎯 Prime Directive (The "Why")
Goal

## 📋 Plan of Action (The "How")
- [ ] Fix bug — issue #42 (critical!)
- [x] Update `config.py` & deploy

## 🧠 Working Memory (Scratchpad)
n/a
"""
        model = self._write_and_load(tmp_path, content)
        assert len(model.plan_steps) == 2
        assert "Fix bug — issue #42 (critical!)" == model.plan_steps[0]["step"]
        assert "Update `config.py` & deploy" == model.plan_steps[1]["step"]

    def test_load_unicode_content(self, tmp_path):
        content = """\
# 🔮 THE THREAD (Current State)

## 🎯 Prime Directive (The "Why")
Résumé des tâches — 日本語テスト

## 📋 Plan of Action (The "How")
- [ ] Créer le fichier
- [x] Tester les émojis 🎉

## 🧠 Working Memory (Scratchpad)
Notes: café ☕
"""
        model = self._write_and_load(tmp_path, content)
        assert "Résumé" in model.prime_directive
        assert "日本語テスト" in model.prime_directive
        assert model.plan_steps[1]["step"] == "Tester les émojis 🎉"
        assert "café ☕" in model.working_memory


# ===========================================================================
# Tests: ThreadManager — update_plan()
# ===========================================================================


class TestThreadManagerUpdatePlan:

    def test_update_plan_writes_file(self, tmp_path):
        thread_file = tmp_path / "THREAD.md"
        mgr = ThreadManager(thread_file)
        model = ThreadModel(
            prime_directive="Build feature X",
            plan_steps=[
                {"step": "Research", "completed": True},
                {"step": "Implement", "completed": False},
            ],
            working_memory="Almost there",
        )
        mgr.update_plan(model)

        content = thread_file.read_text(encoding="utf-8")
        assert "Build feature X" in content
        assert "- [x] Research" in content
        assert "- [ ] Implement" in content
        assert "Almost there" in content

    def test_update_plan_creates_parent_dirs(self, tmp_path):
        thread_file = tmp_path / "deep" / "dir" / "THREAD.md"
        mgr = ThreadManager(thread_file)
        model = ThreadModel(prime_directive="Test")
        mgr.update_plan(model)
        assert thread_file.exists()

    def test_update_plan_no_steps_placeholder(self, tmp_path):
        thread_file = tmp_path / "THREAD.md"
        mgr = ThreadManager(thread_file)
        model = ThreadModel(prime_directive="Goal", plan_steps=[])
        mgr.update_plan(model)

        content = thread_file.read_text(encoding="utf-8")
        assert "(No steps defined)" in content

    def test_update_plan_empty_directive_placeholder(self, tmp_path):
        thread_file = tmp_path / "THREAD.md"
        mgr = ThreadManager(thread_file)
        model = ThreadModel(prime_directive="")
        mgr.update_plan(model)

        content = thread_file.read_text(encoding="utf-8")
        assert "(No directive set)" in content

    def test_update_plan_empty_working_memory_placeholder(self, tmp_path):
        thread_file = tmp_path / "THREAD.md"
        mgr = ThreadManager(thread_file)
        model = ThreadModel(prime_directive="X", working_memory="")
        mgr.update_plan(model)

        content = thread_file.read_text(encoding="utf-8")
        assert "(Empty)" in content

    def test_update_plan_overwrites_existing(self, tmp_path):
        thread_file = tmp_path / "THREAD.md"
        thread_file.write_text("old junk", encoding="utf-8")
        mgr = ThreadManager(thread_file)
        model = ThreadModel(prime_directive="New goal")
        mgr.update_plan(model)

        content = thread_file.read_text(encoding="utf-8")
        assert "old junk" not in content
        assert "New goal" in content


# ===========================================================================
# Tests: ThreadManager._parse_markdown (isolated)
# ===========================================================================


class TestParseMarkdown:
    """Direct tests on _parse_markdown to cover edge-case parsing logic."""

    def _make_manager(self, tmp_path):
        return ThreadManager(tmp_path / "THREAD.md")

    def test_empty_string(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        model = mgr._parse_markdown("")
        assert model.prime_directive == ""
        assert model.plan_steps == []
        assert model.working_memory == ""
        assert model.state == ThreadState.NEW

    def test_whitespace_only(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        model = mgr._parse_markdown("   \n  \n  \t  ")
        assert model.prime_directive == ""
        assert model.plan_steps == []

    def test_content_without_headers(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        model = mgr._parse_markdown("Just some random text\nwithout headers")
        assert model.prime_directive == ""
        assert model.plan_steps == []
        assert model.working_memory == ""

    def test_plan_with_extra_whitespace(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        content = """\
## 🎯 Prime Directive (The "Why")
Goal

## 📋 Plan of Action (The "How")
  - [ ]   Indented step with spaces  
- [x] Normal step

## 🧠 Working Memory (Scratchpad)
Note
"""
        model = mgr._parse_markdown(content)
        assert len(model.plan_steps) == 2
        assert model.plan_steps[0]["step"] == "Indented step with spaces"
        assert model.plan_steps[0]["completed"] is False
        assert model.plan_steps[1]["step"] == "Normal step"
        assert model.plan_steps[1]["completed"] is True

    def test_non_checkbox_lines_in_plan_ignored(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        content = """\
## 📋 Plan of Action (The "How")
Some narrative text explaining the plan.
- [ ] Real step
Another narrative line.
- [x] Completed step
"""
        model = mgr._parse_markdown(content)
        assert len(model.plan_steps) == 2

    def test_single_step_completed(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        content = """\
## 📋 Plan of Action (The "How")
- [x] Only step
"""
        model = mgr._parse_markdown(content)
        assert model.state == ThreadState.COMPLETE

    def test_single_step_unchecked(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        content = """\
## 📋 Plan of Action (The "How")
- [ ] Only step
"""
        model = mgr._parse_markdown(content)
        assert model.state == ThreadState.NEW

    def test_many_steps_derive_in_progress(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        content = """\
## 📋 Plan of Action (The "How")
- [x] Done 1
- [x] Done 2
- [ ] Todo 1
- [ ] Todo 2
"""
        model = mgr._parse_markdown(content)
        assert model.state == ThreadState.IN_PROGRESS

    def test_sections_in_different_order(self, tmp_path):
        """Parser should work regardless of section ordering."""
        mgr = self._make_manager(tmp_path)
        content = """\
## 🧠 Working Memory (Scratchpad)
Memory first

## 📋 Plan of Action (The "How")
- [ ] Step

## 🎯 Prime Directive (The "Why")
Directive last
"""
        model = mgr._parse_markdown(content)
        assert model.prime_directive == "Directive last"
        assert model.working_memory == "Memory first"
        assert len(model.plan_steps) == 1


# ===========================================================================
# Tests: ThreadManager._serialize_model (isolated)
# ===========================================================================


class TestSerializeModel:
    """Direct tests on _serialize_model to verify markdown output structure."""

    def _make_manager(self, tmp_path):
        return ThreadManager(tmp_path / "THREAD.md")

    def test_header_present(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        model = ThreadModel(prime_directive="Test")
        result = mgr._serialize_model(model)
        assert result.startswith("# 🔮 THE THREAD (Current State)")

    def test_sections_present(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        model = ThreadModel(
            prime_directive="Goal",
            plan_steps=[{"step": "Step 1", "completed": False}],
            working_memory="Notes here",
        )
        result = mgr._serialize_model(model)
        assert '## 🎯 Prime Directive (The "Why")' in result
        assert '## 📋 Plan of Action (The "How")' in result
        assert "## 🧠 Working Memory (Scratchpad)" in result

    def test_completed_step_marker(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        model = ThreadModel(
            prime_directive="X",
            plan_steps=[{"step": "Done", "completed": True}],
        )
        result = mgr._serialize_model(model)
        assert "- [x] Done" in result

    def test_uncompleted_step_marker(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        model = ThreadModel(
            prime_directive="X",
            plan_steps=[{"step": "Todo", "completed": False}],
        )
        result = mgr._serialize_model(model)
        assert "- [ ] Todo" in result

    def test_empty_steps_placeholder(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        model = ThreadModel(prime_directive="X", plan_steps=[])
        result = mgr._serialize_model(model)
        assert "(No steps defined)" in result

    def test_empty_directive_placeholder(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        model = ThreadModel(prime_directive="")
        result = mgr._serialize_model(model)
        assert "(No directive set)" in result

    def test_empty_working_memory_placeholder(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        model = ThreadModel(prime_directive="X", working_memory="")
        result = mgr._serialize_model(model)
        assert "(Empty)" in result

    def test_multiple_steps_order_preserved(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        steps = [
            {"step": "Alpha", "completed": False},
            {"step": "Beta", "completed": True},
            {"step": "Gamma", "completed": False},
        ]
        model = ThreadModel(prime_directive="X", plan_steps=steps)
        result = mgr._serialize_model(model)

        alpha_pos = result.index("Alpha")
        beta_pos = result.index("Beta")
        gamma_pos = result.index("Gamma")
        assert alpha_pos < beta_pos < gamma_pos

    def test_ends_with_newline(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        model = ThreadModel(prime_directive="Goal", working_memory="Stuff")
        result = mgr._serialize_model(model)
        assert result.endswith("\n")


# ===========================================================================
# Tests: ThreadManager — Round-Trip (clear ➜ load ➜ update ➜ load)
# ===========================================================================


class TestThreadManagerRoundTrip:

    def test_clear_then_load_returns_defaults(self, tmp_path):
        thread_file = tmp_path / "THREAD.md"
        mgr = ThreadManager(thread_file)
        mgr.clear()
        model = mgr.load()

        assert model.prime_directive == "(Waiting for command...)"
        assert model.plan_steps[0]["step"] == "Await instructions"
        assert model.plan_steps[0]["completed"] is False
        assert model.working_memory == "- System initialized."
        assert model.state == ThreadState.NEW

    def test_update_then_load_consistency(self, tmp_path):
        """Write a model to disk, re-load it, and verify all fields match."""
        thread_file = tmp_path / "THREAD.md"
        mgr = ThreadManager(thread_file)

        original = ThreadModel(
            prime_directive="Refactor the database layer",
            plan_steps=[
                {"step": "Audit existing queries", "completed": True},
                {"step": "Create migration scripts", "completed": False},
                {"step": "Run integration tests", "completed": False},
            ],
            working_memory="Found 12 slow queries in the ORM layer.",
        )
        mgr.update_plan(original)
        reloaded = mgr.load()

        assert reloaded.prime_directive == original.prime_directive
        assert len(reloaded.plan_steps) == len(original.plan_steps)
        for orig, loaded in zip(original.plan_steps, reloaded.plan_steps):
            assert loaded["step"] == orig["step"]
            assert loaded["completed"] == orig["completed"]
        assert reloaded.working_memory == original.working_memory
        assert reloaded.state == ThreadState.IN_PROGRESS

    def test_update_complete_plan_then_load(self, tmp_path):
        thread_file = tmp_path / "THREAD.md"
        mgr = ThreadManager(thread_file)

        model = ThreadModel(
            prime_directive="Ship it",
            plan_steps=[
                {"step": "Build", "completed": True},
                {"step": "Test", "completed": True},
                {"step": "Deploy", "completed": True},
            ],
            working_memory="All green ✅",
        )
        mgr.update_plan(model)
        reloaded = mgr.load()
        assert reloaded.state == ThreadState.COMPLETE

    def test_overwrite_roundtrip(self, tmp_path):
        """Updating twice should keep only the latest version."""
        thread_file = tmp_path / "THREAD.md"
        mgr = ThreadManager(thread_file)

        v1 = ThreadModel(prime_directive="Version 1", plan_steps=[{"step": "V1 step", "completed": False}])
        mgr.update_plan(v1)

        v2 = ThreadModel(prime_directive="Version 2", plan_steps=[{"step": "V2 step", "completed": True}])
        mgr.update_plan(v2)

        reloaded = mgr.load()
        assert reloaded.prime_directive == "Version 2"
        assert reloaded.plan_steps[0]["step"] == "V2 step"

    def test_clear_after_update_resets(self, tmp_path):
        thread_file = tmp_path / "THREAD.md"
        mgr = ThreadManager(thread_file)

        model = ThreadModel(prime_directive="Busy work", plan_steps=[{"step": "Do stuff", "completed": True}])
        mgr.update_plan(model)
        mgr.clear()

        reloaded = mgr.load()
        assert reloaded.prime_directive == "(Waiting for command...)"
        assert reloaded.state == ThreadState.NEW


# ===========================================================================
# Tests: ThreadManager — File I/O Edge Cases
# ===========================================================================


class TestThreadManagerFileIO:

    def test_read_from_file_nonexistent(self, tmp_path):
        mgr = ThreadManager(tmp_path / "no_such_file.md")
        result = mgr._read_from_file()
        assert result == ""

    def test_write_then_read(self, tmp_path):
        thread_file = tmp_path / "THREAD.md"
        mgr = ThreadManager(thread_file)
        mgr._write_to_file("hello world")
        assert mgr._read_from_file() == "hello world"

    def test_write_creates_parent_dirs(self, tmp_path):
        thread_file = tmp_path / "a" / "b" / "c" / "THREAD.md"
        mgr = ThreadManager(thread_file)
        mgr._write_to_file("test")
        assert thread_file.read_text(encoding="utf-8") == "test"

    def test_write_overwrites_existing(self, tmp_path):
        thread_file = tmp_path / "THREAD.md"
        thread_file.write_text("original", encoding="utf-8")
        mgr = ThreadManager(thread_file)
        mgr._write_to_file("replaced")
        assert thread_file.read_text(encoding="utf-8") == "replaced"

    def test_utf8_encoding_roundtrip(self, tmp_path):
        thread_file = tmp_path / "THREAD.md"
        mgr = ThreadManager(thread_file)
        text = "🔮 Ünïcödé — 日本語\n"
        mgr._write_to_file(text)
        assert mgr._read_from_file() == text


# ===========================================================================
# Tests: ThreadManager — Thread Safety
# ===========================================================================


class TestThreadManagerThreadSafety:

    def test_concurrent_notify_and_check(self, tmp_path):
        """Stress test: many threads setting stale while main checks."""
        mgr = ThreadManager(tmp_path / "THREAD.md")
        errors_caught = []

        def notifier():
            for _ in range(50):
                mgr.notify_user_edit()
                time.sleep(0.001)

        def checker():
            for _ in range(100):
                try:
                    mgr.check_for_interrupt()
                except ContextStaleError:
                    errors_caught.append(True)
                time.sleep(0.001)

        threads = [threading.Thread(target=notifier) for _ in range(3)]
        threads.append(threading.Thread(target=checker))

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        # At least one error should have been caught
        assert len(errors_caught) >= 1
