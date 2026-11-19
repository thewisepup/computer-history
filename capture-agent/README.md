# Capture agent

The Swift agent that macOS starts at login. It checks its Accessibility grant
on start, readies the spool, then captures the focused window's text into the
spool whenever focus changes and every 30 seconds (by default) while the user is
at the Mac.

| | |
|---|---|
| Bundle id | `io.github.thewisepup.computer-history.agent` |
| Installed at | `~/Applications/ComputerHistoryAgent.app` |
| Started by | `SMAppService`, from `Contents/Library/LaunchAgents/` inside the bundle (KeepAlive) |
| Signed with | `Computer History Code Signing` from the login keychain, hardened runtime |
| Logs | unified log, subsystem `io.github.thewisepup.computer-history.agent` |
| Folder | `~/Library/Application Support/ComputerHistory/`, beside `history.db` |
| Spool | `spool/` in the folder |
| Config | `agent-config.json` in the folder, optional |

## Commands

Run these from `capture-agent/`.

```bash
scripts/test.sh        # swift test, with the Swift Testing paths Command Line Tools need
scripts/build.sh       # build, wrap in .build/ComputerHistoryAgent.app, sign, verify
scripts/install.sh     # build, replace the installed app, register the login item, check it runs
scripts/uninstall.sh   # unregister the login item, stop the agent, delete the app
```

With Xcode installed, plain `swift test` works too. Under Command Line Tools
alone it cannot find the `Testing` module, so use `scripts/test.sh`.

The installed binary takes the same commands directly:

```bash
agent=~/Applications/ComputerHistoryAgent.app/Contents/MacOS/computer-history-agent
"$agent" status        # Login item: enabled, starts at login. / Capture: not paused.
"$agent" pause         # stop capturing until resume, across restarts and reboots
"$agent" resume
"$agent" check-config  # where the settings came from, every problem, the settings in effect; exit 1 on problems
"$agent" uninstall
"$agent" install       # exit 2 means approval is needed in System Settings > General > Login Items & Extensions
```

None of these need the Accessibility grant, so they run from any terminal.

Running the binary with no arguments starts the agent in the foreground. From
a terminal, macOS checks the terminal's Accessibility grant, not the agent's,
so judge the grant only from the logs of the launchd-started agent.

## Folder and config

The agent finds its folder the way the backend does: `$COMPUTER_HISTORY_DB`
names the database and the folder is its parent; otherwise the folder is
`~/Library/Application Support/ComputerHistory/`. `$COMPUTER_HISTORY_SPOOL`
overrides the spool, which otherwise is `spool/` in the folder. Empty values
count as unset and a leading `~` is the home folder. The launchd-started agent
has neither variable set, and `pause`, `resume` and `check-config` run from a
shell that sets them act on that other folder.

`agent-config.json` in the folder holds the settings. Every key is optional:

| Key | Default | Allowed |
|---|---|---|
| `denylist` | `[]` | bundle ids added to the built-in denylist |
| `accessibility_flag_off_list` | `[]` | bundle ids that never get the accessibility flags |
| `idle_threshold_seconds` | `180` | 10 to 86400 |
| `capture_heartbeat_seconds` | `30` | 5 to 3600 |
| `text_cap_bytes` | `50000` | whole number, 1000 to 10000000 |
| `call_timeout_seconds` | `0.25` | 0.05 to 5 |
| `window_timeout_seconds` | `2` | 0.1 to 60 |

```json
{
  "denylist": ["com.apple.calculator"],
  "idle_threshold_seconds": 300
}
```

A missing file means defaults. A file that cannot be read or is not a JSON
object, an unknown key, a value of the wrong type or out of range, and a
list entry that is not a string are each logged at start as `config problem:
...` and reported by `check-config`; that value, or the whole file, falls back
to its default and capture carries on.

The config is read once at start. Restart the agent for a change to apply:

```bash
launchctl kickstart -k "gui/$(id -u)/io.github.thewisepup.computer-history.agent"
```

## Denylist

The agent never touches the windows of a denylisted app: no title polling and
no reads, not even the accessibility flags. While one is focused it writes an
`excluded` record, with the app name and bundle id and no title or text, on
the `app` trigger when it comes to the front and on every heartbeat while it
stays there. Window and title changes inside it go unnoticed.

