from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone
import io
import math
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time
from urllib.parse import urlsplit

from rich.console import Console
from rich.table import Table
from rich import box

from .models import Contest, Reference, Submission, VPError
from .history_lines import enrich_history
from .parsing import contest_url, contest_id_url
from .receipts import ReceiptReader
from .scoring import medal_lines, rank_of, rank_label, prize_of, recent_submissions, revealed_problems, score_submissions, statistics, submission_history
from .storage import config_directory, desktop, file_lock, read_history, read_json, state_directory, update_history, write_json
from .tui import display, TerminalDashboard

console = Console()


def adapter(url: str, config: dict):
    from .qoj import QOJ
    _, _, canonical = contest_url(url)
    return QOJ(canonical, config.get("qoj", {}))


# Cookies QOJ sets on path "/" for qoj.ac, in the order the login wizard asks for
# them.  Only the session cookie is required; the rest are kept because the
# judge may reject a request that lacks them (cf_clearance gates Cloudflare).
COOKIE_FIELDS = {
    "qoj": (
        ("__Host-UOJREMEMBER", "remember-me token", False),
        ("__Host-UOJSESSID", "login session", True),
        ("cf_clearance", "Cloudflare clearance", False),
        ("uoj_preferred_language", "language preference", False),
    ),
}


def terminal_handle():
    """One open handle on the user's terminal, or None when there is none.

    Every prompt reads *and* writes this handle, so a pipe on stdin or a
    redirected stdout can never split a question from its answer.  /dev/tty is
    tried first; stdio is used when stdin is already a terminal (including the
    tmux pane and `script` wrappers).
    """
    try:
        handle = open("/dev/tty", "r+", buffering=1, encoding="utf8", errors="replace")
        return handle, True
    except OSError:
        pass
    if sys.stdin.isatty():
        return None, True
    return None, False


def can_prompt() -> bool:
    return terminal_handle()[1]


def _tty_errors() -> tuple:
    """Exceptions a terminal read may raise; termios.error is NOT an OSError."""
    try:
        import termios
        return (EOFError, OSError, ValueError, io.UnsupportedOperation, termios.error)
    except ImportError:  # pragma: no cover - non-POSIX
        return (EOFError, OSError, ValueError, io.UnsupportedOperation)


def _read_secret_line(target) -> str:
    """Read one line without echo from `target` (a terminal handle or sys.stdin).

    Two details matter on real terminals (tmux, screen, some emulators):
    * TCSADRAIN waits until the terminal has transmitted pending output; on a
      full pty buffer that can stall, so the mode change uses TCSANOW.
    * Type-ahead still sitting in the kernel queue is flushed, otherwise a
      half-typed line would be consumed as the cookie or leak into the shell.
    """
    fd = target.fileno()
    if not os.isatty(fd):
        raise OSError("not a terminal")
    import termios
    saved = termios.tcgetattr(fd)
    changed = termios.tcgetattr(fd)
    changed[3] &= ~termios.ECHO
    # Only discard stale type-ahead when nothing is waiting: flushing a queued
    # line (pasting, scripted answers, tmux send-keys) would eat the real answer.
    import select
    if not select.select([fd], [], [], 0)[0]:
        termios.tcflush(fd, termios.TCIFLUSH)
    termios.tcsetattr(fd, termios.TCSANOW, changed)
    try:
        line = target.readline()
    finally:
        termios.tcsetattr(fd, termios.TCSANOW, saved)
    return line.rstrip("\n")


def ask(prompt: str, *, secret: bool = False, handle=None) -> str:
    """Prompt and read on the same channel; empty string on EOF.

    The prompt goes to the terminal *and* stderr: when a wrapper redirects one
    of them, the user still sees what is being asked instead of a silent wait.
    """
    target = handle if handle is not None else sys.stdin
    errors = _tty_errors()
    written = False
    if handle is not None:
        try:
            handle.write(prompt)
            handle.flush()
            written = True
        except errors + (AttributeError,):
            pass
    if not written:
        for stream in (sys.stderr, sys.stdout):
            try:
                stream.write(prompt)
                stream.flush()
                break
            except errors + (AttributeError,):
                continue
    try:
        if secret and target.isatty():
            return _read_secret_line(target).strip()
        if target is sys.stdin:
            return input().strip()
        return target.readline().strip()
    except errors:
        if not secret:
            return ""
        # Echo control failed (tmux edge cases, odd ptys): still read the line
        # rather than leaving the user at an unresponsive prompt.
        try:
            line = target.readline()
        except errors:
            return ""
        if not line:
            return ""
        for stream in (sys.stderr, sys.stdout):
            try:
                stream.write("\n(cookie is shown because hidden input is unavailable)\n")
                stream.flush()
                break
            except errors + (AttributeError,):
                pass
        return line.strip()


