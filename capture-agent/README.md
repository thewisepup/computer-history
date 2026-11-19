# Capture agent

The Swift agent that macOS starts at login. For now it checks its
Accessibility grant on start and logs a heartbeat every minute.

| | |
|---|---|
| Bundle id | `io.github.thewisepup.computer-history.agent` |
| Installed at | `~/Applications/ComputerHistoryAgent.app` |
| Started by | `SMAppService`, from `Contents/Library/LaunchAgents/` inside the bundle (KeepAlive) |
| Signed with | `Computer History Code Signing` from the login keychain, hardened runtime |
| Logs | unified log, subsystem `io.github.thewisepup.computer-history.agent` |

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
"$agent" status      # Login item: enabled, starts at login.
"$agent" uninstall
"$agent" install     # exit 2 means approval is needed in System Settings > General > Login Items & Extensions
```

Running the binary with no arguments starts the agent in the foreground. From
a terminal, macOS checks the terminal's Accessibility grant, not the agent's,
so judge the grant only from the logs of the launchd-started agent.

## Window text

`WindowTextReader` reads the focused window of a `FocusedApplication` and
returns a `WindowText`: the window title, the content text, the full text
length in UTF-8 bytes, whether the text was cut off or the read timed out, and
the SHA-256 of the kept text. `focusedApplication(callTimeout:)` asks the
system-wide accessibility element for the focused app and falls back to
`NSWorkspace`. Nothing calls the reader yet.

| Role | Text taken |
|---|---|
| `AXStaticText`, `AXTextArea`, `AXTextField` | `AXValue`; children are read only when it is empty |
| `AXHeading`, `AXLink` | text of their children, else `AXTitle`, else `AXDescription` |
| `AXButton`, `AXPopUpButton`, `AXCheckBox`, `AXRadioButton` | nothing, children skipped |
| `AXSecureTextField` (role or subrole) | nothing, never read past its role |
| anything else (`AXWindow`, `AXGroup`, `AXRow`, ...) | nothing, children read |

Pieces are joined with newlines and cut at 50,000 bytes on a character
boundary; the walk keeps counting the full length past the cap. Each
accessibility call times out after 0.25s and the whole read after 2s; either
ends the read with the text collected so far. Electron apps and Chromium
browsers get `AXManualAccessibility` and `AXEnhancedUserInterface` set once
per process, unless their bundle id is on the off-list in
`WindowTextSettings`. A flag call that times out does not end the read; the
flags are tried again on the next read.

## Logs

`log` is a zsh builtin, so call `/usr/bin/log`:

```bash
/usr/bin/log stream --style compact --predicate 'subsystem == "io.github.thewisepup.computer-history.agent"'
/usr/bin/log show --last 1h --style compact --predicate 'subsystem == "io.github.thewisepup.computer-history.agent"'
launchctl print "gui/$(id -u)/io.github.thewisepup.computer-history.agent"
```

Expected lines: `started, accessibility granted` (or `missing, asked macOS to
prompt for it`), then `heartbeat, accessibility granted` every minute.

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