The built-in denylist is `com.1password.1password`,
`com.agilebits.onepassword7`, `com.apple.keychainaccess` and
`com.apple.Passwords`. The config's `denylist` adds to it and cannot remove
from it, so no config, however wrong, captures one of these. Bundle ids match
ignoring case.

## Pause and resume

`pause` creates `capture-paused` in the folder and `resume` deletes it. The
capture thread checks for the file every tick, so the running agent notices
within half a second and writes one `paused` or `resumed` record at that
moment, trying again each tick if the write fails. Pausing twice writes one
record, as does resuming twice. The file
outlives the agent, so a restart or a reboot stays paused, the agent logs
`capture is paused, ...` at start, and the restart writes no further record.
A pause or resume while the agent is not running is recorded only if the agent
starts before it is undone.

While paused the agent makes no accessibility calls and writes nothing but
the `resumed` record that ends the pause. Pause is independent of idle, lock
and sleep: unlocking a paused Mac writes nothing, and resuming a locked Mac
writes `resumed` and captures once it is unlocked.

## Window text

`WindowTextReader` reads the focused window of a `FocusedApplication` and
returns a `WindowText`: the window title, the content text, the full text
length in UTF-8 bytes, whether the text was cut off or the read timed out, and
the SHA-256 of the kept text. `focusedApplication()` asks the
system-wide accessibility element for the focused app and falls back to
`NSWorkspace`.

| Role | Text taken |
|---|---|
| `AXStaticText`, `AXTextArea`, `AXTextField` | `AXValue`; children are read only when it is empty |
| `AXHeading`, `AXLink` | text of their children, else `AXTitle`, else `AXDescription` |
| `AXButton`, `AXPopUpButton`, `AXCheckBox`, `AXRadioButton` | nothing, children skipped |
| `AXSecureTextField` (role or subrole) | nothing, never read past its role |
| anything else (`AXWindow`, `AXGroup`, `AXRow`, ...) | nothing, children read |

The walk reads each element once, so a tree that links back to an ancestor
ends, and never descends into an `AXApplication` element, which some apps
return as their focused window while in the background or behind the lock
screen.

With the default settings, pieces are joined with newlines and cut at 50,000
bytes on a character boundary; the walk keeps counting the full length past
the cap. Each accessibility call times out after 0.25s and the whole read
after 2s; either ends the read with the text collected so far. Electron apps
and Chromium browsers get `AXManualAccessibility` and
`AXEnhancedUserInterface` set once per process, unless their bundle id is on
the config's `accessibility_flag_off_list` (ignoring case). A flag call that
times out does not end the read; the flags are tried again on the next read.

## Capturing

A capture thread with an 8 MB stack ticks every half second. Each tick checks
the pause file and presence, asks which app is focused, polls that app's
focused window and title through accessibility unless the app is denylisted,
and writes a `capture` or `excluded` record when one is due. The main
thread keeps the minute log line, the spool finish and the sleep and wake
notifications, so a slow read never delays them. The spool writer is shared by
both threads behind its lock.

| Trigger | When |
|---|---|
| `app` | the focused app changed |
| `window` | the focused window within the app changed |
| `title` | the focused window's title changed: a browser tab or editor file switch |
| `heartbeat` | 30 seconds (`capture_heartbeat_seconds`) passed with no capture, and once on start and on resuming |

A change waits one second to settle; further changes restart the wait, so a
burst of switches yields one capture of the final state, labelled with the
strongest trigger in the burst (`app`, then `window`, then `title`). A title
that never settles is still captured one heartbeat interval after it first
changed. Captures are at least one second apart, and every capture restarts
the heartbeat.

Nothing is captured while capture is paused, while the user is idle (by
default more than 180 seconds since the last keyboard or mouse input, from `CGEventSource`), while the screen is locked
or the session is switched away (`CGSessionCopyCurrentDictionary`), or between
`willSleep` and `didWake` (or the first input after `willSleep`, should
`didWake` never arrive). Capture resumes on its own, one second after the
last reason clears. Without the Accessibility grant no `capture` record is
written; `excluded` records still are, since they touch no window.