def _say(lines, handle) -> None:
    """Print through the terminal handle so redirected stdout keeps the dialog."""
    if handle is None:
        for line in lines:
            console.print(line, markup=False)
        return
    handle.write("\n".join(lines) + "\n")
    handle.flush()


def login_name(platform: str) -> str:
    return "qoj"


def _cookie_names(cookie: str) -> set:
    return {part.split("=", 1)[0].strip() for part in cookie.split(";") if "=" in part}


def cookie_wizard(platform: str, account: dict, handle) -> str:
    """Ask for each platform cookie in a fixed order and build the header value.

    One prompt per cookie is far more forgiving than one long paste: a missed
    semicolon or a stray ``Path=/`` no longer silently drops the session.  Enter
    on an existing value keeps it, and the required cookie cannot be skipped.
    """
    fields = COOKIE_FIELDS.get(platform, ())
    current = account.get("cookie", "")
    existing = {}
    for part in current.split(";"):
        if "=" in part:
            name, _, value = part.partition("=")
            existing[name.strip()] = value.strip()
    site = "QOJ"
    _say([f"Enter the {site} cookies from devtools (Network -> request -> Request Headers -> Cookie).",
          "Paste only the value after '=', never the name or a 'Path=/'-style attribute."], handle)
    values = {}
    for index, (name, purpose, required) in enumerate(fields, start=1):
        stored = existing.get(name, "")
        marker = "required" if required else ("Enter keeps it" if stored else "optional, Enter skips")
        _say([f"[{index}/{len(fields)}] {name} ({purpose}) — {marker}"], handle)
        while True:
            value = ask(f"{name}: ", secret=False, handle=handle).strip()
            # A pasted "name=value" pair is accepted, the name is stripped.
            if value.startswith(name + "="):
                value = value[len(name) + 1:].strip()
            value = value.strip(";").strip()
            if value:
                values[name] = value
                break
            if stored:
                values[name] = stored
                break
            if not required:
                break
            _say([f"{name} is required for {site}; paste its value."], handle)
    # Keep anything extra the browser sent (uoj_csrf and friends) that we did not ask for.
    wanted = {name for name, _, _ in fields}
    for name, value in existing.items():
        if name not in wanted and name not in values and value:
            values[name] = value
    return "; ".join(f"{name}={value}" for name, value in values.items())


def prompt_cookie(site: str, platform: str, account: dict, handle) -> str:
    return cookie_wizard(platform, account, handle)


def load_account(platform: str) -> dict:
    path = config_directory() / "config.json"
    config = read_json(path)
    account = config.setdefault(platform, {})
    site = "QOJ"
    handle, interactive = terminal_handle()
    try:
        if interactive and not account.get("cookie"):
            # A cookie is the only credential now that the browser import is
            # gone, so a first run asks for it instead of failing later.
            value = prompt_cookie(site, platform, account, handle)
            if value:
                account["cookie"] = value
                write_json(path, config)
        if not account.get("cookie"):
            raise VPError(f"No {site} cookie is configured. Run: vp login {login_name(platform)}")
        missing = [field for field in ("handle", "cookie") if not account.get(field)]
        if missing and not interactive:
            raise VPError(f"Missing {platform} account fields {', '.join(missing)} in {path}")
        if missing:
            _say([f"First use: configure the existing {platform} login session."], handle)
            labels = {"handle": "Account handle",
                      "cookie": "Browser login Cookie (copy the Cookie value only)"}
            for field in missing:
                # Cookie and handle are both plain text: a hidden paste cannot be
                # checked, and these values are not passwords.
                value = ask(labels[field] + ": ", handle=handle)
                if not value:
                    raise VPError("An account field was empty; no native VP was started.")
                account[field] = value
            write_json(path, config)
    finally:
        if handle is not None:
            handle.close()
    return config


def history() -> None:
    rows = enrich_history(read_history(desktop() / "vp_history.csv"), state_directory())
    table = Table(box=box.SIMPLE, header_style="bold")
    columns = ("start_time", "contest", "solved", "penalty", "rank", "prize", "gold_line", "silver_line", "bronze_line")
    for key in columns:
        table.add_column(key.removesuffix("_line"))
    for row in sorted(rows, key=lambda r: r["start_time"], reverse=True):
        values = []
        for key in columns:
            value = row.get(key) or "—"
            if key.endswith("_line"):
                value = value.replace(" (", "\n(")
            values.append(value)
        table.add_row(*values)
    console.print(table)
    if rows:
        console.print("Medal lines: solved/penalty, then rank limit. Original official final standings; — = unavailable.", markup=False)


