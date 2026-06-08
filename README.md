# MyClaude - Claude CLI Session Manager

A cross-project session picker for [Claude Code](https://docs.anthropic.com/en/docs/claude-code). Scans your local session transcripts, shows a searchable menu sorted by most recent activity, and resumes the chosen session in its original working directory.

## Why

Claude Code stores session transcripts across project directories under `~/.claude/projects/`. Over time you accumulate hundreds of session files — most of them subagent transcripts you never need to see. Finding and resuming a specific session means digging through folders manually.

MyClaude fixes this by:
- **Hiding subagent noise** — only shows your real sessions (subagent transcripts are filtered out automatically)
- **Search** — filter sessions by folder name or message content from the CLI or interactively
- **One command to resume** — picks the right working directory so `--resume` just works

## Usage

```
myclaude                  # show 20 most recent sessions
myclaude navigator        # search sessions by folder name or message
myclaude pdf archiving    # multi-word search (AND match)
myclaude -n 50            # show 50 most recent
myclaude -a               # show every session
```

At the interactive prompt you can:
- Type a **number** to resume that session
- Type a **search term** to filter the full session list on the fly
- Type **N** to start a new session (prompts for a working directory)
- Press **Enter** to cancel

## Example

```
$ myclaude

  8 of 42 session(s). Most recent first:

   1.    5m ago  C:\Source\MyProject
                 fix the login redirect bug on the settings page...

   2.    3h ago  C:\Source\APIServer
                 add rate limiting to the /upload endpoint...

   3.    1d ago  C:\Source\MyProject
                 refactor the database migration scripts to use...

Pick a number, search term to filter, N for new, blank to cancel: myproject

  Search results for "myproject" (2 match(es)):

  1.    5m ago  C:\Source\MyProject
                fix the login redirect bug on the settings page...

  2.    1d ago  C:\Source\MyProject
                refactor the database migration scripts to use...

Pick a number, search term to filter, N for new, blank to cancel: 1

Resuming abc123-def456 in C:\Source\MyProject
```

## Setup

### Requirements

- Python 3.8+
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) installed and on your PATH

### Install

1. Copy `myclaude.py` somewhere on your PATH (e.g. `~/.claude/bin/`).

2. Create a wrapper so you can run it as `myclaude`:

   **Windows** — create `myclaude.cmd`:
   ```cmd
   @python "%~dp0myclaude.py" %*
   ```

   **Linux / macOS** — create `myclaude` (make it executable with `chmod +x`):
   ```bash
   #!/usr/bin/env bash
   python3 "$(dirname "$0")/myclaude.py" "$@"
   ```

3. Make sure the directory containing the wrapper is in your PATH.

## How It Works

- Scans `~/.claude/projects/` recursively for `.jsonl` session transcript files
- Skips subagent sessions (files under `*/subagents/` directories)
- Extracts the working directory and first user message from each session's metadata
- Sorts by last modified time
- Resumes sessions with `claude --resume <session-id>` in the original working directory

## License

MIT
