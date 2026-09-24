# Contributing to Kyberos

Thank you for your interest in contributing to **Kyberos**.

Kyberos is a local-first runtime for persistent, recursive AI agents. This document describes the development workflow, architectural principles, testing requirements, and contribution standards for the project.

---

## Architecture Principles

Kyberos is designed around a few core principles.

### 1. Recursion Without Context Bloat

Complex work should be decomposed into focused tasks.

When appropriate, agents can delegate work to isolated sub-agents rather than continuously expanding the primary context window.

Favor:

- modular components
- explicit interfaces
- composable systems
- isolated recursive work
- efficient context usage

Avoid large monolithic agent loops that accumulate unrelated state.

### 2. State Has Explicit Boundaries

Kyberos separates different kinds of persistent state intentionally:

- **Thread** — active working state and current task progress
- **Archive** — durable memory composed of Engrams
- **Timeline** — chronological history and significant events
- **Codex** — stable reference material and structured knowledge
- **Skills** — reusable executable capabilities
- **Heartbeat** — scheduled and recurring autonomous work

Do not collapse these concepts into a single generic memory system.

### 3. Memory Must Be Inspectable

Persistent agent memory should remain understandable and controllable by the user.

File-backed state is the canonical representation wherever practical. Vector databases and semantic indexes are retrieval mechanisms, not opaque replacements for durable source data.

### 4. Skills Are Capabilities

Reusable agent capabilities belong in the **Skills** subsystem.

Skills should follow the `SKILL.md` convention and may contain:

- instructions
- scripts
- structured parameters
- supporting resources

Core runtime behavior belongs in `src/kyberos/`, not in user-created Skills.

### 5. Protocols Are External Boundaries

Connections to systems such as Discord, Telegram, GitHub, HTTP APIs, and future agent-to-agent systems should be implemented through clearly defined **Protocols** or adapters.

The core runtime should not become tightly coupled to any individual external platform.

### 6. Verification Over Assumption

An attempted action is not necessarily a successful action.

Runtime behavior and tests should verify observable results rather than assuming operations succeeded.

---

## Development Environment

### Prerequisites

- **Python 3.12+**
- **Git**
- **uv** — recommended and used by CI

Supported development environments include:

- Windows 10+
- Linux
- WSL2
- macOS — expected to work, but currently less extensively tested

Contributions improving macOS compatibility are welcome.

---

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/triple-threat-dan/Kyberos.git
cd Kyberos
```

### 2. Install Dependencies

The recommended development workflow uses `uv`:

```bash
uv sync --all-extras --dev
```

This creates and manages the project's virtual environment automatically.

### 3. Verify the Installation

```bash
uv run kyberos --help
```

---

## Testing

Kyberos uses `pytest`.

Before submitting a Pull Request, run the complete test suite:

```bash
uv run pytest
```

Run the same coverage command used by CI:

```bash
uv run pytest --cov=kyberos tests/
```

### Test Expectations

New behavior should include appropriate tests.

Tests should:

- be deterministic
- avoid depending on external services unless explicitly marked as integration tests
- clean up temporary resources
- mock network and provider interactions where appropriate
- test observable behavior rather than implementation details
- work across supported operating systems whenever the functionality is cross-platform

### Cross-Platform Tests

GitHub Actions runs tests on Linux.

Do not assume that behavior observed on a Windows development machine will be identical in CI.

For platform-specific functionality, test the intended platform behavior explicitly.

For example:

```python
if os.name == "nt":
    assert "execute_powershell" in context
    assert "execute_bash" not in context
else:
    assert "execute_bash" in context
    assert "execute_powershell" not in context
```

Platform-specific tools should not cause unrelated tests to fail on another supported operating system.

---

## Project Structure

The v2 architecture is organized approximately as follows:

```text
Kyberos/
├── src/
│   └── kyberos/
│       ├── brain/          # Agent reasoning, RLM orchestration, LLM gateway
│       ├── core/           # Runtime, configuration, daemon, sessions
│       ├── memory/         # Archive, retrieval, indexing, memory lifecycle
│       ├── skills/         # Skill discovery and execution infrastructure
│       └── interface/      # Protocol adapters and external interfaces
│
├── tests/
│   ├── brain/
│   ├── core/
│   ├── memory/
│   ├── skills/
│   └── interface/
│
└── .kyberos/               # Local runtime state; not committed
```

A runtime installation may contain structures such as:

```text
.kyberos/
├── SOUL.md
├── USER.md
├── HEARTBEAT.md
├── thread/
│   └── THREAD.md
├── archive/
│   └── engrams/
├── timeline/
├── codex/
├── skills/
├── workspace/
├── logs/
└── kyberos.json
```

The exact storage layout may evolve during Kyberos v2 development, but the conceptual boundaries between these systems should remain clear.

---

## Runtime vs. Agent

Kyberos is the **runtime**, not the identity of the agent running on it.

Avoid coupling core runtime behavior to a specific agent name, personality, or character.

For example:

```text
Kyberos
   └── hosts and orchestrates
          └── an agent such as ALISS