def configure_submit(api, contest: Contest, directory: Path) -> None:
    script = api.account.get("submit_script") or shutil.which("submit")
    selected = state_directory() / "submit"
    resolved = os.path.realpath(script) if script else ""
    bundled = bool(script and Path(script).exists() and
                   (resolved == os.path.realpath(selected)
                    or os.path.basename(resolved) == "submit" and
                    Path(resolved).parent.parent.name == "third_party"))
    if not script or not Path(script).is_file() or not os.access(script, os.X_OK):
        raise VPError("The existing submit script is not installed; configure its path in ~/.config/vp/config.json.")
    ids = [int(value) for value in contest.problems.values()]
    if not bundled and ids != list(range(ids[0], ids[0] + len(ids))):
        raise VPError("This QOJ contest has nonconsecutive problem IDs. Use the installed submit script with problem_ids support.")
    write_json(directory / "contest.json", api.submit_configuration(contest))
    if bundled:
        found = Path(resolved).parent.parent
        tool = found / "qoj" / "submit"
        if not tool.is_file() or not os.access(tool, os.X_OK):
            raise VPError("The bundled QOJ submit script is missing; reinstall vp.")
        temporary = selected.with_name("submit.new")
        selected.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary.unlink(missing_ok=True)
        temporary.symlink_to(tool)
        os.replace(temporary, selected)


def bind_submit_context(directory: Path, state_path: Path, state: dict) -> None:
    path = directory / "contest.json"
    if not path.is_file():
        return
    config = read_json(path)
    config.setdefault("handle", state["handle"])
    config["vp_context"] = {"state_path": str(state_path), "start_time": state["start_time"],
                            "url": state["url"], "handle": state["handle"]}
    write_json(path, config)


def tmux_exists(name: str) -> bool:
    return subprocess.run(["tmux", "has-session", "-t", name], capture_output=True).returncode == 0


def attach(name: str) -> None:
    command = ["tmux", "switch-client" if os.environ.get("TMUX") else "attach-session", "-t", name]
    subprocess.run(command, check=True)


