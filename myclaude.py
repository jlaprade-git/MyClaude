"""myclaude - cross-project Claude Code session finder and picker.

Claude Code deletes old transcripts from ~/.claude/projects/ after
`cleanupPeriodDays` (default 30), so scanning transcripts misses most
history. This tool instead builds its list from ~/.claude/history.jsonl,
which permanently records every prompt with its folder, timestamp, and
session ID. Transcripts and sessions-index.json files are used to enrich
entries (summaries) and to know which sessions are still resumable.

Usage:
    myclaude                  # show 20 most recent sessions
    myclaude navigator b2b    # search all prompts/folders/summaries
    myclaude -n 50            # show 50 most recent
    myclaude -a               # show every session

Interactive prompt:
    <number>   resume that session (or, if its transcript was cleaned up,
               show its prompt history and offer a new session there)
    p <number> print the full prompt history of that session
    <words>    search all sessions
    n          start a new session in a directory you choose
    <blank>    quit
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude"
PROJECTS_DIR = CLAUDE_DIR / "projects"
HISTORY_FILE = CLAUDE_DIR / "history.jsonl"
PREVIEW_CHARS = 90

# Prompts that carry no meaning for previews/search display
NOISE_PROMPTS = {"exit", "quit", "q", "-c", "continue"}


class Session:
    __slots__ = (
        "sid", "project", "prompts", "first_ts", "last_ts",
        "name", "summary", "transcript",
    )

    def __init__(self, sid):
        self.sid = sid
        self.project = None      # original working directory
        self.prompts = []        # list of (timestamp_ms, text)
        self.first_ts = None     # ms
        self.last_ts = None      # ms
        self.name = None         # session name (rename)
        self.summary = None      # auto summary from sessions-index
        self.transcript = None   # Path to .jsonl if still on disk

    @property
    def resumable(self):
        return self.transcript is not None

    def preview(self):
        for _, text in self.prompts:
            t = text.strip()
            if t and t.lower() not in NOISE_PROMPTS and not t.startswith("/"):
                return t
        return None

    def haystack(self):
        parts = [self.project or "", self.name or "", self.summary or ""]
        parts += [t for _, t in self.prompts]
        return " ".join(parts).lower()

    def matching_prompt(self, words):
        """First prompt containing any of the search words, for display."""
        for _, text in self.prompts:
            low = text.lower()
            if any(w in low for w in words):
                return text
        return None


def load_history():
    """Build sessions from history.jsonl (the permanent record)."""
    sessions = {}
    if not HISTORY_FILE.is_file():
        return sessions
    with HISTORY_FILE.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            sid = e.get("sessionId")
            if not sid:
                continue
            s = sessions.get(sid)
            if s is None:
                s = sessions[sid] = Session(sid)
            ts = e.get("timestamp") or 0
            text = e.get("display") or ""
            if text:
                s.prompts.append((ts, text))
            if e.get("project"):
                s.project = e["project"]
            if ts:
                if s.first_ts is None or ts < s.first_ts:
                    s.first_ts = ts
                if s.last_ts is None or ts > s.last_ts:
                    s.last_ts = ts
    return sessions


def enrich_from_indexes(sessions):
    """Add summaries/paths from sessions-index.json files (these outlive
    the transcripts they describe)."""
    if not PROJECTS_DIR.is_dir():
        return
    for idx_path in PROJECTS_DIR.glob("*/sessions-index.json"):
        try:
            with idx_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        for entry in data.get("entries", []):
            sid = entry.get("sessionId")
            if not sid:
                continue
            if entry.get("isSidechain"):
                continue
            s = sessions.get(sid)
            if s is None:
                s = sessions[sid] = Session(sid)
                fp = entry.get("firstPrompt")
                if fp:
                    s.prompts.append((entry.get("fileMtime") or 0, fp))
            if entry.get("summary") and not s.summary:
                s.summary = entry["summary"]
            if entry.get("projectPath") and not s.project:
                s.project = entry["projectPath"]
            mt = entry.get("fileMtime")
            if mt and (s.last_ts is None or mt > s.last_ts):
                s.last_ts = mt


def mark_transcripts(sessions):
    """Mark sessions whose transcript still exists (resumable), pull the
    session name (rename) from the transcript tail, and pick up any
    transcript not present in history."""
    if not PROJECTS_DIR.is_dir():
        return
    for jsonl in PROJECTS_DIR.rglob("*.jsonl"):
        if jsonl.parent.name == "subagents":
            continue
        sid = jsonl.stem
        s = sessions.get(sid)
        if s is None:
            s = sessions[sid] = Session(sid)
        s.transcript = jsonl
        try:
            mt = int(jsonl.stat().st_mtime * 1000)
            if s.last_ts is None or mt > s.last_ts:
                s.last_ts = mt
        except OSError:
            pass
        if s.project is None or s.name is None:
            cwd, name = scan_transcript(jsonl)
            s.project = s.project or cwd
            s.name = s.name or name


def scan_transcript(path, max_lines=4000):
    """Pull cwd and the latest agent-name (session rename) from a transcript."""
    cwd = None
    name = None
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i >= max_lines and cwd:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if cwd is None and isinstance(e.get("cwd"), str):
                    cwd = e["cwd"]
                if e.get("type") == "agent-name" and e.get("agentName"):
                    name = e["agentName"]
    except OSError:
        pass
    return cwd, name


def collect_sessions():
    sessions = load_history()
    enrich_from_indexes(sessions)
    mark_transcripts(sessions)
    out = [s for s in sessions.values() if s.project or s.prompts]
    out.sort(key=lambda s: s.last_ts or 0, reverse=True)
    return out


def format_relative(ts_ms):
    if not ts_ms:
        return "?"
    delta = datetime.now(timezone.utc).timestamp() - ts_ms / 1000
    if delta < 3600:
        return f"{max(1, int(delta / 60))}m ago"
    if delta < 86400:
        return f"{int(delta / 3600)}h ago"
    if delta < 86400 * 60:
        return f"{int(delta / 86400)}d ago"
    return datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d")


def truncate(s, n):
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[: n - 1] + "..."


def search_sessions(sessions, query):
    """Sessions whose folder, name, summary, or ANY prompt contains every
    word in the query (case-insensitive)."""
    words = query.lower().split()
    return [s for s in sessions if all(w in s.haystack() for w in words)]


def display_sessions(sessions, search_words=None):
    if not sessions:
        print("  No matching sessions.")
        return sessions
    idx_w = len(str(len(sessions)))
    for i, s in enumerate(sessions, 1):
        when = format_relative(s.last_ts)
        flag = "      " if s.resumable else "[gone]"
        label = s.project or "(unknown folder)"
        title = s.name or s.summary
        print(f"  {i:>{idx_w}}. {when:>10}  {flag}  {label}")
        if title:
            print(f"     {' ' * idx_w} {' ' * 10}  {truncate(title, PREVIEW_CHARS)}")
        shown = None
        if search_words:
            shown = s.matching_prompt(search_words)
        if shown is None:
            shown = s.preview()
        if shown:
            print(f"     {' ' * idx_w} {' ' * 10}  > {truncate(shown, PREVIEW_CHARS)}")
        print()
    print("  [gone] = transcript deleted by Claude Code cleanup; prompts still viewable.\n"
          if any(not s.resumable for s in sessions) else "", end="")
    return sessions


def print_prompts(s):
    print(f"\n  Session {s.sid}")
    print(f"  Folder: {s.project or '(unknown)'}")
    if s.name or s.summary:
        print(f"  Title:  {s.name or s.summary}")
    print(f"  {len(s.prompts)} prompt(s):\n")
    for ts, text in s.prompts:
        stamp = datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d %H:%M") if ts else "?"
        print(f"  [{stamp}]")
        for ln in text.splitlines():
            print(f"    {ln}")
        print()


def launch_claude(args_list, cwd):
    cmd = ["claude"] + args_list
    try:
        return subprocess.run(cmd, cwd=cwd).returncode
    except FileNotFoundError:
        # On Windows, 'claude' may be a .cmd shim only resolvable via the shell
        try:
            return subprocess.run(cmd, cwd=cwd, shell=True).returncode
        except FileNotFoundError:
            print("Couldn't find 'claude' on PATH.", file=sys.stderr)
            return 1


def resume_session(s):
    cwd = s.project
    if not cwd or not Path(cwd).is_dir():
        print(f"\n  Original folder is missing: {cwd!r}")
        cwd = None

    if s.resumable and cwd:
        print(f"\nResuming {s.sid} in {cwd}\n")
        return launch_claude(["--resume", s.sid], cwd)

    # Transcript is gone (or folder missing): show history, offer new session
    if not s.resumable:
        print("\n  This session's transcript was deleted by Claude Code's cleanup,")
        print("  so it can't be resumed. Here is what you worked on:")
        print_prompts(s)
    if cwd:
        try:
            ans = input(f"  Start a NEW session in {cwd}? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 130
        if ans in ("y", "yes"):
            print(f"\nStarting new session in {cwd}\n")
            return launch_claude([], cwd)
    return 0


def prompt_loop(all_sessions, visible):
    while True:
        try:
            choice = input(
                "Number to resume, 'p <num>' to view prompts, words to search, "
                "'n' for new, blank to quit: "
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
            target = str(Path(target or home).expanduser().resolve())
            if not Path(target).is_dir():
                print(f"  Not a valid directory: {target}", file=sys.stderr)
                continue
            print(f"\nStarting new session in {target}\n")
            return launch_claude([], target)

        # p <num>: print a session's full prompt history
        parts = choice.split()
        if len(parts) == 2 and parts[0].lower() == "p" and parts[1].isdigit():
            idx = int(parts[1])
            if 1 <= idx <= len(visible):
                print_prompts(visible[idx - 1])
            else:
                print(f"  Out of range (1-{len(visible)}).\n")
            continue

        if choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= len(visible):
                return resume_session(visible[idx - 1])
            print(f"  Out of range (1-{len(visible)}).\n")
            continue

        results = search_sessions(all_sessions, choice)
        print(f"\n  Search results for \"{choice}\" ({len(results)} match(es)):\n")
        visible = display_sessions(results, search_words=choice.lower().split())


def main():
    parser = argparse.ArgumentParser(
        description="Find and resume Claude Code sessions from any project.",
    )
    parser.add_argument(
        "search", nargs="*",
        help="search terms matched against folder, summary, and every prompt",
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
        print(f"No sessions found in {CLAUDE_DIR}")
        return 1

    if args.search:
        query = " ".join(args.search)
        visible = search_sessions(all_sessions, query)
        print(f"\n  Sessions matching \"{query}\" ({len(visible)} match(es)):\n")
        visible = display_sessions(visible, search_words=query.lower().split())
    else:
        visible = all_sessions if args.all else all_sessions[: args.count]
        print(f"\n  {len(visible)} of {len(all_sessions)} session(s). Most recent first:\n")
        visible = display_sessions(visible)

    if not visible and not args.search:
        return 1

    return prompt_loop(all_sessions, visible)


if __name__ == "__main__":
    sys.exit(main())
