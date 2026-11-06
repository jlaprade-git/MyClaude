# MyClaude - Claude CLI Cross Directory Session Manager

A cross-project/cross-directory session finder for [Claude Code](https://docs.anthropic.com/en/docs/claude-code). Builds a searchable index of every session you've ever run, shows a menu sorted by most recent activity, and resumes the chosen session in its original working directory.

## Why

Claude Code **deletes session transcripts after 30 days** (the `cleanupPeriodDays` setting), so any tool that scans `~/.claude/projects/` for transcripts only sees the last month of work. But `~/.claude/history.jsonl` permanently records every prompt you've ever typed, along with its folder, timestamp, and session ID.

MyClaude builds its session list from that permanent history, so it can find work from months or years ago:
- **Complete history** - every session ever, not just the ones whose transcripts survived cleanup
- **Full-text search** - matches against the folder path, session summary, and *every prompt you typed* in the session, not just the first one
- **Knows what's resumable** - sessions whose transcripts still exist resume directly; cleaned-up sessions are marked `[gone]`, and picking one shows its full prompt history and offers to start a fresh session in that folder
- **Hides subagent noise** - only your real sessions

## Usage

```
myclaude                  # show 20 most recent sessions
myclaude navigator        # search by folder, summary, or any prompt text
myclaude pdf archiving    # multi-word search (AND match)
myclaude -n 50            # show 50 most recent
myclaude -a               # show every session
```

At the interactive prompt you can:
- Type a **number** to resume that session (for `[gone]` sessions: view its prompts and optionally start a new session in that folder)
- Type **p \<number\>** to print a session's full prompt history with timestamps
- Type **search words** to filter the full session list on the fly
- Type **n** to start a new session (prompts for a working directory)
- Press **Enter** to quit

## Example

```
$ myclaude ntlm

  Sessions matching "ntlm" (3 match(es)):

  1.     5m ago          C:\Source\NavigatorDeployment
                   > well, we should at least check to see if NTLMv1 is getting used...

  2.     1d ago          C:\
                   > which session was i working on my NTLM audit in...

  3. 2026-09-02  [gone]  C:\Users\jlaprade
                   > #32324 NTLM Authentication Deprecation Audit and Migration...

  [gone] = transcript deleted by Claude Code cleanup; prompts still viewable.
```

## Setup

### Requirements

- Python 3.8+
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) installed and on your PATH

### Install

1. Copy `myclaude.py` somewhere on your PATH (e.g. `~/.claude/bin/`).

2. Create a wrapper so you can run it as `myclaude`:

   **Windows** - create `myclaude.cmd`:
   ```cmd
   @python "%~dp0myclaude.py" %*
   ```

   **Linux / macOS** - create `myclaude` (make it executable with `chmod +x`):
   ```bash
   #!/usr/bin/env bash
   python3 "$(dirname "$0")/myclaude.py" "$@"
   ```

3. Make sure the directory containing the wrapper is in your PATH.

## Tip: Stop Claude Code From Deleting Transcripts

Resuming only works while the transcript file still exists. To keep transcripts around much longer, add this to `~/.claude/settings.json`:

```json
{
  "cleanupPeriodDays": 3650
}
```

MyClaude still finds and shows cleaned-up sessions either way (prompt history lives in `history.jsonl` forever), but raising this setting keeps them *resumable*.

## Tip: Name Your Sessions

Claude Code lets you name sessions so they're easier to find later - both in MyClaude's search and in the built-in `claude --resume` picker:

- **At startup**: `claude -n auth-refactor`
- **During a session**: `/rename auth-refactor`
- **From the resume picker**: highlight a session and press `Ctrl+R`

A named session shows its name above the first-prompt preview, making it much easier to identify at a glance.

## How It Works

- Parses `~/.claude/history.jsonl` (the permanent prompt log) and groups entries by session ID - this is the complete record of every session
- Enriches entries with auto-generated summaries from `sessions-index.json` files, which also outlive the transcripts
- Scans `~/.claude/projects/` for surviving `.jsonl` transcripts to mark sessions as resumable and pick up session names (skipping `*/subagents/` files)
- Sorts by last activity
- Resumes with `claude --resume <session-id>` in the original working directory; for cleaned-up sessions, shows the prompt history and offers a fresh session in that folder

## License

MIT