def launch(state_path: Path, state: dict) -> None:
    name = state["tmux_session"]
    directory = state["directory"]
    monitor = shlex.join([sys.executable, "-m", "vp_helper.cli", "_monitor", str(state_path)])
    # A percentage split (-p) cannot be resolved on a session that has no client
    # yet: tmux aborts with "size missing".  Give the session the real terminal
    # geometry and split by an absolute number of lines instead.
    columns, rows = shutil.get_terminal_size(fallback=(80, 24))
    shell_rows = max(4, rows * 3 // 10)
    subprocess.run(["tmux", "new-session", "-d", "-s", name,
                    "-x", str(columns), "-y", str(rows), "-c", directory, monitor], check=True)
    try:
        subprocess.run(["tmux", "set-option", "-t", name, "remain-on-exit", "on"], check=True)
        subprocess.run(["tmux", "set-option", "-t", name, "mouse", "on"], check=True)
        # -c only fixes the first window. tmux 3.8 removed default-path, so a
        # window opened later would land wherever the tmux server was started;
        # the hook moves each new shell into the contest directory instead.
        subprocess.run(["tmux", "set-hook", "-t", name, "after-new-window",
                        f'run-shell "tmux send-keys -t #{{window_id}} '
                        f'\\"cd {shlex.quote(str(directory))}\\" C-m"'], check=True)
        shell = os.environ.get("SHELL", "/bin/bash")
        subprocess.run(["tmux", "split-window", "-v", "-l", str(shell_rows), "-t", name,
                        "-c", directory, "exec " + shlex.quote(shell)], check=True)
        subprocess.run(["tmux", "select-pane", "-t", name + ":0.1"], check=True)
    except subprocess.CalledProcessError:
        # Preserve the monitor/session if only the shell pane failed to start.
        raise VPError(f"VP monitoring started in tmux session {name}; the shell pane failed to start.") from None


def verify_login(platform: str, api) -> None:
    """Fail fast on a rejected cookie before downloading statements or states.

    QOJ answers unauthenticated requests with the public home page, so a missing
    session only surfaces later as a confusing "not offered / does not belong"
    error.  Reused by `vp login` so both report the same thing.
    """
    origin = getattr(api, "origin", None) or f"https://{urlsplit(api.url).hostname}"
    prefix = "/user/profile/" if platform == "qoj" else "/profile/"
    response = api.web.get(origin + "/")
    try:
        html = response.text
    except Exception:
        return
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    seen = {urlsplit(a.get("href", "")).path[len(prefix):].rstrip("/")
            for node in soup.select("ul.nav-pills, .navbar, nav, header, #header")
            for a in node.select(f'a[href*="{prefix}"]')}
    if not seen:
        raise VPError(f"The {platform} cookie is not accepted: {origin} shows no signed-in account. "
                      f"Run 'vp login {platform}' for details.")
    handle = getattr(api, "handle", "")
    if handle and handle not in seen and not (platform != "qoj" and handle.lower() in {h.lower() for h in seen}):
        raise VPError(f"The cookie belongs to {', '.join(sorted(seen))}, not the configured handle {handle!r}. "
                      f"Fix ~/.config/vp/config.json or run 'vp login {platform}'.")


def prepare_start(url: str) -> tuple[Path, dict]:
    if sys.platform not in ("linux", "darwin"):
        raise VPError(f"vp runs on Linux and macOS, not {sys.platform}.")
    if not sys.stdin.isatty():
        raise VPError("Run vp in an interactive terminal.")
    if shutil.which("tmux") is None:
        raise VPError("tmux is missing; run the installer.")
    platform, _, canonical = contest_url(url)
    state_root = state_directory()
    state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with file_lock(state_root / "start.lock"):
        current = read_json(state_root / "current.json")
        if current:
            old = read_json(Path(current["state_path"]))
            if old.get("url") == canonical and tmux_exists(old.get("tmux_session", "")):
                # A resumed session still needs a usable local submission file;
                # refreshing it never starts or resets the native participation.
                config = load_account(platform)
                api = adapter(canonical, config)
                if api.handle != old.get("handle"):
                    raise VPError("The configured account changed; restore this VP's account before resuming it.")
                directory = Path(old["directory"])
                directory.mkdir(parents=True, exist_ok=True)
                configure_submit(api, Contest.from_dict(old["contest"]), directory)
                bind_submit_context(directory, Path(current["state_path"]), old)
                return Path(current["state_path"]), old
            if old.get("status") != "complete" and time.time() < old.get("start_time", 0) + old.get("contest", {}).get("rules", {}).get("duration", 0):
                raise VPError(f"A native VP is already running: {old.get('url')}. Open that URL to resume it.")
        config = load_account(platform)
        api = adapter(canonical, config)
        verify_login(platform, api)
        console.print("Reading contest information…", markup=False)
        contest = api.prepare()
        ask_srk_archive(contest)
        root = desktop()
        root.mkdir(parents=True, exist_ok=True)
        contest.directory_name = " ".join(contest.directory_name.split())
        directory = root / contest.directory_name
        directory.mkdir(exist_ok=True)
        configure_submit(api, contest, directory)
        for name, pdf in contest.pdfs.items():
            console.print("Downloading " + name, markup=False)
            api.web.pdf(pdf, directory / name)
        # Offer the replay before the judge is touched, so the page is already
        # open when the native VP starts.
        pending = ask_xcpc_setup(contest)
        console.print("Starting and verifying native virtual participation…", markup=False)
        started = api.start(contest)
        name = "vp-" + platform + "-" + contest.contest_id + "-" + str(int(started))
        path = state_root / (name + ".json")
        saved = read_json(path)
        state = {"contest": contest.to_dict(), "url": canonical, "start_time": started,
                 "handle": api.handle,
                 "directory": str(directory), "tmux_session": name, "status": "running",
                 "submissions": saved.get("submissions", []), "recent": saved.get("recent", []),
                 "history_path": str(root / "vp_history.csv")}
        state["xcpc_pending"] = pending
        write_json(path, state)
        bind_submit_context(directory, path, state)
        write_json(state_root / "current.json", {"state_path": str(path)})
        console.print("Prepared " + str(directory), markup=False)
        return path, state


def start(url: str) -> None:
    # Release the cross-shell preparation lock before entering an attached TUI.
    path, state = prepare_start(url)
    bind_submit_context(Path(state["directory"]), path, state)
    if tmux_exists(state["tmux_session"]):
        pane = state["tmux_session"] + ":0.0"
        dead = subprocess.run(["tmux", "display-message", "-p", "-t", pane, "#{pane_dead}"],
                              check=True, capture_output=True, text=True).stdout.strip()
        if dead == "1":
            command = shlex.join([sys.executable, "-m", "vp_helper.cli", "_monitor", str(path)])
            subprocess.run(["tmux", "respawn-pane", "-t", pane, "-c", state["directory"], command], check=True)
        subprocess.run(["tmux", "set-option", "-t", state["tmux_session"], "mouse", "on"], check=True)
        attach(state["tmux_session"])
    else:
        # launch() only builds the session here: attaching takes the terminal
        # over, so anything still to print has to happen before it.
        launch(path, state)
        deliver_xcpc(path, state)
        attach(state["tmux_session"])


def ask_srk_archive(contest: Contest) -> None:
    """Let the user name the archive path when the title alone cannot find it.

    Only a title the parser could not resolve reaches here, because guessing a
    path for a contest we did understand would invite the wrong edition.
    """
    from . import srk
    # Ask whenever the archive cannot be located, including titles the parser
    # could not classify at all; those are exactly the cases a human can place.
    if srk.source_url(contest):
        return
    handle, interactive = terminal_handle()
    try:
        if not interactive:
            return
        console.print("", markup=False)
        console.print("No SRK archive was found for this contest automatically.", markup=False)
        console.print("Enter its path inside algoux/srk-collection, for example:", markup=False)
        console.print("  official/provincial/js/jscpc10th.srk.json", markup=False)
        answer = ask("SRK path (blank to skip): ", handle=handle).strip()
        if not answer:
            return
        if not answer.endswith(".srk.json"):
            answer += ".srk.json"
        contest.extra["srk_source"] = answer.lstrip("/")
    finally:
        if handle is not None:
            handle.close()


def print_url(url: str) -> None:
    """Print an address on its own lines so a long URL never breaks mid-token."""
    console.print("  " + url, markup=False, highlight=False)


def ask_xcpc_setup(contest: Contest) -> dict:
    """Collect the team and serve the page before the native VP is requested.

    The judge has not been touched yet, so a first run has no registration time;
    the page is anchored on the moment it opens and ``deliver_xcpc`` re-anchors
    it once the judge reports its own start.
    """
    from . import xcpc_bridge
    if not xcpc_bridge.enabled():
        return {}
    handle, interactive = terminal_handle()
    try:
        if not interactive:
            return {}
        console.print("", markup=False)
        console.print("Set up the browser replay before the native VP starts.", markup=False)
        team = ask("Team name (blank to skip the replay): ", handle=handle).strip()
        if not team:
            console.print("xcpc-vp: skipped; the terminal panel works on its own.", markup=False)
            return {}
        organization = ask("School / organization: ", handle=handle).strip()
        try:
            url, key = xcpc_bridge.prepare(contest, team, organization, time.time())
        except VPError as exc:
            console.print("xcpc-vp: " + str(exc), markup=False)
            return {}
        console.print("", markup=False)
        console.print("Open this address in your browser:", markup=False)
        print_url(url)
        console.print("Contest: " + (key or "not matched; pick it on the page"), markup=False)
        console.print("", markup=False)
        answer = ask("Press Enter once the replay is running (n to skip the check): ", handle=handle).strip()
        checked = answer.lower() not in ("n", "no", "q", "quit")
        if checked:
            report_xcpc_status(key)
        return {"team": team, "organization": organization, "contest": key or "",
                "checked": checked, "url": url}
    finally:
        if handle is not None:
            handle.close()


def deliver_xcpc(path: Path, state: dict) -> None:
    """Re-anchor the page on the judge's own start and record the account.

    The state file is rewritten because the monitor runs in another process and
    only mirrors submissions once it can read the team from disk.
    """
    pending = state.get("xcpc_pending") or {}
    if not pending.get("team"):
        return
    from . import xcpc_bridge
    contest = Contest.from_dict(state["contest"])
    team, organization, key = pending["team"], pending.get("organization", ""), pending.get("contest", "")
    url, matched = xcpc_bridge.page_url(contest, team, organization, state["start_time"], xcpc_bridge.port())
    key = matched or key
    state.update(xcpc_team=team, xcpc_organization=organization, xcpc_contest=key,
                 xcpc_events=[])
    write_json(path, state)
    write_json(state_directory() / "xcpc-vp.json", {
        "contest": key, "team": team, "organization": organization,
        "start_time": state["start_time"], "url": state["url"]})
    console.print("", markup=False)
    console.print("Native VP started at " + xcpc_bridge._china_time(state["start_time"]) + ".", markup=False)
    console.print("Reload the replay so its clock matches the judge:", markup=False)
    print_url(url)
    console.print("", markup=False)


def report_xcpc_status(key: str) -> None:
    """One readiness line for the page, so a broken replay is visible at once."""
    from . import webui
    from .xcpc_bridge import port as xcpc_port
    number = xcpc_port()
    page = "page serving" if webui.reachable(number) else f"page NOT reachable on port {number}"
    try:
        seen = len(webui.feed(number).get("events") or [])
        page += f", feed answered ({seen} submissions mirrored)"
    except Exception:
        page += ", feed did not answer"
    console.print("xcpc-vp: " + page, markup=False)
    if not key:
        console.print("xcpc-vp: no archive match; choose the contest on the page to see submissions.", markup=False)


def poll(api, contest: Contest, elapsed: float, refresh_reference: bool = False):
    """Keep slow requests outside the terminal's input and redraw loop."""
    try:
        result = api.reference(contest, elapsed) if refresh_reference else api.submissions(contest)
        message = getattr(api, "submission_message", "") if not refresh_reference else ""
        return result, message if isinstance(message, str) else ""
    except VPError as exc:
        return None, str(exc)


def monitor(path: Path) -> None:
    # tmux's default "screen" terminfo only exposes eight colors. Its terminal
    # supports the 256-color palette needed for orange and purple practice rows.
    if os.environ.get("TMUX") and os.environ.get("TERM") in ("screen", "tmux"):
        os.environ["TERM"] = "screen-256color"
    with file_lock(path.with_suffix(".monitor.lock"), nonblocking=True):
        state = read_json(path)
        contest = Contest.from_dict(state["contest"])
        config = read_json(config_directory() / "config.json")
        api = adapter(contest.url, config)
        if state.get("handle") and api.handle != state["handle"]:
            raise VPError("The configured account changed; restore this VP's account before resuming it.")
        api.start_time = state["start_time"]
        reference_api = adapter(contest.url, config)
        reference_api.start_time = state["start_time"]
        submissions = {x["id"]: Submission(**x) for x in state.get("submissions", [])}
        final_score_key = (score_submissions(list(submissions.values()), list(contest.problems),
                                           contest.rules, contest.rules.duration).rank_key
                           if state.get("status") == "complete" else None)
        if hasattr(api, "seed_submissions"):
            api.seed_submissions(list(submissions.values()))
        receipts = ReceiptReader(path, state)
        reference = Reference()
        last_poll = 0.0
        next_poll = next_reference = 0.0
        backoff = 5.0
        submission_error = reference_error = ""
        have_polled = False
        future = reference_future = None
        next_render = 0.0
        with ThreadPoolExecutor(max_workers=2) as network, TerminalDashboard() as view:
            while view.input():
                elapsed = time.time() - state["start_time"]
                now = time.monotonic()
                fresh_submissions = False
                for receipt in receipts.read():
                    if receipt.id not in submissions:
                        submissions[receipt.id] = receipt
                        fresh_submissions = True
                        next_poll = 0.0
                if future is not None and future.done():
                    incoming, error = future.result()
                    future = None
                    if incoming is not None:
                        fresh_submissions = True
                        have_polled = True
                        for submission in incoming:
                            submissions[submission.id] = submission
                        last_poll = now
                    submission_error = error
                    pending = any(s.verdict == "PENDING" for s in submissions.values())
                    backoff = min(60.0, max(5.0, backoff * 2)) if error and incoming is None else 2.0 if pending else 5.0
                    next_poll = now + backoff
                if reference_future is not None and reference_future.done():
                    refreshed, reference_error = reference_future.result()
                    reference_future = None
                    if refreshed is not None:
                        reference = refreshed
                    next_reference = now + 30
                if future is None and now >= next_poll:
                    future = network.submit(poll, api, contest, elapsed)
                if reference_future is None and now >= next_reference:
                    reference_future = network.submit(poll, reference_api, contest, elapsed, True)
                current_reference = (reference.replay.at(contest, elapsed, released=reference.released)
                                     if reference.replay is not None else reference)
                frozen = contest.rules.frozen(elapsed, current_reference.released)
                # Rebuild from canonical submissions, including when resuming old
                # state or offline. Discovery order is not submission chronology.
                recent = recent_submissions(list(submissions.values()), list(contest.problems), contest.rules, elapsed)
                records = submission_history(list(submissions.values()), list(contest.problems), contest.rules, elapsed)
                private = score_submissions(list(submissions.values()), list(contest.problems), contest.rules,
                                            elapsed, name=api.handle)
                public_elapsed = (math.nextafter(float(contest.rules.freeze_at), -math.inf)
                                  if contest.rules.problem_reveal_count and frozen else elapsed)
                public = score_submissions(list(submissions.values()), list(contest.problems), contest.rules,
                                           public_elapsed, public=True, released=current_reference.released, name=api.handle)
                all_final = all(s.verdict not in ("PENDING", "UNAVAILABLE") for s in submissions.values() if 0 <= s.time < contest.rules.duration)
                finalized = (elapsed >= contest.rules.duration and not frozen and current_reference.complete
                             and api.submissions_complete and have_polled and all_final)
                rank = "?" if frozen else str(rank_of(private, current_reference.rows)) if current_reference.complete and private.results_complete else "—"
                shown_rank = rank_label(private, current_reference.rows) if current_reference.complete and private.results_complete and not frozen else rank
                prize = prize_of(private, current_reference.rows, contest.medals) if finalized else ""
                stats = statistics(current_reference.rows + [public], list(contest.problems)) if current_reference.statistics_complete and public.results_complete else None
                shown_message = submission_error or reference_error or current_reference.message
                if finalized and current_reference.replay is not None and not submission_error and not reference_error:
                    shown_message = "Finished"
                elif not have_polled and not shown_message:
                    shown_message = "Connecting…"
                if finalized and not shown_message:
                    shown_message = "Finished"
                elif frozen and not shown_message:
                    shown_message = "Scoreboard frozen"
                if last_poll and now - last_poll > 15:
                    shown_message = "Results stale · " + shown_message
                if now >= next_render:
                    dashboard = display(contest, elapsed, private, shown_rank, prize, stats, records, shown_message)
                    dashboard.revealed = revealed_problems(contest, elapsed, current_reference)
                    view.update(dashboard)
                    next_render = now + 0.25
                if fresh_submissions:
                    preserve_final = (state.get("status") == "complete" and all_final
                                      and private.rank_key == final_score_key)
                    if finalized:
                        final_score_key = private.rank_key
                        state["medal_lines"] = medal_lines(current_reference.rows, contest.medals)
                    state.update(contest=contest.to_dict(), submissions=[asdict(x) for x in submissions.values()],
                                 recent=recent, submission_history=records, last_sync_time=time.time(),
                                 status="complete" if finalized or preserve_final else "running")
                    adopt_xcpc(path, state)
                    write_json(path, state)
                    publish_xcpc(path, state, contest, submissions)
                    row = {"start_time": datetime.fromtimestamp(state["start_time"], timezone.utc).isoformat(),
                           "contest": contest.name, "url": contest.url, "solved": private.solved,
                           "penalty": private.penalty if private.results_complete else "", "rank": rank if finalized else "", "prize": prize}
                    if finalized or not preserve_final:
                        update_history(Path(state["history_path"]), row)
                time.sleep(0.1)


def adopt_xcpc(path: Path, state: dict) -> None:
    """Take xcpc_* fields another process wrote into this stale in-memory copy.

    The launching process records the team after the monitor has already loaded
    its own snapshot; without this the monitor's next write would erase it.
    """
    if state.get("xcpc_team"):
        return
    on_disk = read_json(path)
    if on_disk.get("xcpc_team"):
        state.update({key: value for key, value in on_disk.items() if key.startswith("xcpc_")})


def publish_xcpc(path: Path, state: dict, contest: Contest, submissions: dict) -> None:
    """Mirror judge-verified results into the open page.

    A terminal has no BroadcastChannel, so the page polls this file; only final
    verdicts are written because a pending row would be recorded as a result.
    The team is read back from disk because it is recorded in the launching
    process after the monitor already loaded its own copy.
    """
    from . import xcpc_bridge
    if not xcpc_bridge.enabled():
        return
    adopt_xcpc(path, state)
    if not state.get("xcpc_team"):
        return
    finals = [item for item in submissions.values()
              if item.verdict not in ("PENDING", "UNAVAILABLE", "TOO-LATE")]
    payload = xcpc_bridge.channel_payload(contest, state.get("xcpc_contest") or "",
                                          finals, state["start_time"])
    if payload["events"] == state.get("xcpc_events"):
        return
    payload["team"], payload["organization"] = state["xcpc_team"], state.get("xcpc_organization", "")
    payload["startTime"] = state["start_time"]
    try:
        xcpc_bridge.write_channel(payload)
    except OSError:
        return
    state["xcpc_events"] = payload["events"]


def _probe_login(platform: str, account: dict) -> tuple[str, set]:
    """Return (landing url, detected handles) for the stored cookie."""
    from .http import WebSession
    from bs4 import BeautifulSoup
    site = "qoj.ac"
    web = WebSession(f"https://{site}", account)
    try:
        response = web.session.get(f"https://{site}/", params={"locale": "en"}, timeout=(10, 30))
        final = response.url
        console.print(f"landed:   {final}", markup=False)
        console.print(f"status:   {response.status_code}", markup=False)
        landed = urlsplit(final)
        if landed.path.rstrip("/") in ("/login", "/enter"):
            raise VPError(f"The cookie was rejected: {site} redirected to {landed.path}.")
        if "cf-chl-" in response.text[:3000] or "Just a moment..." in response.text:
            raise VPError("Cloudflare challenge; refresh cf_clearance from the browser.")
        prefix = "/user/profile/"
        soup = BeautifulSoup(response.text, "html.parser")
        found = {urlsplit(a.get("href", "")).path[len(prefix):].rstrip("/")
                 for header in soup.select("ul.nav-pills, .navbar, nav, header, #header")
                 for a in header.select("a[href]") if urlsplit(a["href"]).path.startswith(prefix)}
        return final, found
    finally:
        web.session.close()


def login_check(platform: str) -> None:
    """Interactive login: ask for handle and every platform cookie, save, verify.

    The cookie is asked one name at a time (see COOKIE_FIELDS) so a missing
    semicolon or a stray attribute cannot silently drop the session.  The result
    is written to the config and immediately checked against the live site.
    """
    site = "QOJ"
    path = config_directory() / "config.json"
    config = read_json(path)
    account = config.setdefault(platform, {})
    handle, interactive = terminal_handle()
    try:
        if not interactive:
            raise VPError("vp login needs an interactive terminal.")
        existing = account.get("handle", "")
        prompt = f"Account handle [{existing}]: " if existing else "Account handle: "
        value = ask(prompt, secret=False, handle=handle).strip()
        if value:
            account["handle"] = value
        elif existing:
            account["handle"] = existing
        else:
            raise VPError("A handle is required; vp cannot tell which account is signed in.")
        cookie = cookie_wizard(platform, account, handle)
        if not cookie:
            raise VPError("No cookie was entered.")
        account["cookie"] = cookie
        write_json(path, config)
        _say([f"Saved to {path}"], handle)
        if handle is not None:
            # handle is None when stdin already is the terminal; never close it.
            handle.close()
            handle = None

        _say(["Verifying against " + site + " …"], None)
        names = _cookie_names(cookie)
        console.print("cookies:  " + (", ".join(sorted(names)) or "(none)"), markup=False)
        _, found = _probe_login(platform, account)
        console.print(f"account:  {', '.join(sorted(found)) or '(not detected)'}", markup=False)
        if not found:
            missing = [name for name, _, required in COOKIE_FIELDS.get(key, ()) if required and name not in names]
            hint = (" missing required cookie: " + ", ".join(missing)) if missing else ""
            raise VPError("The cookie was sent but no signed-in account was found." + hint
                          + f" Re-run 'vp login {login_name(platform)}'.")
        wanted = account["handle"]
        if wanted not in found and not (platform != "qoj" and wanted.lower() in {h.lower() for h in found}):
            raise VPError(f"The cookie belongs to {', '.join(sorted(found))}, not {wanted!r}. "
                          f"Update the handle or re-run 'vp login {login_name(platform)}'.")
        console.print("OK: vp is authenticated as " + ", ".join(sorted(found)), markup=False)
    finally:
        if handle is not None:
            handle.close()


def main() -> None:
    args = sys.argv[1:]
    try:
        if args == ["history"]:
            history()
        elif args and args[0] == "login" and len(args) in (1, 2):
            login_check(args[1] if len(args) == 2 else "qoj")
        elif len(args) == 2 and args[0] == "_monitor":
            monitor(Path(args[1]))
        elif len(args) == 2 and args[0] == "qoj":
            start(contest_id_url(*args))
        elif len(args) == 1 and args[0] not in ("-h", "--help"):
            start(args[0])
        elif args in ([], ["-h"], ["--help"]):
            console.print("Usage: vp qoj ID\n       vp CONTEST_URL\n       vp history\n       vp login [qoj]", markup=False)
        else:
            raise VPError("Usage: vp qoj ID, vp CONTEST_URL or vp history")
    except (VPError, OSError, subprocess.CalledProcessError) as exc:
        console.print("vp: " + str(exc), style="red", markup=False)
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
