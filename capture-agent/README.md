# Capture agent

The Swift agent that macOS starts at login. It checks its Accessibility grant
on start, readies the spool, then captures the focused window's text into the
spool whenever focus changes and every 30 seconds (by default) while the user is
at the Mac, with a screenshot of that window saved beside the database.

| | |
|---|---|
| Bundle id | `io.github.thewisepup.computer-history.agent` |
| Installed at | `~/Applications/ComputerHistoryAgent.app` |
| Started by | `SMAppService`, from `Contents/Library/LaunchAgents/` inside the bundle (KeepAlive) |
| Signed with | `Computer History Code Signing` from the login keychain, hardened runtime |
| Logs | unified log, subsystem `io.github.thewisepup.computer-history.agent`, five categories (see [Logs](#logs)) |
| Folder | `~/Library/Application Support/ComputerHistory/`, beside `history.db`, under the home folder in the user database |
| Spool | `spool/` in the folder |
| Instance lock | `agent-instance.lock` in the folder: one capturing agent per account |
| Screenshots | `screenshots/` in the folder |
| Config | `agent-config.json` in the folder, optional |
| Reminder | `screen-recording-reminded` in the folder: when the missing-grant reminder was last posted |

## Commands

Run these from `capture-agent/`.

```bash
scripts/test.sh        # swift test, with the Swift Testing paths Command Line Tools need
scripts/e2e.sh         # the end-to-end check: a scripted session through the spool into a temp database
scripts/build.sh       # build, wrap in .build/ComputerHistoryAgent.app, sign, verify
scripts/install.sh     # refuse unless the guard allows it, then build, replace the installed app,
                       # register the login item, check it runs, then ask for Screen Recording
                       # and open its settings pane unless granted (--force: install anyway)
scripts/uninstall.sh   # unregister the login item, stop the agent, delete the app
```

`install.sh` first runs `computer-history check-agent-install` from this
checkout's `.venv` (created on first use by `scripts/venv-python`), passing
its arguments on. The guard refuses unless the checkout is on `main`, clean
and at `origin/main`, the release gate's capture-agent checks passed on that
commit, and the stable backend is at that commit or newer; it lists every
unmet condition with its fix, and a refusal stops the script before the build
or the old agent's unregistering. `scripts/install.sh --force` installs anyway
and lists what it skipped. The conditions are in
`computer_history/cli/README.md` under check-agent-install.

With Xcode installed, plain `swift test` works too. Under Command Line Tools
alone it cannot find the `Testing` module, so use `scripts/test.sh`. CI runs
both scripts (`docs/agents/checks.md` says when); the pre-commit hook runs
neither, so run them after changing this folder, `fixtures/spool/` or the
end-to-end tests.

The installed binary takes the same commands directly:

```bash
agent=~/Applications/ComputerHistoryAgent.app/Contents/MacOS/computer-history-agent
"$agent" status        # Login item: enabled, starts at login. / Capture: not paused.
"$agent" pause         # stop capturing until resume, across restarts and reboots
"$agent" resume
"$agent" check-config  # where the settings came from, every problem, the settings in effect; exit 1 on problems
"$agent" request-screen-recording  # ask macOS for Screen Recording, open its settings pane unless granted; install.sh runs it
"$agent" uninstall
"$agent" install       # exit 2 means approval is needed in System Settings > General > Login Items & Extensions
```

None of these need the Accessibility grant, so they run from any terminal.

Running the binary with no arguments starts the agent in the foreground. From
a terminal, macOS checks the terminal's Accessibility grant, not the agent's,
so judge the grant only from the logs of the launchd-started agent.

## Folder and config

The capturing agent (`run`, or no arguments) and `status`, `pause` and
`resume` always use `~/Library/Application Support/ComputerHistory/`, with
`spool/` inside it, where `~` is the home folder the user database
(`getpwuid`) gives for the account. They ignore `$HOME`, `$CFFIXED_USER_HOME`,
`$COMPUTER_HISTORY_DB` and `$COMPUTER_HISTORY_SPOOL`, so a process that
starts the app with its own environment (`open -n --env ...`) gets an agent
that captures into the user's own folder, under the user's config and pause,
or, while the login item runs, one that exits at once (see the instance lock
under [Spool](#spool)).

`check-config` and `scripted-session` find the folder the way the backend
does: `$COMPUTER_HISTORY_DB` names the database and the folder is its parent;
otherwise the folder is the one above. `$COMPUTER_HISTORY_SPOOL` overrides the
spool, which otherwise is `spool/` in the folder. Empty values count as unset,
and `$HOME` and a leading `~` are honoured. Neither command reads the Mac, so
the end-to-end check points them at scratch folders. `check-config` also
prints `capturing agent folder, whatever the environment says: <folder>`, so a
shell with the variables set can see that `run` would not use them.

`agent-config.json` in the folder holds the settings. Every key is optional:

| Key | Default | Allowed |
|---|---|---|
| `denylist` | `[]` | bundle ids added to the built-in denylist |
| `accessibility_flag_off_list` | `[]` | bundle ids that never get the accessibility flags |
| `idle_threshold_seconds` | `180` | 10 to 86400 |
| `capture_heartbeat_seconds` | `30` | 5 to 60, so `status` can count on a record at least every minute |
| `text_cap_bytes` | `50000` | whole number, 1000 to 10000000 |
| `call_timeout_seconds` | `0.25` | 0.05 to 5 |
| `window_timeout_seconds` | `2` | 0.1 to 60 |
| `screenshots` | `true` | `true` or `false`; `false` takes no screenshots and writes no `screenshot` records |
| `screenshot_long_edge_pixels` | `1440` | whole number, 256 to 8192; larger images are scaled down to it, smaller ones kept as they are |
| `screenshot_jpeg_quality` | `60` | whole number, 1 to 100 |
| `screenshot_change_pixels` | `6` | whole number, 0 to 1000: a picture is a `duplicate` when fewer than this many of its thumbnail pixels (each 9x9 points of the window) changed from its window's last kept picture; `0` counts every picture as changed, which turns dedup off |
| `screenshot_keep_after_minutes` | `10` | whole number, 1 to 1440: an unchanged window gets a new `kept` picture once its last one is older than this |
| `watchdog` | none | an object the agent leaves alone: the backend's watchdog reads its thresholds from it (`computer_history/cli/README.md`, watchdog) |

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
no reads, not even the accessibility flags. A denylisted app counts as soon as
it is in front, even when it has not taken keyboard focus (a locked Passwords
window leaves focus with the previous app). While one is in front it writes an
`excluded` record, with the app name and bundle id and no title or text, on
the `app` trigger when it comes to the front and on every heartbeat while it
stays there. Window and title changes inside it go unnoticed.

An entry covers its own bundle id and every id under it, ignoring case:
`com.apple.Passwords` covers `com.apple.Passwords.MenuBarExtra`, the
Passwords menu-bar extra, but not `com.apple.PasswordsHelper`. The built-in
denylist:

| Entry | Covers |
|---|---|
| `com.1password` | 1Password 8 (`com.1password.1password`) and its helpers |
| `com.agilebits` | 1Password 7 and older (`com.agilebits.onepassword7`, ...) |
| `com.apple.keychainaccess` | Keychain Access |
| `com.apple.Passwords` | Passwords and its menu-bar extra |
| `com.bitwarden.desktop` | Bitwarden and `com.bitwarden.desktop.helper` |
| `com.dashlane` | any Dashlane app (Dashlane has no current Mac app) |
| `com.lastpass` | LastPass (`com.lastpass.LastPass`, `com.lastpass.lastpassmacdesktop`) |
| `in.sinew.Enpass-Desktop` | Enpass |
| `me.proton.pass` | Proton Pass (`me.proton.pass.electron`) |
| `org.keepassxc.keepassxc` | KeePassXC |

The config's `denylist` adds to it and cannot remove from it, so no config,
however wrong, captures one of these. A denylisted app never gets the
accessibility flags (see Window text), even when it is an Electron app.

## Private windows and password pages

Some windows of allowed apps are never read either: private browser windows
and password-manager pages. Before walking the focused window, the reader
takes its title and `AXDocument` (in Chromium browsers, the active tab's
address); while walking, it reads `AXURL` of every `AXWebArea` before its
contents. A match ends the read with nothing kept, and the agent writes an
`excluded` record, with the app name and bundle id and no title or text,
instead of the capture, and takes no screenshot. Title changes in the window
still trigger, so a private window yields `excluded` records on the same
triggers a capture would have.

| Browser | Bundle ids (and ids under them) | Private window title ends with |
|---|---|---|
| Chrome, Chromium | `com.google.Chrome`, `org.chromium.Chromium` | ` (Incognito)` |
| Brave | `com.brave.Browser` | ` (Private)` |
| Firefox | `org.mozilla.firefox`, `org.mozilla.firefoxdeveloperedition`, `org.mozilla.nightly` | `Private Browsing` or `(Private Browsing)` |
| Safari | `com.apple.Safari`, `com.apple.SafariTechnologyPreview` | `Private Browsing` |

Chromium on macOS gives the window the accessible title from
`BrowserView::GetAccessibleWindowTitle`, which ends with Chrome's
`IDS_ACCESSIBLE_INCOGNITO_WINDOW_TITLE_FORMAT` (`$1 (Incognito)`, Brave's
override `$1 (Private)`). Firefox on macOS titles a private window
`<page> — Private Browsing`. Safari ships the strings `Private Browsing`
(window title) and `%@, Private Browsing`. All of these are English: a Mac in
another language is not covered.

A page is a password-manager page when its address starts with
`chrome://password-manager`, `chrome://settings/passwords`,
`brave://password-manager`, `about:logins`, or `chrome-extension://<id>/`
for the Chrome Web Store ids of 1Password, 1Password Beta, Bitwarden,
LastPass, Dashlane, Proton Pass, Enpass and KeePassXC-Browser (popups,
vault pages and their inline menus, which are frames inside the page). Where
the address is not given, a Chrome window titled `Google Password Manager`
and a Firefox window titled `Passwords` count too.

A window of a Chromium browser (Chrome and its channels, Chromium, Brave, Edge, Arc,
Vivaldi and Opera)
whose read found no address at all, neither a non-empty `AXDocument` nor an
`AXURL` on a web area, is excluded as well: an extension popup gives no
`AXDocument`, and its page may not be in the tree yet (or ever, with the app
on `accessibility_flag_off_list`). Such a browser on the off list therefore
captures nothing.

Not covered yet, so captured as ordinary windows: Arc
(`company.thebrowser.Browser`), Edge (`com.microsoft.edgemac`), Vivaldi and
Opera private windows; Brave's private windows with Tor; Chrome guest
windows; extension popups in Safari and Firefox, whose addresses carry a
per-install id; and Edge's password pages. None of the title formats has been
checked against a running browser on a Mac yet.

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
length in UTF-8 bytes, whether the read timed out, and whether the window is
excluded (see Private windows and password pages). The `SpoolRecord` made
from it derives the text's SHA-256 and whether it was cut off, for the spool
line and the minute log line alike. `focusedApplication()` asks the
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
`AXEnhancedUserInterface` set once per launch (process id, app bundle and
launch time, so a reused process id gets them again), unless they are
denylisted or their bundle id is on the config's `accessibility_flag_off_list`
(ignoring case). A flag call that
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

## Sleep and wake

The `willSleep` notification writes a `slept` record at that moment, on the
main thread and before the handler returns, so it is in `open.part` before
the Mac sleeps. `didWake`, or the first input after `willSleep` should
`didWake` not have come yet, writes one `woke` record on the main thread, but
only after a sleep that wrote a `slept` record; the Mac counts as asleep until
that record is written. Neither is written while capture is paused, since the
pause already explains the time; a failed write is counted with the other
failed writes. Window text records are written one at a time, and a capture
or excluded record is written only if the Mac is still awake at that moment,
so none lands after the `slept` record, whenever it was read. Once the capture
loop stops, sleep and wake write nothing. A lost `didWake` (a crash or power
loss) leaves no `woke` record; the backend ends the sleep at the next record
or where `aw-afk` next shows you active. The scripted Mac sends both
notifications when a script's `presence` changes `asleep`, and reports asleep
while it sends `didWake`, as macOS does.

Update the backend before installing an agent that writes these records: an
older backend counts `slept` and `woke` lines as unusable and sets their files
aside in `spool/unreadable/` after storing the other records, so those lines
are kept but never stored.

## Screenshots

Right after each `capture` record is written, the capture thread takes its
screenshot and queues one `screenshot` record for it (see Text recognition).
`excluded`, `paused`, `resumed`, `slept` and `woke` records get none, and a capture record that
could not be written gets none.

Before the picture it checks again that capture is not paused, the user is
not idle, locked or asleep, and the same app and window title are still in
front; the window-text read can take up to the window timeout. If anything
changed, or a check gets no answer, the record says `failed` and no picture
is taken.

| Status | When |
|---|---|
| `secure-field` | the focused app's `AXFocusedUIElement` has role or subrole `AXSecureTextField`; no picture is taken |
| `kept` | the picture was taken and saved |
| `duplicate` | fewer than `screenshot_change_pixels` of the picture's thumbnail pixels changed from its window's last kept picture, which is at most `screenshot_keep_after_minutes` old; nothing is saved |
| `no-permission` | ScreenCaptureKit refused with `userDeclined`: the Screen Recording grant is missing |
| `failed` | anything else: focus or presence changed during the read, the password-field check got no answer, the window's frame could not be read or matched, another ScreenCaptureKit error, no answer within 2 seconds, an earlier request still unanswered, or the image could not be saved |

The password-field check fails closed: a timeout reading the focused element,
its role or its subrole, or a focused element with no role, gives `failed`.
An app that reports no focused element at all is photographed.

The picture is a ScreenCaptureKit still of one window: the on-screen window of
the focused app whose frame matches the accessibility frame of its focused
window (within 2 points), so a focused floating panel is photographed rather
than the main window behind it. The title only chooses among windows with the
same frame; when no single window matches, nothing is taken. ScreenCaptureKit
is asked for the window scaled so its long edge is at most
`screenshot_long_edge_pixels`, never above its native size. Only one request
is outstanding at a time: while one has not answered, later captures get
`failed` at once instead of waiting.

The image is encoded as JPEG at `screenshot_jpeg_quality` and saved as
`screenshots/<local yyyy-MM-dd>/<record id>.jpg` in the folder. The folders
are `0700`, set again on every save, and the images `0600`. Nothing is ever
deleted: an image whose record the spool refuses, or whose record a crash or
a stop cut off, stays.

Each picture is shrunk to a grey thumbnail with one pixel per 9x9 points of
the window (the window's frame, not the picture's pixels), so a line of text
covers about as many thumbnail pixels in a small window as in a maximized one
on a wide display. The thumbnail is at most 640 pixels on its long edge and
never has more pixels than the picture; each pixel is the average brightness
of the block it covers. It is compared with the thumbnail of the last kept
picture of the same window: a pixel has changed when its brightness differs by
more than 24 of 255, which absorbs JPEG and scaling noise, and the picture has
changed when at least `screenshot_change_pixels` pixels have, which lets a
blinking caret through but not a typed line. A thumbnail of another size (a
resized window) is a change, and so is a match whose kept picture is older
than `screenshot_keep_after_minutes`, or dated after the new picture (the
clock was set back). A window is
the ScreenCaptureKit window id of the window photographed plus its title, so
two windows of one app with the same title are told apart and each browser
tab or editor file still counts on its own. The agent remembers the last kept
picture of a fixed number of most recently seen windows (`ScreenshotDedup.windows`),
in memory only, so a restart starts over. A window whose title changes is a
new window: its first picture is kept, and the old title is still remembered
until it ages out. A `duplicate` record carries the kept record's image path and
recognized text, its own picture's hash, and no image size. A kept image
whose record the spool refuses is still remembered, so its duplicates point
at it.

Each picture's `perceptual_hash` is a 64-bit difference hash: each bit says
whether a pixel of a 9x8 grey thumbnail is brighter than its right neighbour.
It is recorded for later measurement and decides nothing.

### Text recognition

Screenshot records go through one first-in, first-out queue, `ScreenshotQueue`,
with no length limit, on a thread of its own, so the capture thread never waits for
recognition. The image is saved before its record is queued; the queue holds
the record and the image's path, never the picture. Every screenshot record
goes through it, whatever its status, so a capture's screenshot record reaches
the spool after its capture record, in capture order, with the capture's time,
possibly after later `capture`, `paused`, `resumed`, `slept` or `woke` records.

For a `kept` record the queue reads the text in the saved JPEG with Vision:
accurate mode, English (`en-US`), language correction on, one line per
recognized line in the order Vision returns them, no positions or confidence.
The text is cut like window text, at `WindowTextSettings.textCapBytes` (50 KB),
with `full_text_bytes`, `text_cut_off` and `text_sha256`. A `duplicate` record
waits its turn behind its kept record and copies that record's finished text;
no recognition runs for it. If Vision fails, the record is still `kept`, with
empty text (`full_text_bytes` 0) and its image, its duplicates copy the empty
text, and the minute log line counts the failure. The window's next picture
is then kept and read again rather than matched against the image with no
text; duplicates queued before the failure was known still copy the empty text.
That retry happens once: if its text cannot be read either, later pictures of
the window are matched against it as usual and copy its empty text until the
keep-after limit, so a static window whose text is never read saves at most two
images per limit.

Vision runs on a thread of its own and gets `ScreenshotSettings.recognitionTimeout`
(10 seconds) per image; with no answer by then the record is `kept` with empty
text and counted as a failed recognition, so a hung Vision call delays the queue
once, not forever. Only one Vision call runs at a time: while a timed-out call
has still not returned, later kept images get empty text at once, without
starting another.

On `SIGTERM` (launchd stops the login item at every logout, and on
`launchctl` stop or uninstall) the agent stops taking captures, gives the queue
until 5 seconds after the signal (`AgentLifecycle.stopDrainSeconds`) to write
what it can, then writes no more screenshot records, finishes the open spool
file, logs `stopping, N screenshot records dropped` and exits. A capture tick
still running when the signal comes finishes first and eats into those 5
seconds; if the capture thread has not finished a second after them, the agent
logs `stopping, the capture thread did not finish in time` and exits anyway.
launchd waits 20 seconds before `SIGKILL`. The dropped records are lost and
their images stay. A crash or `SIGKILL` loses everything queued the same way.
A record is written as one line under the spool's lock and the queue writes
nothing once stopped, and a torn last line is dropped on the next start (see
Spool), so no stop can leave a broken record for the backend. `pause` stops
new captures but not the queue: records of captures taken before the pause
are still written, after the `paused` record. The scripted session waits for
the queue to empty before it ends, with or without a crash.

### Screen Recording permission

`scripts/install.sh` asks for the grant once per install: it launches the
installed app through `open -n -W ... --args request-screen-recording`, so
macOS asks on behalf of the agent rather than the terminal. That command calls
`CGRequestScreenCaptureAccess` and, unless that reports the grant held, opens
the Screen Recording settings pane. Turn on Computer History Agent there.
That answer only decides whether the pane opens. The agent never trusts
`CGPreflightScreenCaptureAccess`, which can stay stale for the life of the
process: a picture taken is the evidence the grant is held, and a
`no-permission` record is the evidence it is missing. Until it is granted,
window text capture carries on.

When a screenshot comes back `no-permission`, the agent posts one notification
whose click opens the settings pane, trying
`x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension?Privacy_ScreenCapture`
first and `x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture`
if that does not open. While the grant stays missing it tries again at most
once every 24 hours, or at once if the clock was set back by more than that.
The time of the last notification actually posted is kept in
`screen-recording-reminded` in the folder, so a restart keeps the 24 hours.
When macOS first asks whether the agent may post notifications, the
notification is posted once the user allows them, and the time of that try is
saved then, from the notification centre's thread. A try that posted nothing
(the user declined or has not answered yet, a notification centre that did not
answer within 2 seconds, notifications turned off, or the agent not running
from its app bundle) waits the 24 hours only within that run, and a restart
tries again. Any picture taken (`kept` or
`duplicate`) deletes the file, and a later loss reminds at once. With
notifications off, `status` is the only warning.

`CaptureSettings` holds the idle threshold, heartbeat interval, settle delay,
minimum gap and poll interval; the first two come from the config. An agent
that finds the instance lock or the spool held by another agent exits without
capturing.

## Scripted sessions and the end-to-end check

Everything the capture loop asks of the Mac is one protocol, `Mac`: the
clocks, presence, the Accessibility grant, the focused app and its
accessibility tree with each window's frame, a picture of the focused
window, and posting a notification. `LiveMac` answers from macOS;
`ScriptedMac` answers from a script on a virtual clock, with scripted
accessibility elements and a striped 1600x1000 fixture image for every
picture, so the real `CaptureLoop`, `CaptureDecision`, `AppWatch`,
`WindowWatch`, `WindowWalk` and `SpoolWriter` run unchanged on top of it. The
unit tests use `ScriptedMac` too. Text recognition is passed to the capture
loop beside the image store: `main.swift`, the only place that picks
`LiveMac`, passes Vision; a scripted session passes `ScriptedImageStore`'s
scripted text, and the unit tests give empty text unless a test sets it.

```bash
COMPUTER_HISTORY_DB=/tmp/scratch/history.db .build/debug/computer-history-agent scripted-session e2e/session.json
```

`scripted-session <script.json>` plays a script against the folder and spool
the environment names, then exits: no Accessibility grant, no login item, no
real time. It refuses to run when the folder or the spool is in, or links
into, `~/Library/Application Support/ComputerHistory/`, or when the folder
already holds a `*.db` file, so it needs `COMPUTER_HISTORY_DB` (and
`COMPUTER_HISTORY_SPOOL`, if set) to point into an empty scratch folder. It finishes the open spool file every virtual minute and at the
end, and prints the capture counts and the accessibility calls each app got.

A script is JSON: `start` (UTC ISO-8601 with milliseconds), `apps` by id (each
with `name`, `bundle_id`, `focused_window` and `windows` by id), and `steps`
in time order, each `at` seconds after the start with exactly one action:

| Action | Effect |
|---|---|
| `"focus": "<app>"` | that app comes to the front |
| `"focus_window": {"app": ..., "window": ...}` | the app's focused window changes |
| `"set_title": {"app": ..., "window": ..., "title": ...}` | the window's title changes |
| `"focus_element": {"app": ..., "window": ..., "element": ...}` | the app's focused element becomes the element with that `id` in that window; `{"app": ...}` alone clears it |
| `"window_image": "picture" \| "no-permission" \| "failed"` | what a picture of the focused window gives from now on: the fixture image (the start), a missing grant, or a failure |
| `"presence": {"idle_seconds": ..., "locked": ..., "asleep": ...}` | presence; missing keys are 0 or false; a change of `asleep` sends the will-sleep or did-wake notification |
| `"pause": true`, `"resume": true` | creates or deletes `capture-paused`, as the commands do |
| `"end": true` | finishes the open spool file and exits |
| `"crash": true` | exits leaving `open.part` unfinished, as a crash would |

A window is an element: `role`, and optionally `id` (unique in its window,
for `focus_element`), `title`, `subrole`, `description`, `value` (repeated
`repeat` times), `document` (`AXDocument`), `url` (`AXURL`), `hangs`
(attributes whose calls time out) and `children`. A
window may also set `recognized_text`: the text the scripted recognition reads
from each picture kept of it (otherwise empty).

`scripts/e2e.sh` builds the agent and runs `tests/e2e/test_capture_e2e.py`. It
plays `e2e/crash.json`, appends a torn line to the leftover `open.part`, plays
`e2e/session.json`, then runs the real `computer-history ingest` three times
(twice, then once more with the finished files put back) and `status` against
a temporary database, with a stand-in ActivityWatch that has no buckets, and
checks the stored records and signals against the scripts. The session's nine
captures give every screenshot status: `kept` with scripted recognized text,
`secure-field` on a focused password field, `failed` from a refused picture, a
`duplicate` copying its kept record's text, and two `no-permission` records
that post one reminder and leave `status` warning. The test checks the images
on disk, the stored records and their signals (a `rebuild-signals` included),
the reminder's saved time, and every line of the screenshots section in
`status`. The backend runs with the screenshots folder closed to it (mode
`000`), and the images must come out byte for byte the same. It also checks
that the agent's `check-config` and the backend name the same default folder
and spool for a scratch home folder, and that with `$HOME`,
`$CFFIXED_USER_HOME` and both overrides pointing at a scratch folder it still
names the account's real folder as the capturing agent's. It also runs the agent test in
`tests/data/test_synthetic_spool.py`, which plays a synthetic developer day through `scripted-session` and checks the
synthetic spool renderer writes the same captures (time, trigger, app, bundle
id and title) as the agent.
Plain `pytest` skips both agent tests unless `CAPTURE_AGENT_BINARY` names a built agent.

## Logs

The agent writes to the unified log under the subsystem
`io.github.thewisepup.computer-history.agent`, in five categories:

| Category | Carries |
|---|---|
| `lifecycle` | start, a start refused for the instance lock, the config report, the paused state at start, the minute heartbeat, stop |
| `capture` | silence starting, changing and ending; one debug record per capture written |
| `spool` | spool ready, a leftover file finished, failures to start or finish the spool |
| `screenshots` | each try of the missing Screen Recording grant reminder |
| `ocr` | one debug record per text recognition that failed or got no answer in time |

| Level | Records |
|---|---|
| `error` | the spool failing to start or finish a file, the reminder time not saved |
| `notice` | start, the config report, the paused state, the minute heartbeat, stop, each reminder try |
| `info` | silence changes, spool ready, a leftover file finished |
| `debug` | each capture (bundle id, trigger, text bytes, private window title), each failed recognition |

macOS keeps `notice` and `error` on disk. `info` stays in memory and reaches
disk only when an error flushes it, and `debug` is collected only while a
`log stream --level debug` runs. To keep `info` on disk, for `log show
--info` an hour later: `sudo log config --subsystem
io.github.thewisepup.computer-history.agent --mode persist:info`.

Window titles, window text and recognized text never go in a message. The
capture debug record carries the window title as a private argument, which
the log shows as `<private>` unless a configuration profile enables private
data for the subsystem. Bundle ids, counts, paths and error descriptions are
public. `scripted-session` prints each message to stdout instead, without the
private argument.

`log` is a zsh builtin, so call `/usr/bin/log`:

```bash
/usr/bin/log stream --style compact --predicate 'subsystem == "io.github.thewisepup.computer-history.agent"'
/usr/bin/log stream --style compact --level debug --predicate 'subsystem == "io.github.thewisepup.computer-history.agent" && category == "capture"'
/usr/bin/log show --last 1h --style compact --info --predicate 'subsystem == "io.github.thewisepup.computer-history.agent" && category == "spool"'
/usr/bin/log show --last 1d --style compact --predicate 'subsystem == "io.github.thewisepup.computer-history.agent" && logType == "error"'
launchctl print "gui/$(id -u)/io.github.thewisepup.computer-history.agent"
```

Expected lines: `started, accessibility granted` (or `missing, asked macOS to
prompt for it`), `config read from <path>, 10 apps denylisted` (or `config not
found at <path>, using defaults, ...`) followed by any `config problem: ...`,
`capture is paused, ...` when it is, `spool ready at <folder>`, then every
minute `heartbeat, accessibility granted, last minute: 12 captures written, 3
excluded, 1 timed out, 0 cut off, slowest read 0.42s, 2 screenshot records
queued` (records waiting on the queue at that moment), with `, 2 failed to
write (last: <error>)`, `, 1 screenshot records failed to write (last:
<error>)` and `, 1 text recognitions failed (last: <error>)` appended when
writes or recognitions fail, each only when its count is not zero and each
with the last error of its own kind. `silent: paused`, `silent:
idle`, `silent: locked, asleep` and `capturing again` mark silence starting,
changing and ending. Each reminder try logs one of `screen recording missing,
posted a reminder`, `..., asked macOS to allow notifications for the
reminder`, `..., the notification centre did not answer within 2s`, or, once
per run, `..., notifications unavailable (<reason>), status is the only
warning`. `could not save the reminder time to <path> (<error>), a restart may
remind again` appears at most once per run. After a crash, start also logs
`spool finished leftover file <name>`. At debug, each capture logs `captured
com.apple.TextEdit on heartbeat, 1832 text bytes <private>` and each failed
recognition `text recognition failed for <image>.jpg: <error>`.

## Spool

The agent appends one JSON record per line to `open.part` in the spool
folder. Every minute, if `open.part` is non-empty, it is renamed to a
finished file and the next record starts a new `open.part`. A leftover
`open.part` from a crash is finished the same way on start. A torn last line
is dropped before the rename, and the rename is atomic, so the backend, which
reads only `*.jsonl`, never sees a partial file. A leftover `open.part` that a
failed start left behind has its torn last line dropped before the next
record, and if `open.part` is removed while open, the next record starts a new
one.

Finished files are named `<yyyyMMdd'T'HHmmss.SSS'Z'>.jsonl` in UTC, for
example `20261118T090100.000Z.jsonl`. Each name is at least one millisecond
after every name the running agent has used and the newest name in the folder
when it started, so two finishes in the same millisecond, a leftover file
finished at start, or a clock that steps back never produce a name that sorts
out of order or replaces a file. The rename refuses to overwrite.

Only the owner can read the spool: the folder is `0700` and `open.part`,
the finished files and `agent.lock` are `0600`. On start the agent tightens a
folder, lock file or leftover `open.part` that is more open than that, and
carries on as before when it is not allowed to.

A capturing agent first takes `agent-instance.lock` in the folder (`0600`,
in a folder it creates `0700`), then `agent.lock` in the spool folder, and
holds both while it runs. A second agent cannot take the instance lock: it
logs only `instance lock not taken at <file>: another agent holds <file>,
exiting`, asks for no Accessibility prompt, and exits with status 1 without
opening the spool. One that gets past it but finds the spool held logs only
`spool failed to start at <folder>: another agent is writing to <folder>,
exiting` and exits the same way. launchd starts its own agent again, every 10
seconds or so, until the locks are free. A scripted session takes only the
spool's lock, so it can run while the login item does.

A capture, exclusion, pause, resume, slept or woke record has every key below, sorted,
with `null` where a key does not apply:

| Key | Value |
|---|---|
| `version` | format version, `1` |
| `id` | lowercase UUID; becomes the observation's `source_id` |
| `captured_at` | UTC ISO-8601 with milliseconds, `2026-11-18T09:00:05.250Z` |
| `kind` | `capture`, `excluded`, `paused`, `resumed`, `slept` or `woke` |
| `trigger` | `app`, `window`, `title` or `heartbeat`; `null` for `paused`, `resumed`, `slept` and `woke` |
| `app_name` | the focused app; `null` for `paused`, `resumed`, `slept` and `woke` |
| `bundle_id` | the focused app's bundle id, or `null` |
| `window_title` | `capture` only |
| `text` | `capture` only: the window's text, possibly cut off or partial |
| `text_sha256` | `capture` only: lowercase hex SHA-256 of `text` as UTF-8 |
| `full_text_bytes` | `capture` only: UTF-8 length of all text read, before any cut |
| `text_cut_off` | `capture` only: `true` when `text` is shorter than the full text |
| `timed_out` | `capture` only: `true` when reading stopped at a timeout and the text is partial |

A `screenshot` record (`ScreenshotRecord`) tells what became of the
screenshot taken with one capture (see Screenshots). It has
every key below, sorted, with `null` where a key does not apply:

| Key | Value |
|---|---|
| `version` | format version, `1` |
| `id` | lowercase UUID of this record; becomes the observation's `source_id` |
| `kind` | `screenshot` |
| `capture_id` | the `id` of the capture it belongs to |
| `captured_at` | the capture's time |
| `status` | `kept`, `duplicate`, `secure-field`, `no-permission` or `failed` |
| `app_name`, `bundle_id`, `window_title` | the capture's |
| `image_path` | `kept` and `duplicate`: the JPEG's path relative to the folder (for `duplicate`, the kept image it matched) |
| `image_bytes` | `kept` only: the JPEG's size |
| `perceptual_hash` | `kept` and `duplicate`: the screenshot's own hash |
| `text` | `kept` and `duplicate`: the recognized text, possibly cut off (for `duplicate`, the kept record's) |
| `text_sha256`, `full_text_bytes`, `text_cut_off` | as for a capture, of the recognized text |

[`fixtures/spool/records.jsonl`](../fixtures/spool/records.jsonl) holds one
example of every kind, trigger and screenshot status. It is the contract with the backend: the
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
