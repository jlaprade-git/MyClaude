"""myclaude - cross-project Claude Code session picker.

Scans ~/.claude/projects/ for all session transcripts, shows a menu sorted
by most recent activity, and resumes the chosen one in its original working
directory (which Claude Code requires for --resume to work).

Usage:
    myclaude                  # show 20 most recent sessions
    myclaude navigator        # search sessions by folder name or message
    myclaude -n 50            # show 50 most recent
    myclaude -a               # show every session

At the interactive prompt you can also type a search term instead of a
number to filter the full session list on the fly.
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECTS_DIR = Path.home() / ".claude" / "projects"
PREVIEW_CHARS = 70
SCAN_LINES = 50  # how many lines to scan for metadata before giving up


def extract_metadata(session_path):
    """Return (cwd, first_user_message, session_name) from a session JSONL.

    cwd and first_message are extracted from the first SCAN_LINES lines.
    session_name comes from the last 'agent-name' entry in the file (since
    renames append a new entry), so we scan the entire file for those.
    """
    cwd = None
    first_message = None
    session_name = None
    try:
        with session_path.open("r", encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # cwd and first message: only from the top of the file
                if i < SCAN_LINES:
                    if cwd is None and isinstance(entry.get("cwd"), str):
                        cwd = entry["cwd"]
                    if (
                        first_message is None
                        and entry.get("type") == "user"
                        and entry.get("userType") == "external"
                    ):
                        content = (entry.get("message") or {}).get("content")
                        if isinstance(content, str):
                            first_message = content
                        elif isinstance(content, list):
                            for block in content:
                                if isinstance(block, dict) and block.get("type") == "text":
                                    first_message = block.get("text", "")
                                    break
                # session name: take the last one found (renames overwrite)
                if entry.get("type") == "agent-name" and entry.get("agentName"):
                    session_name = entry["agentName"]
    except OSError:
        pass
    return cwd, first_message, session_name


def format_relative(mtime):
    delta = datetime.now(timezone.utc).timestamp() - mtime
    if delta < 60:
        return f"{int(delta)}s ago"
    if delta < 3600:
        return f"{int(delta / 60)}m ago"
    if delta < 86400:
        return f"{int(delta / 3600)}h ago"
    if delta < 86400 * 30:
        return f"{int(delta / 86400)}d ago"
    return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")


def truncate(s, n):
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[: n - 1] + "..."


def load_session_indexes():
    """Load all sessions-index.json files into a dict keyed by session ID."""
    index = {}
    for idx_path in PROJECTS_DIR.rglob("sessions-index.json"):
        try:
            with idx_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            for entry in data.get("entries", []):
                sid = entry.get("sessionId")
                if sid:
                    index[sid] = entry
        except (OSError, json.JSONDecodeError):
            continue
    return index


def collect_sessions():
    """Collect only real sessions (no subagents)."""
    if not PROJECTS_DIR.is_dir():
        return []
    session_index = load_session_indexes()
    sessions = []
    for jsonl in PROJECTS_DIR.rglob("*.jsonl"):
        # Skip subagent sessions entirely — they live under <parent-id>/subagents/
        if jsonl.parent.name == "subagents":
            continue
        try:
            mtime = jsonl.stat().st_mtime
        except OSError:
            continue
        sid = jsonl.stem
        cwd, preview, name = extract_metadata(jsonl)
        # Enrich from sessions-index.json if available
        idx_entry = session_index.get(sid)
        if idx_entry:
            if not name:
                name = idx_entry.get("name")
            if not preview and idx_entry.get("summary"):
                preview = idx_entry["summary"]
        sessions.append((mtime, sid, cwd, preview, name))
    sessions.sort(key=lambda x: x[0], reverse=True)
    return sessions


def search_sessions(sessions, query):
    """Filter sessions whose cwd, preview, or name contains every word in query (case-insensitive)."""
    words = query.lower().split()
    results = []
    for s in sessions:
        mtime, sid, cwd, preview, name = s
        haystack = f"{cwd or ''} {preview or ''} {name or ''}".lower()
        if all(w in haystack for w in words):
            results.append(s)
    return results


def display_sessions(sessions):
    """Print the numbered session list. Returns the list shown."""
    if not sessions:
        print("  No matching sessions.")
        return sessions
    idx_w = len(str(len(sessions)))
    for i, (mtime, sid, cwd, preview, name) in enumerate(sessions, 1):
        when = format_relative(mtime)
        label = name or cwd or "(unknown cwd)"
        if name and cwd:
            label = f"{name}  ({cwd})"
        print(f"  {i:>{idx_w}}. {when:>8}  {label}")
        if preview:
            print(f"     {' ' * idx_w}  {truncate(preview, PREVIEW_CHARS)}")
        print()
    return sessions


def resume_session(session):
    """Resume a session by its tuple. Returns exit code."""
    _, resume_id, cwd, _, _ = session
    if not cwd or not Path(cwd).is_dir():
        print(
            f"Can't resume: original working directory is missing or unknown ({cwd!r}).",
            file=sys.stderr,
        )
        return 1
    print(f"\nResuming {resume_id} in {cwd}\n")
    try:
        return subprocess.run(["claude", "--resume", resume_id], cwd=cwd).returncode
    except FileNotFoundError:
        print("Couldn't find 'claude' on PATH.", file=sys.stderr)
        return 1


def prompt_loop(all_sessions, visible):
    """Interactive prompt loop. Returns exit code."""
    while True:
        try:
            choice = input(
                "Pick a number, search term to filter, N for new, blank to cancel: "
            ).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 130

        if not choice:
            return 0

        if choice.lower() in ("n", "new"):
            home = str(Path.home())
            try:
                target = input(f"  Directory for new session [{home}]: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 130
            target = target or home
            target = str(Path(target).expanduser().resolve())
            if not Path(target).is_dir():
                print(f"  Not a valid directory: {target}", file=sys.stderr)
                continue
            print(f"\nStarting new session in {target}\n")
            try:
                return subprocess.run(["claude"], cwd=target).returncode
            except FileNotFoundError:
                print("Couldn't find 'claude' on PATH.", file=sys.stderr)
                return 1

        # Try as a number first (selection from current list)
        try:
            idx = int(choice)
            if 1 <= idx <= len(visible):
                return resume_session(visible[idx - 1])
            else:
                print(f"  Out of range (1-{len(visible)}).\n")
                continue
        except ValueError:
            pass

        # Otherwise treat it as a search query against all sessions
        results = search_sessions(all_sessions, choice)
        print(f"\n  Search results for \"{choice}\" ({len(results)} match(es)):\n")
        visible = display_sessions(results)
        if not visible:
            print()


def main():
    parser = argparse.ArgumentParser(
        description="Pick and resume a Claude Code session from any project.",
    )
    parser.add_argument(
        "search", nargs="*",
        help="search terms to filter sessions by folder or message",
    )
    parser.add_argument(
        "-n", "--count", type=int, default=20,
        help="number of recent sessions to show (default: 20)",
    )
    parser.add_argument(
        "-a", "--all", action="store_true",
        help="show every session (overrides --count)",
    )
    args = parser.parse_args()

    all_sessions = collect_sessions()
    if not all_sessions:
        print(f"No sessions found in {PROJECTS_DIR}")
        return 1

    # If a search query was given on the command line, filter first
    if args.search:
        query = " ".join(args.search)
        visible = search_sessions(all_sessions, query)
        print(f"\n  Sessions matching \"{query}\" ({len(visible)} match(es)):\n")
    else:
        visible = all_sessions if args.all else all_sessions[: args.count]
        total = len(all_sessions)
        shown = len(visible)
        print(f"\n  {shown} of {total} session(s). Most recent first:\n")

    visible = display_sessions(visible)
    if not visible and not args.search:
        return 1

    return prompt_loop(all_sessions, visible)


if __name__ == "__main__":
    sys.exit(main())