`CaptureSettings` holds the idle threshold, heartbeat interval, settle delay,
minimum gap and poll interval; the first two come from the config. An agent
that finds the spool held by another agent does not capture.

## Logs

`log` is a zsh builtin, so call `/usr/bin/log`:

```bash
/usr/bin/log stream --style compact --predicate 'subsystem == "io.github.thewisepup.computer-history.agent"'
/usr/bin/log show --last 1h --style compact --predicate 'subsystem == "io.github.thewisepup.computer-history.agent"'
launchctl print "gui/$(id -u)/io.github.thewisepup.computer-history.agent"
```

Expected lines: `started, accessibility granted` (or `missing, asked macOS to
prompt for it`), `config read from <path>, 4 apps denylisted` (or `config not
found at <path>, using defaults, ...`) followed by any `config problem: ...`,
`capture is paused, ...` when it is, `spool ready at <folder>`, then every
minute `heartbeat, accessibility granted, last minute: 12 captures written, 3
excluded, 1 timed out, 0 cut off, slowest read 0.42s`, with `, 2 failed to
write (last: <error>)` appended when writes fail. `silent: paused`, `silent:
idle`, `silent: locked, asleep` and `capturing again` mark silence starting,
changing and ending. The log never holds window titles or text. After a crash,
start also logs `spool finished leftover file <name>`.

## Spool

The agent appends one JSON record per line to `open.part` in the spool
folder. Every minute, if `open.part` is non-empty, it is renamed to a
finished file and the next record starts a new `open.part`. A leftover
`open.part` from a crash is finished the same way on start. A torn last line
is dropped before the rename, and the rename is atomic, so the backend, which
reads only `*.jsonl`, never sees a partial file.

Finished files are named `<yyyyMMdd'T'HHmmss.SSS'Z'>.jsonl` in UTC, for
example `20261118T090100.000Z.jsonl`. Each name is at least one millisecond
after every name the running agent has used and the newest name in the folder
when it started, so two finishes in the same millisecond, a leftover file
finished at start, or a clock that steps back never produce a name that sorts
out of order or replaces a file. The rename refuses to overwrite.

The agent holds `agent.lock` in the spool folder while it runs. A second
agent started by hand cannot take the lock and writes nothing.

Every record has every key, sorted, with `null` where a key does not apply:

| Key | Value |
|---|---|
| `version` | format version, `1` |
| `id` | lowercase UUID; becomes the observation's `source_id` |
| `captured_at` | UTC ISO-8601 with milliseconds, `2026-11-18T09:00:05.250Z` |
| `kind` | `capture`, `excluded`, `paused` or `resumed` |
| `trigger` | `app`, `window`, `title` or `heartbeat`; `null` for `paused` and `resumed` |
| `app_name` | the focused app; `null` for `paused` and `resumed` |
| `bundle_id` | the focused app's bundle id, or `null` |
| `window_title` | `capture` only |
| `text` | `capture` only: the window's text, possibly cut off or partial |
| `text_sha256` | `capture` only: lowercase hex SHA-256 of `text` as UTF-8 |
| `full_text_bytes` | `capture` only: UTF-8 length of all text read, before any cut |
| `text_cut_off` | `capture` only: `true` when `text` is shorter than the full text |
| `timed_out` | `capture` only: `true` when reading stopped at a timeout and the text is partial |

[`fixtures/spool/records.jsonl`](../fixtures/spool/records.jsonl) holds one
example of every kind and trigger. It is the contract with the backend: the
Swift tests check the encoder writes exactly those lines, and the Python tests
read the same file.

## Accessibility

On its first start without the grant the agent asks macOS to prompt. Turn on
Computer History Agent in System Settings > Privacy & Security >
Accessibility. The grant is tied to the bundle id and the signing
certificate, so it survives rebuilds signed with the same certificate.
Uninstalling leaves the grant in place; `tccutil reset Accessibility
io.github.thewisepup.computer-history.agent` removes it.

The login item is different: macOS pins it to the exact binary, so a
rebuilt agent fails its first launch. `scripts/install.sh` detects that,
forces the failed launch that makes macOS record the new binary, and
registers again.