```

Agent-specific identity belongs in runtime state such as `SOUL.md`, not in core Kyberos implementation.

---

## Skills

Skills are reusable agent capabilities stored under:

```text
.kyberos/skills/
```

A Skill should normally have the following structure:

```text
example-skill/
├── SKILL.md
└── scripts/
```

`SKILL.md` should clearly document:

- purpose
- when the Skill should be used
- accepted parameters
- execution behavior
- dependencies
- limitations
- relevant safety considerations

Do not place durable memories in the Skills system.

Do not place reusable Skills in the Archive.

---

## Memory Architecture

### Thread

The **Thread** represents active work.

It should contain only the context necessary to continue the current task.

### Archive

The **Archive** contains durable memory.

Individual durable memories are called **Engrams**.

### Timeline

The **Timeline** records meaningful events and historical activity.

### Codex

The **Codex** contains structured reference material, documentation, procedures, policies, and other relatively stable knowledge.

When contributing to memory functionality, preserve these distinctions instead of treating all persistent information as interchangeable.

---

## Submitting a Pull Request

### 1. Fork the Repository

Create a fork of Kyberos under your GitHub account.

### 2. Create a Branch

Use a descriptive branch name:

```bash
git checkout -b feat/your-feature-name
```

Suggested prefixes:

```text
feat/       New functionality
fix/        Bug fixes
refactor/   Internal restructuring
docs/       Documentation
test/       Test improvements
chore/      Maintenance
```

### 3. Make Your Changes

Keep changes focused on the purpose of the PR.

Avoid unrelated formatting or refactoring unless it is necessary for the change.

### 4. Add or Update Tests

New functionality should include tests when reasonably possible.

Bug fixes should preferably include a regression test demonstrating the original failure.

### 5. Run the Test Suite

```bash
uv run pytest --cov=kyberos tests/
```

### 6. Commit Your Changes

Use clear, descriptive commit messages.

For example:

```text
feat: add Archive Engram retrieval
fix: make tool context platform-aware
refactor: separate Protocol lifecycle from session routing
docs: document Thread lifecycle
```

### 7. Push Your Branch

```bash
git push origin feat/your-feature-name
```

### 8. Open a Pull Request

Describe:

- what changed
- why it changed
- how it was tested
- any architectural decisions involved
- any known limitations or follow-up work

Keep PRs reasonably focused so they can be reviewed and tested effectively.

---

## Code Style

### Python

Follow standard Python conventions and PEP 8.

Prefer clear, maintainable code over clever abstractions.

### Type Hints

Public interfaces should use type annotations.

Because Kyberos requires Python 3.12+, modern Python typing syntax is preferred:

```python
def find_engrams(query: str, limit: int = 10) -> list[str]:
    ...
```

Prefer this over older forms such as:

```python
List[str]
Optional[str]
```

unless compatibility or readability requires otherwise.

### Docstrings

Public classes, functions, and methods should include useful docstrings where their purpose or behavior is not immediately obvious.

### Async Code

Avoid blocking the event loop.

Use asynchronous APIs for network, subprocess, and I/O-heavy operations when they may occur in concurrent runtime paths.

### Logging

Use the Kyberos logging infrastructure rather than `print()` for runtime diagnostics.

Do not log:

- API keys
- authentication tokens
- passwords
- private credentials
- unnecessary sensitive user data

---

## Architectural Changes

Changes affecting core concepts such as:

- Thread
- Archive
- Engrams
- Timeline
- Skills
- Protocols
- Codex
- Dream Cycles
- session routing
- recursive execution
- tool security

should preserve clear subsystem boundaries.

For significant architectural changes, explain the reasoning in the Pull Request.

Avoid introducing compatibility shims or abstractions that make the architecture harder to understand unless they solve a concrete requirement.

---

## Security

Kyberos agents may execute tools and interact with external systems, so security-sensitive changes deserve additional care.

Contributions should:

- treat external content as untrusted by default
- avoid exposing credentials to model context unnecessarily
- validate tool arguments where appropriate
- maintain authorization boundaries between users
- require appropriate confirmation for destructive operations
- avoid silently expanding agent privileges

Security regressions should be treated as bugs even when the underlying feature otherwise works.

---

## AI-Assisted Development

AI-assisted and AI-generated code is welcome! Just remember however, the same standards apply regardless of how the code was produced.

Before submitting AI-generated code:

- read and understand it
- verify that it solves the intended problem
- run the relevant tests
- review it for security and architectural issues
- remove unnecessary complexity
- add tests and documentation where appropriate

The person submitting the Pull Request remains responsible for the code.

---

## Documentation

Update documentation when changing:

- public APIs
- CLI commands
- configuration
- runtime directories
- architectural concepts
- installation steps
- user-visible behavior

Terminology should remain consistent across:

- `README.md`
- `CONTRIBUTING.md`
- example `AGENT.md`
- CLI help
- source code
- configuration
- tests

---

## License

By contributing to Kyberos, you agree that your contributions will be distributed under the project's **MIT License**.

See [`LICENSE`](LICENSE) for details.

---

**Maintain the Thread. Preserve the Archive. Expand the Skills.**