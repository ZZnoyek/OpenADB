#!/usr/bin/env python3
"""phone.py - adb driver to control a phone and SEE it.

Run with -help for the full AI-facing usage guide, or 'help <command>'
for per-command help.
"""
import json
import re
import shlex
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

SHOTS = Path.home() / "Pictures"
SHOTS.mkdir(exist_ok=True)
VIDS = Path.home() / "Videos"
VIDS.mkdir(exist_ok=True)
BRAVE = "com.brave.browser/com.google.android.apps.chrome.Main"

APP_NAMES = {
    "com.whatsapp": "WhatsApp",
    "com.whatsapp.w4b": "WhatsApp Business",
    "com.brave.browser": "Brave",
    "com.google.android.youtube": "YouTube",
    "com.google.android.apps.youtube.music": "YouTube Music",
    "com.sec.android.app.launcher": "Home screen",
    "com.samsung.android.lool": "Device care",
    "com.samsung.android.settings": "Settings",
    "com.android.settings": "Settings",
    "com.discord": "Discord",
    "com.microsoft.teams": "Microsoft Teams",
    "com.anthropic.claude": "Claude",
    "com.google.android.gm": "Gmail",
    "com.google.android.apps.maps": "Maps",
    "com.google.android.apps.photos": "Photos",
    "com.sec.android.gallery3d": "Gallery",
    "com.sec.android.app.camera": "Camera",
    "com.android.chrome": "Chrome",
}

HELP = f"""\
openadb - adb driver to control a phone and SEE it.

You (the AI) are driving a real Android phone over adb. This is not a
simulation: taps tap, typed text is typed, force-stop kills the app for
real. There is no undo. Default device size: 1080x2340 portrait (actual
size is read from the device at runtime, so trust `who`/`status` over
this number if they disagree).

HOW THIS TOOL "SEES" THE SCREEN (read this first)
  There is no camera and no pixel-level vision model behind this tool.
  "Sight" is built from two independent sources that are merged together:
    1. UI TREE (uiautomator dump) - the accessibility tree Android itself
       uses. Gives exact element bounds, text, content-desc, class,
       resource-id, and state (checked/enabled/scrollable/focused).
       Fast and pixel-accurate when it works.
    2. OCR (tesseract on a real screenshot) - reads pixels as text with
       coordinates. This is the *only* source of truth for canvas-drawn
       UI, game engines, video content, and some custom-rendered web
       apps where the UI tree is empty or a single opaque WebView blob.
  `sight` merges both. If OCR is unavailable (tesseract not installed)
  the EYES section is simply omitted - everything else still works.

  Icon-only controls (a plain back-arrow, hamburger menu, or toggle
  switch with no text and no content-desc) are NOT invisible: small
  native clickable controls (ImageButton/Switch/CheckBox/etc under ~20%
  of screen area) are surfaced as `icon:<resource-id-or-class>`, e.g.
  `icon:menu_btn`. You can `tap icon:menu_btn` or often just
  `tap menu_btn` (word-boundary matching strips the "icon:" prefix
  automatically). Large unlabeled clickable containers are NOT surfaced
  this way (too noisy / usually not the real tap target) - use raw
  coordinates or `shot` if you truly can't identify one.

LOOK
  sight     main "look": app, page, keyboard state, AT A GLANCE (top
            bar / body / bottom bar, like a human's first glance),
            LAYOUT (top->bottom, left->right reading order), TAP
            TARGETS, EYES (OCR). Use 'sight --brief' for a cheap
            one-line version when you just need to check something
            small, or 'sight --json' for a structured machine-readable
            dump (app, page, elements with bounds, focused field, OCR).
  ui        raw element list with exact bounds:   ui [filter]
  find      grep the screen for a label (UI tree only, no OCR): find Search
  ocr       read pixels as text + coords directly: ocr [filter]
  shot      screenshot -> saved + opened on your laptop (for a human,
            or for you if you have vision - text-only agents want
            'sight' instead).
  notify    list current notifications (title, text, source app).
  top       focused app + current activity stack summary.

ACT
  tap       tap X Y  OR  tap "text"  (matches UI text/content-desc/icon
            label, exact match first then prefix then whole-word, OCR
            fallback if no UI element matches at all). Options: --wait N
            (poll up to Ns for the target to appear), --index N (pick the
            Nth match, indices match `ui`), --force (bypass the web-target
            refusal).
  longtap   long-press ~800ms:  longtap X Y  OR  longtap "text"
  doubletap double-tap (zoom, like):  doubletap X Y  OR  doubletap "text"
  swipe     swipe [left|right|up|down | X1 Y1 X2 Y2 | "elem" <dir> |
            "from" "to"] [ms] - full-screen drags are orientation-aware;
            "elem" <dir> swipes inside one element's bounds (scroll one
            pane); "from" "to" drags between two elements.
  scroll    REAL scroll (not a swipe): flings content like a human flicking
            a list - momentum scrolling. scroll [times] [up|down]  (down =
            reveal content below). scroll "elem" [times] [up|down]  scroll
            inside a specific panel. --drag for a slow, precise controlled
            scroll instead of a fling.
  text      type into the focused field:  text "hello world"
            SAFE TYPING (use when precision matters):
              text "hi" --field "Message"   tap the right field, then type
              text "hi" --check "Message"   refuse to type unless that exact
                  field is focused (catches wrong-field typos before they
                  happen - exit 1 on mismatch)
              --clear  empty the field first   --verify  confirm text landed
              --enter  submit (press Enter):  text "query" --enter
            `sight` reports the FOCUSED FIELD so you know where text will
            land before you send it.
  key       key <home|back|recents|power|volup|voldown|enter|tab|del|
            play|pause|next|prev|...>  (full list: `key` with no arg)
  open      open URL in Brave, or launch an app by human name, exact
            package, or fuzzy match:  open whatsapp | open com.discord
  close     force-stop an app (kills it, no confirmation):  close com.whatsapp
  uninstall uninstall an app:  uninstall whatsapp
  clear     wipe an app's data (logs out, resets to first-run):  clear whatsapp
  run       execute a script of commands from a file, one per line
            (blank/# lines skipped, stops on first failure):  run steps.txt
  clipboard get clipboard text (best-effort, not supported on all
            devices/Android versions):  clip
  push      push <local-file> <device-path>  (copy a file TO the phone)
  pull      pull <device-path> [local-path]  (copy a file OFF the phone)
  ls        ls [path]  (list files on the phone, default /sdcard)

DEVICE
  status    online / battery / screen size / focused app.
  state     compact overview: battery, screen power state, LOCK STATE,
            volume, orientation, DND, wifi, bluetooth, focused app.
            Cheapest single call to re-establish context after a gap.
            'state --json' for the same as structured JSON.
  who       device manufacturer, model, Android version, SDK.
  battery   detailed battery stats (charging/discharging/temp/voltage).
  ping      is the device reachable + adb round-trip latency.
  apps      installed user apps:   apps [filter]   (--all for system too)
  info      app details:  info <package>  (version, install/update time)
  signal    network type (lte/5g/wifi) + signal strength.
  storage   free space on /data, /sdcard, /system.
  mem       RAM total + available.      (ram alias)
  cpu       top processes by CPU right now.
  time      phone's current clock time.
  dpi       display density (read-only - do not try to change it, it
            will break every coordinate this tool reports).
  volume    volume [up|down|mute|unmute|set N|get]  (media stream)
  brightness brightness [N 0-255|up|down|max|min|auto|state]
  screen    screen [on|off|state]   (power state, not lock state)
  wake      wake the screen (does NOT dismiss the lock screen - use
            'unlock' for that).
  lock      turn screen off / lock the device.
  unlock    wake + swipe + dismiss keyguard, THEN VERIFIES it actually
            worked before saying so - see UNLOCK below, read this before
            assuming a locked phone is a dead end.
  orient    orient [portrait|landscape|auto]
  dnd       dnd [on|off|state]
  airplane  airplane [on|off]
  wifi      wifi [on|off|state]
  bluetooth bluetooth [on|off|state]   (bt alias)
  data      mobile data [on|off|state]
  record    record screen video:   record [seconds]   (default 5s)
  wait      wait <seconds> | wait --until <text> [--timeout N]
  cmd       raw adb shell, for anything not covered above:
            cmd dumpsys battery / cmd pm list packages

CHECK
  verify    verify <text> - exit 0 if the text is on screen (UI tree or
            OCR), exit 1 if not. Use this to assert state in a script,
            not just to look.

UNLOCK - READ THIS IF THE PHONE IS LOCKED
  `unlock` wakes the screen, swipes up (dismisses a basic swipe-only
  lock screen), then calls the keyguard-dismiss API, then CHECKS the
  actual lock state and reports one of three real outcomes:
    "unlocked"                 -> it worked, proceed.
    "still locked: ... PIN/pattern/password" (exit code 1)
                                -> the device has a real secure lock.
       adb CANNOT bypass a PIN/pattern/password without the credential -
       this is an OS security boundary, not a bug in this tool, and
       there is no flag or workaround that changes that. If you know
       the PIN, drive the on-screen keypad with `tap`/`key` digits or
       `text "1234" --enter`. If you don't, tell the human it needs
       manual unlock.
    "unlock attempted (couldn't confirm lock state ...)"
                                -> lock-state detection didn't recognize
       this Android version's fields. Follow up with `sight` and judge
       from what's actually on screen.
  `sight` and `state` both surface current lock state up front, so you
  don't waste turns interpreting lock-screen elements as app content.

AI WORKFLOW
  1. sight                  # look first, every time - don't assume
  2. tap "Like"              # act on what you actually saw
  3. sight                   # confirm the action landed
  Faster: append --sight to any ACTING command to auto-confirm in one
  round-trip:  tap "X" --sight   text "hi" --enter --sight
  (read-only commands like sight/ui/status/apps ignore --sight, since
  there's nothing to confirm after a look.)
  --sight also DIFFS the screen before vs after your action and prints a
  ===== CHANGED ===== section: what appeared (+), disappeared (-), flipped
  state (~ checked/unchecked/enabled/disabled), or APP CHANGED. If nothing
  changed it says so explicitly - that means the tap probably missed, the
  app hasn't responded yet, or you need to `wait --until` for something
  slower to load. Don't compare two full dumps by eye.
  Cheaper: sight --brief for a one-line summary when you just need a
  sanity check, not the full picture.
  Assert instead of guessing timing:  wait --until "page loaded"
  then verify "Save".  Don't chain sleep() and hope - poll for the
  actual text you're waiting on.
  Shortcuts: home / back / recents / rotate / screenshot / type / bt /
  url / sleep / ram / screencap.

RELIABILITY / HOW TAP RESOLUTION ACTUALLY WORKS
  - Match order for `tap "text"`: exact match (case-insensitive) beats
    prefix/truncated match beats whole-word-inside-longer-string match.
    Ties are broken toward clickable, non-web elements. If several
    elements share the label, `--index N` picks one (indices match `ui`).
  - If the target may not be on screen yet (loading), `tap ... --wait 5`
    polls the UI until it appears instead of failing on the first frame.
  - Very short ambiguous queries (<3 chars) that don't hit an exact
    match are REFUSED with a candidate list rather than guessing wrong
    - re-issue with more of the label, or use raw coordinates.
  - [x@y] marks a native tap target, {{x@y}} marks a web tap target,
    (text) is native non-clickable text, 'text' is web non-clickable
    text. 'web?' in TAP TARGETS means the web element's coordinates are
    NOT confirmed against the actual rendered pixels (OCR doesn't see
    it there) - tap refuses these unless you force it with raw
    coordinates, because tapping blind on unconfirmed web coordinates
    is how you end up tapping the wrong thing on a scrolled/dynamic page.
  - Giant invisible/oversized web containers are never reported as a
    single button (would swallow every tap on the page).
  - If `tap` says NOT FOUND: the label genuinely isn't on screen right
    now (wrong screen, needs a scroll, or OCR/tesseract isn't
    installed) - run `sight` to see what actually is there before
    retrying with different wording.
  - Use `shot` to look at the real screen yourself whenever something
    isn't adding up - it's the ground truth this whole tool is inferring
    from.

Per-command help:  openadb help <command>
"""

CMD_HELP = {
    "ui": """\
ui [filter] - raw element list with exact bounds.
Each: [index]* 'label' [x1,y1][x2,y2] <Class> resource-id  (* = clickable)""",
    "find": """\
find <text> - grep the screen for a label (same as 'ui <text>').""",
    "tap": """\
tap X Y        tap exact coordinates.
tap "text"     tap the on-screen element containing "text".
               Exact match first, then truncated/word match; OCR fallback.
               Refuses ambiguous short queries and unconfirmed web phantoms.
Options:  --wait N     poll up to N seconds for the target to appear, then tap.
          --index N    pick the Nth match (indices match the `ui` listing)
                       when several elements share a label.
          --force      bypass the unconfirmed-web-target refusal.
Exit code 1 with NOT FOUND / REFUSED if it won't tap.""",
    "longtap": """\
longtap X Y | longtap "text" - press and hold ~800ms (right-click, press menus).
Accepts the same --wait/--index/--force options as tap.""",
    "doubletap": """\
doubletap X Y | doubletap "text" - two quick taps (zoom, like).
Accepts the same --wait/--index/--force options as tap.""",
    "swipe": """\
swipe [left|right|up|down | X1 Y1 X2 Y2 | "elem" <dir> | "from" "to"] [ms]
  left|right|up|down - full-screen, orientation-aware drag.
  X1 Y1 X2 Y2        - raw coordinate drag.       [ms] defaults 150.
  "elem" up          - swipe INSIDE one element's bounds (scroll a single pane).
  "from" "to"        - drag from one element to another (drag-and-drop).""",
    "scroll": """\
scroll [times] [up|down] - REALLY scroll content (a fling with momentum,
like flicking a list), NOT a swipe. down = reveal content below.
scroll "elem" [times] [up|down] - scroll inside a specific element/panel.
--drag  slow, precise controlled scroll (content follows the finger).
--fling fast momentum scroll (default).
Orientation-aware.""",
    "text": """\
text "<string>" - type into the focused field. Quoted safely, so spaces
and special characters (! : ) etc.) work.
Options:
  --field "<label>"  tap the field with that label first, then type into it
                     (never type into the wrong field by accident).
  --check "<label>"  REFUSE to type unless the currently focused field
                     matches <label> - catches the "typed into the note
                     editor instead of the chat box" failure before it
                     happens. Exit code 1 on mismatch.
  --clear            select-all + delete existing text before typing.
  --verify           re-read the field afterwards and confirm the text landed.
  --enter            submit (press Enter) after typing.
Example: text "hello" --field "Message" --clear --enter""",
    "key": """\
key <name> - home|back|recents|power|volup|voldown|enter|tab|space|del|esc|
menu|screenshot|search|up|down|left|right|ok|shift|capslock|wake|sleep|
play|pause|next|prev|stop|ff|rew|mute|camera|call|endcall""",
    "open": """\
open <url | app name | package> - URL opens in Brave; otherwise resolves the
package by exact package, known app name (whatsapp, brave, settings...), or
fuzzy match and launches it.  open example.com  /  open whatsapp""",
    "close": """\
close <package | app name> - force-stop an app.
  close com.brave.browser  /  close whatsapp (resolves by name)""",
    "uninstall": """\
uninstall <package | app name> - uninstall an app entirely.
  uninstall whatsapp  /  uninstall com.discord""",
    "clear": """\
clear <package | app name> - wipe an app's data (logs you out, resets it to
first-run state). The app itself stays installed.
  clear whatsapp""",
    "run": """\
run <script-file> - execute a sequence of openadb commands from a file,
one command per line. Blank lines and # comments are skipped. Stops at the
first command that fails (exit code 1). Commands run as if typed on the
command line, so --sight, --wait, --field etc. all work.
Example script:
  # reconnect and reset
  open whatsapp
  wait --until "Chats"
  sight --brief""",
    "clipboard": """\
clip - print the current clipboard text (best effort).""",
    "notify": """\
notify - list current notification titles + apps.""",
    "apps": """\
apps [filter] - list installed user apps, optionally filtered.""",
    "info": """\
info <package> - version, install time, target SDK for an app.""",
    "battery": """\
battery - level, status, temperature, voltage, technology.""",
    "ping": """\
ping - device reachable? plus round-trip latency.""",
    "volume": """\
volume [up|down|mute|unmute|set N] - adjust or read media volume.""",
    "brightness": """\
brightness [N|up|down|max|min|auto] - set (0-255) or read brightness.""",
    "screen": """\
screen [on|off|state] - power the screen or report its state.""",
    "wake": """\
wake - wake the screen (does not unlock).""",
    "lock": """\
lock - turn screen off / lock the device.""",
    "unlock": """\
unlock - wake + swipe up + dismiss keyguard, then VERIFIES it worked.
Works for no-lock or swipe-to-unlock screens. If the device has a
PIN/pattern/password, adb cannot bypass it - the command reports "still
locked" instead of falsely claiming success; enter the credential
manually (or drive it via tap/text if you know it).""",
    "orient": """\
orient [portrait|landscape|auto] - set or report screen orientation.""",
    "dnd": """\
dnd [on|off|state] - toggle Do Not Disturb (zen mode).""",
    "airplane": """\
airplane [on|off] - toggle airplane mode.""",
    "record": """\
record [seconds] - record the screen, pull to ~/Videos. Default 5s.""",
    "status": """\
status - online / battery / screen size / focused app.""",
    "ocr": """\
ocr [filter] - OCR screenshot -> 'text' @ (cx,cy). Reads video/image text.""",
    "shot": """\
shot - screenshot to ~/Pictures and open it on the laptop.
shot --path <file> - save the screenshot to a specific file (no auto-open).""",
    "cmd": """\
cmd <adb shell args> - run raw adb shell and print output.
cmd wm size / cmd dumpsys battery / cmd pm list packages""",
    "top": """\
top - focused app + current activity stack summary.""",
    "state": """\
state - compact overview: battery, screen, lock state, volume, orientation,
DND, wifi, bluetooth, and focused app. Cheapest way to re-establish context.""",
    "who": """\
who - device manufacturer, model, Android version, SDK, security patch.""",
    "wait": """\
wait <seconds> - pause (e.g. after launching an app).  wait 3
wait --until <text> [--timeout N] - poll until text appears on screen.""",
    "wifi": """\
wifi [on|off|state] - toggle or read wifi.""",
    "bluetooth": """\
bluetooth [on|off|state] - toggle or read bluetooth.  (bt alias)""",
    "data": """\
data [on|off|state] - toggle or read mobile data.""",
    "signal": """\
signal - network type (lte/5g...) + signal strength.""",
    "storage": """\
storage - free space on /data, /sdcard, /system.""",
    "mem": """\
mem - RAM total and available.  (ram alias)""",
    "cpu": """\
cpu - top processes by CPU from the process table.""",
    "time": """\
time - phone's current clock time.""",
    "dpi": """\
dpi - display density (read-only; changing it breaks tap coordinates).""",
    "push": """\
push <local-file> <device-path> - copy a file to the phone.""",
    "pull": """\
pull <device-path> [local-path] - copy a file off the phone.""",
    "ls": """\
ls [path] - list files on the phone (default /sdcard).""",
    "verify": """\
verify <text> - exit 0 if the text is on screen (UI or OCR), else exit 1.
verify --gone <text> - poll (up to 10s) until the text DISAPPEARS, exit 1
if it's still there. Use to assert a page loaded or an action took effect.""",
    "sight": """\
sight - main "look" command. Use 'sight --brief' for a one-line summary.
Use 'sight --json' for a structured machine-readable dump (app, page,
screen state, locked, battery, keyboard, focused field, elements with
bounds/centers/state, and OCR lines with coordinates).
Shows: APP (human name), PAGE (title/url), KEYBOARD (if visible), FOCUSED
FIELD (where text will land - check before typing!), AT A GLANCE (top bar /
body / bottom bar, like a human's first look), LAYOUT (top->bottom,
left->right, [tap] {web tap} (text) 'web text', checked/unchecked,
disabled), TAP TARGETS (grouped, incl. unlabeled icon buttons), and EYES
(OCR with pixel coordinates). Icon-only buttons with no text or
content-desc are now included (labeled icon:<resource-id or class>) so
purely graphical controls are no longer invisible.
Run before acting and after acting to confirm.""",
}

HUMAN_HELP = """\
OpenADB - drive your Android phone from your computer's terminal.

WHAT IT IS
  OpenADB lets you control your phone by typing commands: tap buttons,
  type text, open apps, scroll, take screenshots, copy files. Instead of
  touching the screen you type what you want done.

  It "sees" your screen the way a screen-reader does (via Android's
  accessibility tree, plus text recognition / OCR). So when you say
  tap "send", it finds the word Send on the screen, works out its
  position, and taps it - no coordinates needed.

  EXAMPLES
    openadb open whatsapp          open an app
    openadb sight                  look at the screen
    openadb tap "send"             tap the button labelled Send
    openadb text "hello"           type a message
    openadb key enter              press the Enter key
    openadb scroll                 scroll the current screen
    openadb shot                   save a screenshot to ~/Pictures
    openadb status                 connection, battery, screen state

FIRST TIME SETUP (once, a few minutes)
  1. On the phone open Settings > About phone and tap "Build number"
     seven times. A message says you're now a developer.
  2. Back in Settings open "Developer options" and switch ON
     "USB debugging".
  3. Plug the phone into the PC with a data cable. On the phone, allow
     the "USB debugging" prompt (tick "Always allow" if shown).
  4. Unlock the phone - OpenADB cannot see a locked or off screen.
  5. Type:  openadb ping
     "device online" means you're ready to go.

THE THREE COMMANDS YOU'LL USE MOST
  1. openadb sight   - shows you, in plain words, what's on the phone
                       right now: the app, the page, and every button
                       and piece of text it can find. Run this before
                       and after each step so you know what's happening.
  2. openadb tap "X" - taps the thing called X on screen. Use
                       openadb tap 500 1200 to tap a spot by position.
  3. openadb text "Y" - types Y into the box that is currently selected.
                       If nothing is selected, tap the box first.

A REAL EXAMPLE (sending a message in WhatsApp)
  openadb open whatsapp
  openadb sight                    look at the screen
  openadb tap "search"             open the search bar
  openadb text "mum" --enter       type a name, press enter
  openadb tap "mum"                open that chat
  openadb text "coming home now"   write the message
  openadb sight                    check it landed in the box
  openadb tap "send"               send it

WHERE DOES MY TYPING GO?
  Text always goes into the field that is currently "focused". If you
  ran openadb sight, it tells you which field that is. Tap the box you
  want first, THEN type. This stops text landing in the wrong place.

USEFUL EXTRAS
  openadb swipe up                 scroll fast / change screen
  openadb tap "back"               go back a page
  openadb key home                 go to the home screen
  openadb ocr "what i want"        find a word and its position
  openadb verify "loaded"          check something is on screen
  openadb record 10                record 10 seconds of video
  openadb copy "this is it"        put text on the phone's clipboard
  openadb push myfile.jpg /sdcard/ copy a file to the phone
  openadb pull /sdcard/file.txt    copy a file from the phone

GOT STUCK?
  - "no device": phone unplugged, still locked, or the USB prompt wasn't
    allowed. Plug it in, unlock it, check the phone for a popup.
  - "device offline": the phone lost its connection - unplug and replug.
  - Says nothing found / can't see it: look at the phone. Popups, app
    dialogs and loading screens hide what you're after - try openadb
    sight to see what OpenADB can actually see.
  - For every single command:  openadb -help
  - This quick guide again:    openadb -help-human
"""


def print_help(cmd=None):
    if cmd and cmd in CMD_HELP:
        print(CMD_HELP[cmd])
    else:
        print(HELP)

def adb(*args, timeout=20):
    try:
        return subprocess.run(["adb", *args], capture_output=True, text=True,
                              timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess([], 1, "", "adb timed out")
    except FileNotFoundError:
        print("adb not found on this machine (is it installed and on PATH?)")
        sys.exit(1)


def shell(*args, timeout=20):
    return adb("shell", *args, timeout=timeout).stdout


def fail(msg):
    print(msg)
    sys.exit(1)


def device_online():
    """True if exactly one adb device is attached and authorized."""
    out = adb("devices").stdout
    if "unauthorized" in out:
        fail("device is UNAUTHORIZED - approve the adb debugging prompt on the "
             "phone (or re-pair / reconnect), then retry.")
    return bool(re.search(r"\bdevice$", out, re.M))


def check_device():
    """Friendly error instead of silent empty output when the phone is gone."""
    if not device_online():
        fail("no adb device online - is the phone connected, USB debugging "
             "enabled, and `adb devices` listing it as 'device'? "
             "Reconnect and retry.")


def batch_shell(parts, timeout=30):
    """Run several shell commands in ONE adb round-trip.

    parts: {label: shell-script}. Returns {label: combined stdout}.
    Big win on sight/state/status which each used to fire 4-9 adb calls.
    """
    script = "\n".join(f"echo '<@@{k}@@>'; {v}" for k, v in parts.items())
    out = adb("shell", script, timeout=timeout).stdout
    res = {}
    cur = None
    buf = []
    for line in out.splitlines():
        m = re.match(r"<@@(\w+)@@>", line)
        if m:
            if cur is not None:
                res[cur] = "\n".join(buf)
            cur = m.group(1)
            buf = []
        elif cur is not None:
            buf.append(line)
    if cur is not None:
        res[cur] = "\n".join(buf)
    return res


def app_name(pkg):
    return APP_NAMES.get(pkg, pkg.split(".")[-1].capitalize() if pkg else "?")


_SIZE_CACHE = [None]


def screen_size():
    if _SIZE_CACHE[0]:
        return _SIZE_CACHE[0]
    m = re.search(r"Physical size:\s*(\d+)x(\d+)", shell("wm", "size"))
    if m:
        _SIZE_CACHE[0] = (int(m.group(1)), int(m.group(2)))
    return _SIZE_CACHE[0]


def rotation():
    """Actual display rotation 0/1/2/3 (works even in auto mode)."""
    out = shell("dumpsys", "window")
    m = re.search(r"mCurrentRotation=ROTATION_(\d)", out)
    if m:
        return int(m.group(1))
    accel = shell("settings", "get", "system", "accelerometer_rotation").strip()
    if accel == "1":
        return None
    return {"0": 0, "1": 1, "2": 2, "3": 3}.get(
        shell("settings", "get", "system", "user_rotation").strip(), 0)


def screen_space():
    """Active drawable space (w, h) matching the current rotation."""
    w, h = screen_size() or (1080, 2340)
    if rotation() in (1, 3):
        w, h = h, w
    return w, h


def ui_xml():
    for attempt in range(2):
        cmd = ("rm -f /sdcard/ui.xml; uiautomator dump /sdcard/ui.xml "
               ">/dev/null 2>&1 && cat /sdcard/ui.xml")
        r = adb("shell", cmd, timeout=30)
        out = r.stdout
        if r.returncode == 0 and "<hierarchy" in out:
            return out
        time.sleep(0.4)
    return ""


def bounds_center(b):
    m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", b)
    if not m:
        return None
    x1, y1, x2, y2 = map(int, m.groups())
    return (x1 + x2) // 2, (y1 + y2) // 2


def overlap(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    minarea = min((ax2 - ax1) * (ay2 - ay1), (bx2 - bx1) * (by2 - by1))
    return inter / minarea if minarea else 0.0


def elements():
    xml = ui_xml()
    if not xml:
        return []
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []
    w, h = screen_size() or (1080, 2340)
    out = []
    seen = set()
    kept = []

    def add(label, t, d, b, x1, y1, x2, y2, cx, cy, clk, node, cls, web, icon):
        key_l = label
        dup = False
        for klabel, kbox, kc in kept:
            if klabel == key_l:
                if (overlap(kbox, (x1, y1, x2, y2)) > 0.9
                        or abs(cx - kc[0]) + abs(cy - kc[1]) < 25):
                    dup = True
                    break
        if dup:
            return
        kept.append((key_l, (x1, y1, x2, y2), (cx, cy)))
        out.append({
            "label": label, "text": t, "desc": d, "bounds": b,
            "clickable": clk,
            "rid": node.get("resource-id", ""), "class": cls.split(".")[-1],
            "web": web, "icon": icon,
            "icon_label": label if icon else "",
            "scrollable": node.get("scrollable") == "true",
            "checkable": node.get("checkable") == "true",
            "checked": node.get("checked") == "true",
            "enabled": node.get("enabled") != "false",
            "selected": node.get("selected") == "true",
            "focused": node.get("focused") == "true",
        })

    def walk(node, in_web, click_anc, depth=0):
        if depth > 200:
            return
        cls = node.get("class", "")
        web = in_web or "WebView" in cls
        self_click = node.get("clickable") == "true"
        clickable = self_click or click_anc
        t = (node.get("text") or "").strip()
        d = (node.get("content-desc") or "").strip()
        b = node.get("bounds", "")
        m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", b)
        if m:
            x1, y1, x2, y2 = map(int, m.groups())
            if x2 > x1 and y2 > y1:
                cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                if 0 <= cx < w and 0 <= cy < h:
                    if t or d:
                        key = (t, d, b)
                        if key not in seen:
                            seen.add(key)
                            clk = clickable
                            if (web and clk and
                                    (x2 - x1) * (y2 - y1) > 0.75 * w * h):
                                clk = False
                            add(t or d, t, d, b, x1, y1, x2, y2, cx, cy,
                                clk, node, cls, web, False)
                    elif "EditText" in cls and node.get("focused") == "true":
                        # Empty but FOCUSED input: it has no text and no
                        # content-desc, yet it's exactly where `text` would
                        # type. Surface it so sight/json know the target.
                        rid = node.get("resource-id", "")
                        tail = rid.rsplit("/", 1)[-1] if rid else "input"
                        key = ("__focused__", tail, b)
                        if key not in seen:
                            seen.add(key)
                            add(f"input:{tail}", "", "", b, x1, y1, x2, y2,
                                cx, cy, clickable, node, cls, web, False)
                    elif self_click and not web:
                        # icon-only control: no text/desc, but a real,
                        # small, native clickable target - a human would
                        # still see and tap this, so don't drop it.
                        short = cls.split(".")[-1]
                        icon_cls = ("Image", "Button", "Check", "Switch",
                                   "Radio", "Icon")
                        if any(k in short for k in icon_cls) and \
                                (x2 - x1) * (y2 - y1) < 0.2 * w * h:
                            rid = node.get("resource-id", "")
                            tail = rid.rsplit("/", 1)[-1] if rid else short
                            key = ("__icon__", tail, b)
                            if key not in seen:
                                seen.add(key)
                                add(f"icon:{tail}", "", "", b, x1, y1, x2,
                                    y2, cx, cy, True, node, cls, web, True)
        for child in node:
            walk(child, web, clickable, depth + 1)

    walk(root, False, False)
    return out


def display_label(e):
    """Best human-readable label for an element, icon-only included."""
    return (e.get("label") or e["text"] or e["desc"]
            or e.get("icon_label") or "(unlabeled)")


def focused_el(els=None):
    """The UI-tree element currently focused (usually the text field that
    `input text` would type into), or None. Pass `els` to reuse a fresh
    `elements()` dump from the caller instead of re-dumping."""
    if els is None:
        els = elements()
    for e in els:
        if e.get("focused"):
            return e
    return None


def fmt_ui(els):
    lines = []
    for i, e in enumerate(els):
        label = display_label(e)
        mark = "*" if e["clickable"] else " "
        state = ""
        if e.get("checkable"):
            state = " [x]" if e.get("checked") else " [ ]"
        if not e.get("enabled", True):
            state += " (disabled)"
        if e.get("focused"):
            state += " (focused)"
        lines.append(f"[{i:>3}]{mark} {label!r}{state} {e['bounds']} "
                     f"<{e['class']}> {e['rid']}")
    return "\n".join(lines)


def _app_from_window(text):
    for line in text.splitlines():
        m = re.search(r"mFocusedApp=ActivityRecord\{[^}]+? ([\w.]+)/([\w.]+)", line)
        if m:
            return m.group(1)
    return "unknown"


def focused_app(data=None):
    text = data.get("window", "") if data else shell("dumpsys", "window")
    return _app_from_window(text)


def _battery_level_from(text):
    m = re.search(r"level:\s*(\d+)", text)
    return m.group(1) if m else "?"


def battery_level(data=None):
    text = data.get("battery", "") if data else shell("dumpsys", "battery")
    return _battery_level_from(text)


# ---- look helpers ----

def center_y(b):
    m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", b)
    if not m:
        return 0
    x1, y1, x2, y2 = map(int, m.groups())
    return (y1 + y2) // 2


def page_title(els):
    for e in els:
        if e["class"] == "EditText" and e["text"]:
            return e["text"]
    for e in els:
        if e["text"] and not e["clickable"]:
            return e["text"][:60]
    for e in els:
        if e["text"]:
            return e["text"][:60]
    return ""


def describe(app, title, els):
    parts = [f"{app_name(app)} screen"]
    if title and title != app_name(app):
        parts.append(f"showing \"{title}\"")
    taps = sum(1 for e in els if e["clickable"])
    parts.append(f"{taps} tappable controls")
    for e in els:
        if e["class"] == "EditText" and e["text"]:
            parts.append(f"input field: \"{e['text'][:40]}\"")
            break
    return ". ".join(parts) + "."


def layout_lines(els):
    if not els:
        return ["  (no readable elements)"]
    for e in els:
        e["cy"] = center_y(e["bounds"])
    els.sort(key=lambda e: e["cy"])
    bands = []
    for e in els:
        if bands and e["cy"] - bands[-1][0] < 90:
            bands[-1][1].append(e)
        else:
            bands.append((e["cy"], [e]))
    lines = []
    for i, (cy, group) in enumerate(bands, 1):
        group.sort(key=lambda e: bounds_center(e["bounds"])[0])  # left -> right
        parts = []
        for e in group:
            label = display_label(e).replace("\n", " ")[:24]
            state = ""
            if e.get("checkable"):
                state = "\u2713" if e.get("checked") else "\u2717"
                state = f" ({state})"
            if not e.get("enabled", True):
                state += "!"
            if e["clickable"]:
                c = bounds_center(e["bounds"])
                item = f"[{label}{state}@({c[0]},{c[1]})]" if not e["web"] \
                    else f"{{{label}{state}@({c[0]},{c[1]})}}"
            else:
                item = f"({label})" if not e["web"] else f"'{label}'"
            parts.append(item)
        lines.append(f"  {i:>2}: " + "  ".join(parts))
    return lines


def _keyboard_from(text):
    m = re.search(r"mInputShown=(\w+)", text)
    if m:
        return m.group(1) == "true"
    m = re.search(r"isInputViewShown=(\w+)", text)
    if m:
        return m.group(1) == "true"
    return None


def keyboard_visible(data=None):
    text = data.get("input", "") if data else shell("dumpsys", "input_method")
    return _keyboard_from(text)


def at_a_glance(els, h):
    """Quick top/body/bottom read, the way a human's eyes scan a screen
    before looking at any one control."""
    top = [e for e in els if center_y(e["bounds"]) < h * 0.12]
    bottom = [e for e in els if center_y(e["bounds"]) > h * 0.88]
    top_ids = {id(e) for e in top}
    bottom_ids = {id(e) for e in bottom}
    body = [e for e in els if id(e) not in top_ids and id(e) not in bottom_ids]

    def names(lst, n):
        labels = [display_label(e) for e in lst if display_label(e) != "(unlabeled)"]
        if not labels:
            labels = [display_label(e) for e in lst]
        return ", ".join(labels[:n]) + ("..." if len(labels) > n else "")

    parts = []
    if top:
        parts.append(f"  top bar: {names(top, 8)}")
    if bottom:
        parts.append(f"  bottom bar: {names(bottom, 8)}")
    if body:
        parts.append(f"  body ({len(body)} items): {names(body, 10)}")
    return parts


def snapshot_key(e):
    c = bounds_center(e["bounds"])
    if not c:
        return None
    return (display_label(e), c[0] // 20, c[1] // 20)  # coarse bucket, jitter


def diff_report(before, after, before_app, after_app):
    bmap = {snapshot_key(e): e for e in before if snapshot_key(e)}
    amap = {snapshot_key(e): e for e in after if snapshot_key(e)}
    added = [amap[k] for k in amap if k not in bmap]
    removed = [bmap[k] for k in bmap if k not in amap]
    changed = []
    for k in amap:
        if k in bmap:
            be, ae = bmap[k], amap[k]
            if be.get("checked") != ae.get("checked") or \
                    be.get("enabled") != ae.get("enabled"):
                changed.append((be, ae))

    lines = []
    if before_app != after_app:
        lines.append(f"  APP CHANGED: {app_name(before_app)} -> "
                     f"{app_name(after_app)}")
    for e in added[:12]:
        c = bounds_center(e["bounds"])
        lines.append(f"  + {display_label(e)!r} @{c[0]},{c[1]}")
    for e in removed[:12]:
        c = bounds_center(e["bounds"])
        lines.append(f"  - {display_label(e)!r} @{c[0]},{c[1]}")
    for be, ae in changed[:12]:
        c = bounds_center(ae["bounds"])
        flips = []
        if be.get("enabled") != ae.get("enabled"):
            flips.append("enabled" if ae.get("enabled") else "disabled")
        if be.get("checked") != ae.get("checked"):
            flips.append("checked" if ae.get("checked") else "unchecked")
        lines.append(f"  ~ {display_label(ae)!r} @{c[0]},{c[1]} -> "
                     f"{', '.join(flips)}")
    any_change = bool(added or removed or changed or before_app != after_app)
    return lines, any_change


def cmd_sight(brief=False):
    els = elements()
    data = batch_shell({
        "window": "dumpsys window",
        "power": "dumpsys power",
        "input": "dumpsys input_method",
        "battery": "dumpsys battery",
        "trust": "dumpsys trust",
    })
    app = focused_app(data)
    title = page_title(els)
    state = screen_state(data)
    if state != "Awake":
        print(f"NOTE: screen is {state.lower()} - "
              "wake it first (wake / unlock)")
    else:
        locked = is_locked(data)
        if locked:
            print("NOTE: device is locked - run `unlock` first "
                  "(elements below may be the lock screen, not the app)")
    if brief:
        tappable = sorted((e for e in els if e["clickable"]),
                          key=lambda e: center_y(e["bounds"]))[:6]
        first = ", ".join(
            f"{(display_label(e).replace(chr(10), ' ')[:18] or '?')}@"
            f"{bounds_center(e['bounds'])[0]},{bounds_center(e['bounds'])[1]}"
            for e in tappable)
        print(f"BRIEF: {app_name(app)} | {title or '-'} | "
              f"battery {battery_level(data)}% | {len([e for e in els if e['clickable']])} taps"
              + (f" | {first}" if first else ""))
        return
    print(f"APP:    {app_name(app)} ({app})")
    if title:
        print(f"PAGE:   {title}")
    print(f"BATTERY: {battery_level(data)}%")
    print(f"SUMMARY: {describe(app, title, els)}")

    kb = keyboard_visible(data)
    if kb:
        print("KEYBOARD: visible (an on-screen text field is focused)")

    fe = focused_el(els)
    if fe:
        print(f"FOCUSED FIELD: {display_label(fe)!r} {fe['bounds']} "
              f"<{fe['class']}> (text will go here - use `text --check "
              f"{display_label(fe)!r}` to enforce this)")

    _, h = screen_size() or (1080, 2340)
    glance = at_a_glance(els, h)
    if glance:
        print("\nAT A GLANCE:")
        for line in glance:
            print(line)

    print("\nLAYOUT (top -> bottom, left -> right, ~coords are centers):")
    print("  [label@(x,y)] native tap   {label@(x,y)} web tap")
    print("  (label) native text        'label' web text")
    print("  (\u2713)/(\u2717) checked/unchecked   ! disabled")
    for line in layout_lines(els):
        print(line)

    ocr = ocr_lines()
    tappable = [e for e in els if e["clickable"]]
    if tappable:
        tappable.sort(key=lambda e: center_y(e["bounds"]))
        print(f"\nTAP TARGETS ({len(tappable)}, top -> bottom):")
        for e in tappable[:40]:
            label = display_label(e).replace("\n", " ")[:44]
            c = bounds_center(e["bounds"])
            kind = "icon" if e.get("icon") else "app"
            if e["web"]:
                kind = "web" if ocr_confirmed(label, ocr) else "web?"
            tag = "" if e.get("enabled", True) else "  (disabled)"
            print(f"  {kind:<4} {label!r}  ->  tap {c[0]} {c[1]}{tag}")

    if ocr:
        print("\nEYES (OCR, pixel-accurate):")
        for d in ocr[:45]:
            print(f"  '{d['text'][:70]}' @ ({d['cx']},{d['cy']})")
    elif ocr is not None:
        print("\nEYES (OCR): no text recognized")

    web = sum(1 for e in els if e["web"])
    if web and web * 2 > len(els):
        print("\nNOTE: heavy web page; web coords may drift. "
              "'web?' targets are NOT confirmed on screen.")
    if any(e.get("scrollable") for e in els):
        print("\nNOTE: this screen has scrollable content - "
              "there may be more above or below (use scroll/swipe).")


def _bounds_list(e):
    m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", e["bounds"])
    return [int(x) for x in m.groups()] if m else None


def sight_json():
    """Structured, machine-readable snapshot of the screen (for scripts/AIs)."""
    els = elements()
    data = batch_shell({
        "window": "dumpsys window",
        "power": "dumpsys power",
        "input": "dumpsys input_method",
        "battery": "dumpsys battery",
        "trust": "dumpsys trust",
    })
    app = focused_app(data)
    fe = focused_el(els)
    ocr = ocr_lines()
    return {
        "app": app_name(app),
        "package": app,
        "page": page_title(els) or None,
        "screen": screen_state(data),
        "locked": is_locked(data),
        "battery": battery_level(data),
        "keyboard": keyboard_visible(data),
        "focused_field": ({
            "label": display_label(fe),
            "bounds": _bounds_list(fe),
            "center": list(bounds_center(fe["bounds"])),
        } if fe else None),
        "scrollable": any(e.get("scrollable") for e in els),
        "elements": [{
            "label": display_label(e),
            "text": e["text"], "desc": e["desc"],
            "bounds": _bounds_list(e),
            "center": list(bounds_center(e["bounds"])),
            "clickable": e["clickable"], "class": e["class"],
            "rid": e["rid"], "web": e["web"], "icon": e["icon"],
            "checked": e.get("checked"),
            "enabled": e.get("enabled", True),
            "focused": e.get("focused"),
        } for e in els],
        "ocr": ([{"text": d["text"], "center": [d["cx"], d["cy"]],
                  "conf": d.get("conf")} for d in ocr] if ocr else []),
    }


def cmd_ui(filter_):
    els = elements()
    if filter_:
        f = filter_.lower()
        els = [e for e in els if f in e["text"].lower() or f in e["desc"].lower()
               or f in e.get("icon_label", "").lower()]
    print(f"{len(els)} elements\n")
    print(fmt_ui(els))


def cmd_find(text):
    cmd_ui(text)


def cmd_top():
    app = focused_app()
    print(f"focused app: {app} ({app_name(app)})")
    for line in shell("dumpsys", "window").splitlines():
        m = re.search(r"mFocusedApp=ActivityRecord\{[^}]+? [\w.]+/([\w.]+)",
                      line)
        if m:
            print("activity:", m.group(1))
            break
    print("\nactivity stack (top 8):")
    out = shell("dumpsys", "activity", "top")
    shown = 0
    for line in out.splitlines():
        m = re.search(r"ACTIVITY ([\w.]+)/([\w.]+)", line)
        if m and shown < 8:
            print("  ", m.group(1))
            shown += 1


# ---- act helpers ----

def match_level(query, text):
    """0=none, 1=whole-word, 2=edge(truncated), 3=exact (case-insensitive)."""
    if not query or not text:
        return 0
    t = text.lower()
    if query == t:
        return 3
    if t.startswith(query) or query.startswith(t):
        return 2
    if re.search(rf"(?<![a-z0-9]){re.escape(query)}(?![a-z0-9])", t):
        return 1
    return 0


def ocr_confirmed(query, ocr):
    if not ocr:
        return False
    words = [w for w in re.split(r"[^a-z0-9]+", query.lower()) if len(w) >= 3]
    keys = ([max(words, key=len)] if words else [query.lower()]) + [query.lower()]
    return any(match_level(k, m["text"]) for k in keys for m in ocr)


def _matches(query, els, prefer_scrollable=False):
    """All elements matching query, in UI order (same indices as `ui`).
    `prefer_scrollable` breaks ties toward scrollable containers (for
    swipe/scroll INSIDE an element, where a huge list matters more than
    a same-named label)."""
    def rank(e):
        tl = match_level(query, e["text"])
        dl = match_level(query, e["desc"])
        il = match_level(query, e.get("icon_label", ""))
        if prefer_scrollable:
            return (max(tl, dl, il), tl + dl + il,
                    1 if e.get("scrollable") else 0,
                    1 if e["clickable"] else 0, -1 if e["web"] else 0)
        return (max(tl, dl, il), tl + dl + il, 1 if e["clickable"] else 0,
                -1 if e["web"] else 0)

    hits = [e for e in els if match_level(query, e["text"])
            or match_level(query, e["desc"])
            or match_level(query, e.get("icon_label", ""))]
    best = max(hits, key=rank) if hits else None
    return best, hits


def _bounds_of(e):
    m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", e["bounds"])
    return tuple(map(int, m.groups())) if m else None


def _act_args(args, op):
    """Strip --wait/--index/--force flags; return (positional, opts)."""
    pos = []
    opts = {"wait": 0.0, "index": None, "force": False}
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--wait" and i + 1 < len(args):
            try:
                opts["wait"] = float(args[i + 1])
            except ValueError:
                fail("--wait needs a number of seconds")
            i += 1
        elif a == "--index" and i + 1 < len(args):
            try:
                opts["index"] = int(args[i + 1])
            except ValueError:
                fail("--index needs an integer")
            i += 1
        elif a == "--force":
            opts["force"] = True
        else:
            pos.append(a)
        i += 1
    return pos, opts


def _try_target(args, op="tap", index=None, force=False, soft=False):
    """Resolve args to (x, y, label, source). Returns None if not found.

    Exits 1 only on true refusals (ambiguous short query, unconfirmed
    web target without --force) where retrying cannot help. With
    soft=True (used by --wait polling) those refusals become "keep
    polling" instead, so a target that is mid-load is retried rather
    than aborted.
    """
    if len(args) == 2 and re.match(r"^\d+ \d+$", " ".join(args)):
        return int(args[0]), int(args[1]), "coords", "coord"
    query = " ".join(args).lower()
    if not query:
        print(f"{op} needs coordinates or a text label")
        sys.exit(1)

    els = elements()
    best, hits = _matches(query, els)
    if best:
        c = bounds_center(best["bounds"])
        top = max(match_level(query, best["text"]),
                  match_level(query, best["desc"]),
                  match_level(query, best.get("icon_label", "")))
        if len(query) < 3 and top < 3:
            if soft:
                return None
            print(f"ambiguous short query {query!r}, not {op}ping; candidates:")
            for e in hits[:10]:
                print(f"  {e['text'] or e['desc']!r} {e['bounds']}")
            sys.exit(1)
        if index is not None:
            if index < 0 or index >= len(hits):
                print(f"--index {index} out of range: {len(hits)} match(es) "
                      f"for {query!r}")
                sys.exit(1)
            best = hits[index]
            c = bounds_center(best["bounds"])
        if best["web"] and not force:
            ocr = ocr_lines()
            if ocr is not None and not ocr_confirmed(query, ocr):
                if soft:
                    return None
                print(f"web label {query!r} NOT confirmed on screen "
                      f"(OCR doesn't see it); not {op}ping. "
                      f"Force with '{op} X Y' or '--force'.")
                sys.exit(1)
            if ocr:
                b = _bounds_of(best)
                if b:
                    x1, y1, x2, y2 = b
                    pad = 60
                    om = [d for d in ocr if match_level(query, d["text"])]
                    near = [d for d in om
                            if x1 - pad <= d["cx"] <= x2 + pad
                            and y1 - pad <= d["cy"] <= y2 + pad]
                    if near:
                        pick = max(near, key=lambda x: (
                            match_level(query, x["text"]), x["conf"],
                            len(x["text"])))
                        c = (pick["cx"], pick["cy"])
        return c[0], c[1], display_label(best), "ui"

    ocr = ocr_lines()
    if ocr:
        om = [d for d in ocr if match_level(query, d["text"])]
        if om:
            d = max(om, key=lambda m: (match_level(query, m["text"]),
                                       m["conf"], len(m["text"])))
            lvl = match_level(query, d["text"])
            if len(query) < 3 and lvl < 3:
                if soft:
                    return None
                print(f"ambiguous short query {query!r}, not {op}ping; OCR hits:")
                for m in om[:10]:
                    print(f"  {m['text']!r} @ ({m['cx']},{m['cy']})")
                sys.exit(1)
            return d["cx"], d["cy"], d["text"], "ocr"
    return None


def _resolve_target(args, op="tap", index=None, force=False):
    r = _try_target(args, op, index=index, force=force)
    if r is None:
        print(f"NOT FOUND: {' '.join(args)!r}")
        sys.exit(1)
    return r


def _wait_target(pos, op, o):
    """Poll until the target appears (--wait N) or the timeout elapses."""
    if not o["wait"]:
        return _resolve_target(pos, op, index=o["index"], force=o["force"])
    deadline = time.time() + o["wait"]
    while True:
        r = _try_target(pos, op, index=o["index"], force=o["force"], soft=True)
        if r:
            return r
        if time.time() >= deadline:
            print(f"NOT FOUND after {o['wait']:g}s: {' '.join(pos)!r}")
            sys.exit(1)
        time.sleep(0.25)


def cmd_tap(args):
    pos, o = _act_args(args, "tap")
    x, y, label, src = _wait_target(pos, "tap", o)
    shell("input", "tap", str(x), str(y))
    print(f"tapped {label!r} at ({x},{y}) via {src}" if src != "coord"
          else f"tapped ({x},{y})")


def cmd_longtap(args):
    pos, o = _act_args(args, "longtap")
    x, y, label, src = _wait_target(pos, "longtap", o)
    shell("input", "swipe", str(x), str(y), str(x), str(y), "800")
    print(f"long-pressed {label!r} at ({x},{y})")


def cmd_doubletap(args):
    pos, o = _act_args(args, "doubletap")
    x, y, label, src = _wait_target(pos, "doubletap", o)
    shell("input", "tap", str(x), str(y))
    time.sleep(0.05)
    shell("input", "tap", str(x), str(y))
    print(f"double-tapped {label!r} at ({x},{y})")


def _dir_swipe(direction):
    w, h = screen_space()
    mx, my = w // 2, h // 2
    return {
        "left": (int(w * 0.85), my, int(w * 0.15), my),
        "right": (int(w * 0.15), my, int(w * 0.85), my),
        "up": (mx, int(h * 0.85), mx, int(h * 0.15)),
        "down": (mx, int(h * 0.15), mx, int(h * 0.85)),
    }[direction]


def cmd_swipe(args):
    pos, o = _act_args(args, "swipe")
    dirs = ("left", "right", "up", "down")
    if len(pos) == 2 and pos[0] not in dirs and pos[1] in dirs:
        # element-relative swipe: swipe "chat" up (scroll inside one pane)
        el, _ = _matches(pos[0].lower(), elements(), prefer_scrollable=True)
        if not el:
            print(f"NOT FOUND: {pos[0]!r}")
            sys.exit(1)
        b = _bounds_of(el)
        if not b:
            print("can't swipe inside that element (no bounds)")
            sys.exit(1)
        x1, y1, x2, y2 = b
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        px, py = int((x2 - x1) * 0.18), int((y2 - y1) * 0.18)
        d = pos[1]
        if d == "up":
            sx, sy, ex, ey = cx, y2 - py, cx, y1 + py
        elif d == "down":
            sx, sy, ex, ey = cx, y1 + py, cx, y2 - py
        elif d == "left":
            sx, sy, ex, ey = x2 - px, cy, x1 + px, cy
        else:
            sx, sy, ex, ey = x1 + px, cy, x2 - px, cy
        shell("input", "swipe", str(sx), str(sy), str(ex), str(ey), "150")
        print(f"swiped inside {display_label(el)!r} {d} "
              f"({sx},{sy})->({ex},{ey})")
        return
    if len(pos) == 2 and not re.match(r"^\d+$", pos[0]) \
            and not re.match(r"^\d+$", pos[1]):
        # drag between two elements: swipe "from" "to"
        a = _wait_target([pos[0]], "swipe", o)
        b = _wait_target([pos[1]], "swipe", o)
        shell("input", "swipe", str(a[0]), str(a[1]), str(b[0]), str(b[1]),
              "400")
        print(f"dragged {a[2]!r} -> {b[2]!r} "
              f"({a[0]},{a[1]})->({b[0]},{b[1]})")
        return
    if pos and pos[0] in dirs:
        x1, y1, x2, y2 = _dir_swipe(pos[0])
        ms = pos[1] if len(pos) > 1 else "150"
    else:
        if len(pos) < 4:
            print('usage: swipe [left|right|up|down | X1 Y1 X2 Y2 | '
                  '"elem" <dir> | "from" "to"] [ms]')
            sys.exit(1)
        try:
            x1, y1, x2, y2 = map(int, pos[:4])
        except ValueError:
            print('usage: swipe [left|right|up|down | X1 Y1 X2 Y2 | '
                  '"elem" <dir> | "from" "to"] [ms]')
            sys.exit(1)
        ms = pos[4] if len(pos) > 4 else "150"
    try:
        ms = str(max(0, int(ms)))
    except ValueError:
        ms = "150"
    shell("input", "swipe", str(x1), str(y1), str(x2), str(y2), ms)
    print(f"swiped ({x1},{y1})->({x2},{y2}) {ms}ms")


def cmd_scroll(args):
    """A real scroll: a fling (fast flick -> momentum scroll) by default, or
    a slow controlled drag with --drag. This is NOT the same as `swipe`:
    swipe is a deliberate hand-placed gesture; scroll moves content in the
    focused/scrollable area (or a named panel) like a human flicking a list.
    """
    mode = "fling"
    times = 1
    direction = "down"
    element = None
    for a in args:
        if a in ("--drag", "--slow"):
            mode = "drag"
        elif a in ("--fling", "--fast"):
            mode = "fling"
        elif a.lower() in ("up", "down"):
            direction = a.lower()
        else:
            try:
                times = int(a)
            except ValueError:
                element = (a if element is None else element + " " + a)
    if times < 1:
        times = 1
    # fling = short fast swipe (velocity -> inertial scroll like a real flick)
    # drag  = slow deliberate move (content follows the finger, precise)
    dur = 70 if mode == "fling" else 450
    gap = 0.45 if mode == "fling" else 0.25

    def do_fling(x, sy, ey):
        shell("input", "swipe", str(x), str(sy), str(x), str(ey), str(dur))
        time.sleep(gap)

    if element:
        el, _ = _matches(element.lower(), elements(), prefer_scrollable=True)
        if not el:
            print(f"NOT FOUND: {element!r}")
            sys.exit(1)
        b = _bounds_of(el)
        if not b:
            print(f"can't scroll inside {element!r} (no bounds)")
            sys.exit(1)
        x1, y1, x2, y2 = b
        cx = (x1 + x2) // 2
        if mode == "fling":
            pad = max(30, int((y2 - y1) * 0.28))
        else:
            pad = max(20, int((y2 - y1) * 0.15))
        if direction == "up":
            sy, ey = y2 - pad, y1 + pad
        else:
            sy, ey = y1 + pad, y2 - pad
        for _ in range(times):
            do_fling(cx, sy, ey)
        print(f"scrolled {times}x {direction} inside {element!r} ({mode})")
        return
    w, h = screen_space()
    mx = w // 2
    if mode == "fling":
        y_hi, y_lo = int(h * 0.72), int(h * 0.28)
    else:
        y_hi, y_lo = int(h * 0.62), int(h * 0.38)
    if direction == "up":
        sy, ey = y_lo, y_hi
    else:
        sy, ey = y_hi, y_lo
    for _ in range(times):
        do_fling(mx, sy, ey)
    print(f"scrolled {times}x {direction} ({mode})")


def clear_field():
    """Select-all + delete in the focused field (best effort)."""
    r = adb("shell", "input", "keycombination", "113", "29")  # ctrl+A
    time.sleep(0.15)
    shell("input", "keyevent", "67")  # DEL
    if "error" in r.stderr.lower() or "usage" in r.stderr.lower() \
            or "keycombination" in r.stdout.lower():
        print("note: select-all (keycombination) not supported here - "
              "existing text may not have been fully cleared")


def cmd_text(args):
    field_q = check_q = None
    clear = enter = verify = False
    parts = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--enter":
            enter = True
        elif a == "--clear":
            clear = True
        elif a == "--verify":
            verify = True
        elif a in ("--field", "--check") and i + 1 < len(args):
            if a == "--field":
                field_q = args[i + 1]
            else:
                check_q = args[i + 1]
            i += 1
        else:
            parts.append(a)
        i += 1
    text = " ".join(parts)
    if not text:
        print('text "<string>" [--field "<label>" | --check "<label>" | '
              '--clear | --enter | --verify]')
        sys.exit(1)

    if field_q:
        # tap the right field first so text lands where intended
        x, y, label, src = _resolve_target([field_q], "tap")
        shell("input", "tap", str(x), str(y))
        time.sleep(0.4)

    fe = focused_el()
    if check_q:
        if not fe:
            print(f"REFUSED: nothing is focused, but --check expected "
                  f"{check_q!r}. Use --field \"{check_q}\" to tap the field "
                  "first, or tap it manually.")
            sys.exit(1)
        cq = check_q.lower()
        lvl = max(match_level(cq, fe["text"]),
                  match_level(cq, fe["desc"]),
                  match_level(cq, fe.get("icon_label", "")),
                  match_level(cq, fe.get("rid", "").rsplit("/", 1)[-1]))
        if lvl == 0:
            print(f"REFUSED: the focused field is {display_label(fe)!r}, not "
                  f"{check_q!r} - typing here would land in the WRONG field. "
                  f"Use --field \"{check_q}\" to tap the right one first.")
            sys.exit(1)
    if clear:
        if fe:
            clear_field()
        else:
            print("note: nothing focused, skipping --clear")

    q = text.replace("'", "'\\''")
    shell("input", "text", f"'{q}'")
    if enter:
        shell("input", "keyevent", "66")
    print("typed:", text + (" + enter" if enter else ""))

    if verify:
        time.sleep(0.35)
        fe2 = focused_el()
        got = fe2.get("text", "").strip() if fe2 else ""
        norm = lambda s: s.replace(" ", "").lower()
        ok = bool(got) and (norm(text) in norm(got)
                            or norm(got).startswith(norm(text)))
        why = ""
        if not ok:
            # Many fields (WhatsApp, web inputs, some apps) expose no text in
            # the UI tree even when full. Confirm via OCR around the field
            # instead of reporting a false MISMATCH.
            ocr = ocr_lines()
            if ocr:
                near = ocr
                if fe2:
                    b = _bounds_of(fe2)
                    if b:
                        x1, y1, x2, y2 = b
                        near = [d for d in ocr if y1 - 30 <= d["cy"] <= y2 + 30]
                if ocr_confirmed(text, near if near else ocr):
                    ok = True
                    why = " (field exposes no text - confirmed via OCR)"
        print(f"verify: field shows {got!r} -> "
              + ("OK" + why if ok else "MISMATCH (text may not have landed)"))


KEYS = {
    "home": "3", "back": "4", "recents": "187", "power": "26",
    "volup": "24", "voldown": "25", "enter": "66", "tab": "61",
    "space": "62", "del": "67", "esc": "111", "menu": "82",
    "screenshot": "120", "search": "84", "up": "19", "down": "20",
    "left": "21", "right": "22", "ok": "23", "shift": "59",
    "capslock": "115", "wake": "224", "sleep": "223",
    "play": "126", "pause": "127", "next": "87", "prev": "88",
    "stop": "86", "ff": "90", "rew": "89", "mute": "164",
    "camera": "27", "call": "5", "endcall": "6", "appswitch": "187",
}


def cmd_key(name):
    if not name:
        print("key must be one of:", ", ".join(KEYS))
        sys.exit(1)
    code = KEYS.get(name.lower())
    if not code and len(name) == 1 and name.isdigit():
        code = str(7 + int(name))  # KEYCODE_0 = 7 .. KEYCODE_9 = 16
    if not code:
        print("key must be one of:", ", ".join(KEYS))
        sys.exit(1)
    shell("input", "keyevent", code)
    print("pressed:", name.lower())


def _open_url(url):
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    adb("shell", "am", "start", "-a", "android.intent.action.VIEW",
        "-d", url, "-n", BRAVE)
    print("opened in Brave:", url)


def _resolve_candidates(target):
    """Return package candidates by exact package, known app name, or fuzzy."""
    t = target.strip()
    if "." in t:
        return [t]
    low = t.lower()
    cands = []
    for pkg, name in APP_NAMES.items():
        if name.lower() == low or name.lower().startswith(low):
            cands.append(pkg)
    out = shell("pm", "list", "packages", "-3")
    for pkg in re.findall(r"package:(.+)", out):
        if low in pkg.lower() or low == pkg.split(".")[-1].lower():
            if pkg not in cands:
                cands.append(pkg)
    return cands


def launch_activity(pkg):
    """Return 'package/activity' if pkg has a launchable activity, else None."""
    out = shell("cmd", "package", "resolve-activity", "--brief",
                "-a", "android.intent.action.MAIN",
                "-c", "android.intent.category.LAUNCHER", pkg)
    for line in out.splitlines():
        line = line.strip()
        if "/" in line and not line.startswith(("priority=", "No activity",
                                                "Resolving", "Warning")):
            return line
    return None


def cmd_open(target):
    if "://" in target or target.startswith("www."):
        _open_url(target)
        return
    for pkg in _resolve_candidates(target):
        act = launch_activity(pkg)
        if act:
            r = adb("shell", "am", "start", "-n", act)
            if r.returncode == 0 and "Error" not in r.stdout:
                print("launching app:", pkg)
                return
    m = re.match(r"^[\w-]+(\.[\w-]+)+$", target)
    if m and re.match(r"^[a-z]{2,6}$", target.rsplit(".", 1)[-1]):
        _open_url(target)
        return
    if "." in target and "/" in target:
        slash = target.find("/")
        looks_like_component = slash + 1 < len(target) and target[slash + 1] == "."
        if not looks_like_component:
            _open_url(target)
            return
    print("not found / not launchable:", target)
    sys.exit(1)


def cmd_close(target):
    if not target:
        print("close <app name or package>   e.g. close whatsapp")
        sys.exit(1)
    pkgs = _resolve_candidates(target)
    if not pkgs:
        print("no app matched:", target)
        sys.exit(1)
    for pkg in pkgs:
        shell("am", "force-stop", pkg)
        print("closed:", pkg, f"({app_name(pkg)})")


def cmd_uninstall(target):
    if not target:
        print("uninstall <app name or package>   e.g. uninstall whatsapp")
        sys.exit(1)
    pkgs = _resolve_candidates(target)
    if not pkgs:
        print("no app matched:", target)
        sys.exit(1)
    pkg = pkgs[0]
    r = adb("uninstall", pkg)
    if r.returncode == 0 and "Success" in r.stdout:
        print("uninstalled:", pkg)
    else:
        print("uninstall failed:", r.stdout.strip() or r.stderr.strip())
        sys.exit(1)


def cmd_clear(target):
    if not target:
        print("clear <app name or package>   e.g. clear whatsapp")
        sys.exit(1)
    pkgs = _resolve_candidates(target)
    if not pkgs:
        print("no app matched:", target)
        sys.exit(1)
    pkg = pkgs[0]
    r = adb("shell", "pm", "clear", pkg)
    if "Success" in r.stdout:
        print("cleared app data:", pkg, f"({app_name(pkg)})")
    else:
        print("clear failed:", r.stdout.strip() or r.stderr.strip())
        sys.exit(1)


# ---- OCR ----

def screenshot_bytes():
    try:
        r = subprocess.run(["adb", "exec-out", "screencap", "-p"],
                           capture_output=True, timeout=20)
    except subprocess.TimeoutExpired:
        return b""
    except FileNotFoundError:
        print("adb not found on this machine (is it installed and on PATH?)")
        sys.exit(1)
    return r.stdout if r.returncode == 0 else b""


def _tesseract_lines(path, psm):
    try:
        r = subprocess.run(
            ["tesseract", str(path), "stdout", "--psm", psm, "tsv"],
            capture_output=True, text=True, timeout=15)
    except subprocess.TimeoutExpired:
        return []
    rows = r.stdout.splitlines()
    if not rows:
        return []
    words = {}
    for row in rows[1:]:
        cols = row.split("\t")
        if len(cols) < 12 or cols[0] != "5":
            continue
        text = cols[11].strip()
        if not text:
            continue
        try:
            conf = float(cols[10])
        except ValueError:
            conf = 0
        if conf < 40:
            continue
        try:
            left, top, w, h = map(int, cols[6:10])
        except ValueError:
            continue
        key = (cols[1], cols[2], cols[3])
        if key not in words:
            words[key] = {"x1": left, "y1": top, "x2": left + w,
                          "y2": top + h, "text": text, "conf": conf}
        else:
            d = words[key]
            d["x1"] = min(d["x1"], left)
            d["y1"] = min(d["y1"], top)
            d["x2"] = max(d["x2"], left + w)
            d["y2"] = max(d["y2"], top + h)
            d["text"] += " " + text
            d["conf"] = min(d["conf"], conf)
    out = []
    for d in words.values():
        alnum = sum(ch.isalnum() for ch in d["text"])
        if alnum < 3 or alnum / max(1, len(d["text"])) < 0.4:
            continue
        if d["y2"] - d["y1"] > 200:
            continue
        d["cx"] = (d["x1"] + d["x2"]) // 2
        d["cy"] = (d["y1"] + d["y2"]) // 2
        out.append(d)
    return out


def ocr_lines():
    """OCR screenshot once, run psm 6 + psm 11, merge for better coverage."""
    if not shutil.which("tesseract"):
        return None
    img = screenshot_bytes()
    if not img:
        return []
    tmp = SHOTS / "ocr-raw.png"
    tmp.write_bytes(img)
    merged = {}
    for psm in ("6", "11"):
        for d in _tesseract_lines(tmp, psm):
            key = (d["cx"] // 90, d["cy"] // 60)
            if key not in merged or len(d["text"]) > len(merged[key]["text"]):
                merged[key] = d
    out = sorted(merged.values(), key=lambda d: (d["cy"] // 60, d["cx"]))
    return out


def cmd_ocr(filter_):
    lines = ocr_lines()
    if lines is None:
        print("tesseract not installed")
        return
    if not lines:
        print("(no text recognized)")
        return
    for d in lines:
        if filter_ and filter_.lower() not in d["text"].lower():
            continue
        print(f"  '{d['text'][:70]}' @ ({d['cx']},{d['cy']})")


def cmd_shot(args):
    open_it = True
    path = SHOTS / f"phone-{int(time.time())}.png"
    if args:
        if args[0] == "--path" and len(args) > 1:
            path = Path(args[1]).expanduser()
            open_it = False
        else:
            print("usage: shot  |  shot --path <file>")
            sys.exit(1)
    try:
        with open(path, "wb") as f:
            r = subprocess.run(["adb", "exec-out", "screencap", "-p"],
                               stdout=f, timeout=20)
    except subprocess.TimeoutExpired:
        print("screenshot timed out")
        return
    except FileNotFoundError:
        print("adb not found on this machine (is it installed and on PATH?)")
        sys.exit(1)
    print(path if r.returncode == 0 else "screenshot failed")
    if r.returncode == 0 and open_it:
        subprocess.Popen(["xdg-open", str(path)])


def cmd_record(seconds):
    seconds = int(seconds or "5")
    dev_path = "/sdcard/phone-rec.mp4"
    shell("rm", "-f", dev_path)
    print(f"recording {seconds}s...")
    r = adb("shell", "screenrecord", "--time-limit", str(seconds), dev_path,
            timeout=max(30, seconds + 15))
    if "failed" in (r.stdout + r.stderr).lower():
        # non-16:9 screens (e.g. 1080x2340) often break screenrecord's
        # default encoder setup - retry at a standard size
        shell("screenrecord", "--size", "1080x1920", "--time-limit",
              str(seconds), dev_path, timeout=max(30, seconds + 15))
    dest = VIDS / f"phone-{int(time.time())}.mp4"
    r = adb("pull", dev_path, str(dest), timeout=max(30, seconds + 15))
    shell("rm", "-f", dev_path)
    print(str(dest) if r.returncode == 0 else "recording failed")


# ---- device ----

def cmd_status():
    dev = adb("devices").stdout
    online = bool(re.search(r"\bdevice$", dev, re.M)) and "unauthorized" not in dev
    data = batch_shell({"wm": "wm size", "window": "dumpsys window",
                        "battery": "dumpsys battery"})
    size = re.search(r"Physical size:\s*(\d+)x(\d+)", data.get("wm", ""))
    print(f"device online: {online}")
    print(f"screen: {size.group(0).split()[2] if size else 'unknown'}")
    print(f"battery: {battery_level(data)}%")
    app = focused_app(data)
    print(f"focused app: {app_name(app)} ({app})")


def cmd_battery():
    out = shell("dumpsys", "battery")
    status_map = {"1": "unknown", "2": "charging", "3": "discharging",
                  "4": "not charging", "5": "full"}
    for key in ("level", "status", "health", "temperature", "voltage",
                "technology"):
        m = re.search(rf"^\s*{key}:\s*(.+)$", out, re.M)
        if m:
            val = m.group(1).strip()
            if key == "status":
                val = status_map.get(val, val)
            elif key == "temperature":
                val = f"{int(val) / 10.0:.1f} C"
            print(f"{key}: {val}")


def cmd_ping():
    start = time.perf_counter()
    r = adb("devices")
    lat = (time.perf_counter() - start) * 1000
    online = bool(re.search(r"\bdevice$", r.stdout, re.M)) \
        and "unauthorized" not in r.stdout
    print(f"device online: {online}")
    print(f"adb round-trip: {lat:.0f} ms")
    if online:
        data = batch_shell({"window": "dumpsys window",
                            "battery": "dumpsys battery"})
        print(f"battery: {battery_level(data)}%  focused: "
              f"{app_name(focused_app(data))}")


def cmd_apps(filter_):
    if filter_ in ("--all", "--system"):
        out = shell("pm", "list", "packages")
        pkgs = sorted(re.findall(r"package:(.+)", out))
        print(f"{len(pkgs)} packages")
    else:
        out = shell("pm", "list", "packages", "-3")
        pkgs = sorted(re.findall(r"package:(.+)", out))
        if filter_:
            pkgs = [p for p in pkgs if filter_.lower() in p.lower()]
        print(f"{len(pkgs)} user apps")
    for p in pkgs:
        print("  ", p)


def cmd_info(pkg):
    if not pkg:
        print("info <package>")
        sys.exit(1)
    out = shell("dumpsys", "package", pkg)
    if "Unable to find package" in out:
        print("package not found:", pkg)
        return
    fields = {
        "versionName": "version",
        "versionCode": "version code",
        "firstInstallTime": "first installed",
        "lastUpdateTime": "last updated",
        "targetSdkVersion": "target SDK",
    }
    for key, label in fields.items():
        m = re.search(rf"\s{key}=(\S+)", out)
        if m:
            print(f"{label}: {m.group(1)}")


def cmd_volume(args):
    if not args or args[0] == "get":
        r = adb("shell", "cmd", "media_session", "volume",
                "--stream", "3", "--get")
        m = re.search(r"volume is (\d+) in range \[(\d+)\.\.(\d+)\]",
                      r.stdout)
        if m:
            print(f"media volume: {m.group(1)} (max {m.group(3)})")
        else:
            print("media volume: unknown")
        return
    a = args[0]
    if a == "up":
        shell("input", "keyevent", "24")
        print("volume up")
    elif a == "down":
        shell("input", "keyevent", "25")
        print("volume down")
    elif a == "mute":
        shell("cmd", "media_session", "volume",
              "--stream", "3", "--set", "0")
        print("media volume: muted")
    elif a == "unmute":
        m = re.search(r"volume is (\d+) in range",
                      adb("shell", "cmd", "media_session", "volume",
                          "--stream", "3", "--get").stdout)
        if m and int(m.group(1)) == 0:
            shell("cmd", "media_session", "volume",
                  "--stream", "3", "--set", "10")
        print("media volume: unmuted")
    elif a == "set" and len(args) > 1:
        shell("cmd", "media_session", "volume",
              "--stream", "3", "--set", args[1])
        print("media volume set to", args[1])
    else:
        print("usage: volume [up|down|mute|unmute|set N|get]")
        sys.exit(1)


def cmd_brightness(args):
    mode = shell("settings", "get", "system", "screen_brightness_mode").strip()
    if not args or args[0] == "state":
        if mode == "1":
            print("brightness: auto")
        else:
            cur = shell("settings", "get", "system", "screen_brightness").strip()
            print(f"brightness: {cur}")
        return
    a = args[0]
    if a == "auto":
        shell("settings", "put", "system", "screen_brightness_mode", "1")
        print("brightness: auto")
        return
    cur = shell("settings", "get", "system", "screen_brightness").strip()
    try:
        cur = int(cur)
    except ValueError:
        cur = 120
    if a == "up":
        val = min(255, cur + 40)
    elif a == "down":
        val = max(0, cur - 40)
    elif a == "max":
        val = 255
    elif a == "min":
        val = 0
    else:
        try:
            val = max(0, min(255, int(a)))
        except ValueError:
            print("usage: brightness [N 0-255|up|down|max|min|auto|state]")
            sys.exit(1)
    shell("settings", "put", "system", "screen_brightness_mode", "0")
    shell("settings", "put", "system", "screen_brightness", str(val))
    print(f"brightness: {val}")


def cmd_screen(args):
    a = args[0] if args else "state"
    if a == "on":
        shell("input", "keyevent", "224")
        print("screen: on")
    elif a == "off":
        shell("input", "keyevent", "223")
        print("screen: off")
    else:
        out = shell("dumpsys", "power")
        m = re.search(r"mWakefulness=(\w+)", out)
        print("screen:", m.group(1) if m else "unknown")


def cmd_wake():
    shell("input", "keyevent", "224")
    print("woke screen")


def cmd_lock():
    shell("input", "keyevent", "26")
    print("locked")


def _locked_from(text):
    for pat in (r"mDreamingLockscreen=(\w+)",
                r"isStatusBarKeyguard=(\w+)",
                r"mShowingLockscreen=(\w+)",
                r"isKeyguardShowingAndNotOccluded=(\w+)",
                r"deviceLocked=(\w+)"):
        m = re.search(pat, text)
        if m:
            return m.group(1) == "true"
    return None


def is_locked(data=None):
    if data:
        r = _locked_from(data.get("window", ""))
        if r is not None:
            return r
        return _locked_from(data.get("trust", ""))
    r = _locked_from(shell("dumpsys", "window"))
    if r is not None:
        return r
    return _locked_from(shell("dumpsys", "trust"))


def cmd_unlock():
    shell("input", "keyevent", "224")  # wake
    for _ in range(5):
        if screen_state() == "Awake":
            break
        time.sleep(0.3)
    w, h = screen_space()
    # swipe up: dismisses a basic swipe lockscreen, harmless no-op otherwise
    shell("input", "swipe", str(w // 2), str(int(h * 0.8)),
          str(w // 2), str(int(h * 0.35)), "300")
    time.sleep(0.3)
    shell("wm", "dismiss-keyguard")
    time.sleep(0.4)
    locked = is_locked()
    if locked is True:
        print("still locked: this device has a PIN/pattern/password. "
              "adb cannot bypass a secure lock without the credential - "
              "enter it manually, or if you know the PIN use "
              "`text \"1234\" --enter` / `key <digit>` once the keypad is up.")
        sys.exit(1)
    elif locked is False:
        print("unlocked")
    else:
        print("unlock attempted (couldn't confirm lock state on this "
              "device - check with `sight`)")


def cmd_orient(args):
    a = args[0] if args else "state"
    if a == "portrait":
        shell("settings", "put", "system", "accelerometer_rotation", "0")
        shell("settings", "put", "system", "user_rotation", "0")
        print("orientation: portrait")
    elif a == "landscape":
        shell("settings", "put", "system", "accelerometer_rotation", "0")
        shell("settings", "put", "system", "user_rotation", "1")
        print("orientation: landscape")
    elif a == "auto":
        shell("settings", "put", "system", "accelerometer_rotation", "1")
        print("orientation: auto")
    else:
        accel = shell("settings", "get", "system", "accelerometer_rotation").strip()
        rot = shell("settings", "get", "system", "user_rotation").strip()
        map_ = {"0": "portrait", "1": "landscape",
                "2": "reverse-portrait", "3": "reverse-landscape"}
        if accel == "1":
            print("orientation: auto")
        else:
            print("orientation:", map_.get(rot, rot))


def cmd_dnd(args):
    a = args[0] if args else "state"
    if a == "on":
        shell("settings", "put", "global", "zen_mode", "3")
        print("do-not-disturb: on")
    elif a == "off":
        shell("settings", "put", "global", "zen_mode", "0")
        print("do-not-disturb: off")
    else:
        zen = shell("settings", "get", "global", "zen_mode").strip()
        map_ = {"0": "off", "1": "important only", "2": "alarms only",
                "3": "block all"}
        print("do-not-disturb:", map_.get(zen, zen))


def cmd_airplane(args):
    a = args[0] if args else "state"
    if a == "on":
        shell("settings", "put", "global", "airplane_mode_on", "1")
        adb("shell", "am", "broadcast", "-a",
            "android.intent.action.AIRPLANE_MODE", "--ez", "state", "true")
        print("airplane mode: on")
    elif a == "off":
        shell("settings", "put", "global", "airplane_mode_on", "0")
        adb("shell", "am", "broadcast", "-a",
            "android.intent.action.AIRPLANE_MODE", "--ez", "state", "false")
        print("airplane mode: off")
    else:
        print("airplane mode:",
              shell("settings", "get", "global", "airplane_mode_on").strip())


def cmd_clipboard(args=None):
    args = args or []
    if args and args[0] == "set" and len(args) > 1:
        print("clipboard set not available: this device has no "
              "`cmd clipboard` and `service call` is rejected on "
              "Android 16; type into a focused field with `text \"...\"` "
              "instead.")
        return
    out = adb("shell", "cmd", "clipboard", "get-text").stdout.strip()
    if out and "No shell command implementation" not in out and out != "null":
        print("clipboard:", out)
    else:
        print("clipboard: not readable via shell on this device "
              "(no `cmd clipboard` / `dumpsys clipboard` support)")


def cmd_notify():
    out = shell("dumpsys", "notification", "--noredact")
    entries = []
    cur = None
    pending = ""
    for line in out.splitlines():
        m = re.search(r"NotificationRecord\([^)]*pkg=([\w.]+)", line)
        if m:
            pending = m.group(1)
            continue
        m = re.search(r"android\.title=String \((.*)\)\s*$", line)
        if m:
            cur = {"title": m.group(1), "text": "", "pkg": pending or ""}
            entries.append(cur)
            continue
        m = re.search(r"android\.text=String \((.*)\)\s*$", line)
        if m and cur:
            cur["text"] = m.group(1)
    if not entries:
        print("no notifications")
        return
    print(f"{len(entries)} notification(s):")
    for e in entries[:20]:
        label = e["title"]
        if e["text"] and e["text"] != e["title"]:
            label += f" — {e['text']}"
        print(f"  [{e['pkg'] or '?'}] {label[:90]}")


# ---- extra ----

def _wakefulness_from(text):
    m = re.search(r"mWakefulness=(\w+)", text)
    return m.group(1) if m else "unknown"


def screen_state(data=None):
    text = data.get("power", "") if data else shell("dumpsys", "power")
    return _wakefulness_from(text)


def _state_info():
    size = screen_size() or (0, 0)
    data = batch_shell({
        "window": "dumpsys window",
        "trust": "dumpsys trust",
        "power": "dumpsys power",
        "battery": "dumpsys battery",
        "date": "date",
        "vol": "cmd media_session volume --stream 3 --get",
        "settings": "settings get system accelerometer_rotation; "
                    "settings get system user_rotation; "
                    "settings get global zen_mode; "
                    "settings get global wifi_on; "
                    "settings get global bluetooth_on",
    })
    locked = is_locked(data)
    vol = "?"
    m = re.search(r"volume is (\d+) in range \[\d+\.\.(\d+)\]",
                  data.get("vol", ""))
    if m:
        vol = f"{m.group(1)}/{m.group(2)}"
    s = data.get("settings", "").splitlines()
    accel = s[0].strip() if len(s) > 0 else ""
    urot = s[1].strip() if len(s) > 1 else ""
    zen = s[2].strip() if len(s) > 2 else ""
    wifi = s[3].strip() if len(s) > 3 else ""
    bt = s[4].strip() if len(s) > 4 else ""
    orient = "auto" if accel == "1" else \
        {"0": "portrait", "1": "landscape",
         "2": "reverse-portrait", "3": "reverse-landscape"}.get(urot, "?")
    dnd = {"0": "off", "1": "important", "2": "alarms", "3": "block"}.get(
        zen, zen)
    app = focused_app(data)
    return {
        "online": True,
        "size": list(size),
        "battery": battery_level(data),
        "screen": screen_state(data),
        "locked": locked,
        "time": data.get("date", "").strip(),
        "volume": vol,
        "orientation": orient,
        "dnd": dnd,
        "wifi": "on" if wifi == "1" else wifi,
        "bluetooth": "on" if bt == "1" else bt,
        "app": app,
        "app_name": app_name(app),
    }


def cmd_state(args=None):
    if args and args[0] == "--json":
        print(json.dumps(_state_info(), indent=2))
        return
    info = _state_info()
    lock_str = {True: "yes", False: "no"}.get(info["locked"], "?")
    size = info["size"]
    print(f"device online | {size[0]}x{size[1]} | battery {info['battery']}% | "
          f"screen {info['screen']} | locked {lock_str} | time {info['time']}")
    print(f"volume {info['volume']} | orientation {info['orientation']} | "
          f"dnd {info['dnd']} | wifi {info['wifi']} | "
          f"bluetooth {info['bluetooth']}")
    print(f"focused: {info['app_name']} ({info['app']})")


def cmd_who():
    out = shell("getprop")
    fields = {
        "ro.product.manufacturer": "manufacturer",
        "ro.product.model": "model",
        "ro.product.name": "product",
        "ro.build.version.release": "android",
        "ro.build.version.sdk": "sdk",
        "ro.build.version.security_patch": "security patch",
    }
    found = {}
    for line in out.splitlines():
        m = re.match(r"\[([^]]+)\]: \[([^]]*)\]", line.strip())
        if m and m.group(1) in fields:
            found[fields[m.group(1)]] = m.group(2)
    for label in ("manufacturer", "model", "android", "sdk",
                  "security patch"):
        if label in found:
            print(f"{label}: {found[label]}")

def cmd_wait(args):
    if not args:
        print("wait <seconds>   OR   wait --until <text> [--timeout N]")
        sys.exit(1)
    if args[0] == "--until":
        timeout = 30
        text_parts = []
        i = 1
        while i < len(args):
            if args[i] == "--timeout" and i + 1 < len(args):
                timeout = float(args[i + 1])
                i += 2
            else:
                text_parts.append(args[i])
                i += 1
        query = " ".join(text_parts).lower()
        deadline = time.time() + timeout
        n = 0
        while time.time() < deadline:
            for e in elements():
                if match_level(query, e["text"]) \
                        or match_level(query, e["desc"]) \
                        or match_level(query, e.get("icon_label", "")):
                    print(f"FOUND: {display_label(e)!r} {e['bounds']}")
                    return
            n += 1
            if n % 3 == 0:
                ocr = ocr_lines()
                if ocr:
                    for d in ocr:
                        if match_level(query, d["text"]):
                            print(f"FOUND (OCR): {d['text']!r} "
                                  f"@ ({d['cx']},{d['cy']})")
                            return
            time.sleep(1)
        print(f"timeout ({timeout:g}s) waiting for {query!r}")
        sys.exit(1)
    try:
        t = float(args[0])
    except ValueError:
        print("wait <seconds>   OR   wait --until <text> [--timeout N]")
        sys.exit(1)
    time.sleep(t)
    print(f"waited {t:.1f}s")


def cmd_wifi(args):
    a = args[0] if args else "state"
    if a == "on":
        shell("svc", "wifi", "enable")
        print("wifi: on")
    elif a == "off":
        shell("svc", "wifi", "disable")
        print("wifi: off")
    else:
        v = shell("settings", "get", "global", "wifi_on").strip()
        print("wifi:", "on" if v == "1" else v if v else "unknown")


def cmd_bluetooth(args):
    a = args[0] if args else "state"
    if a == "on":
        shell("svc", "bluetooth", "enable")
        print("bluetooth: on")
    elif a == "off":
        shell("svc", "bluetooth", "disable")
        print("bluetooth: off")
    else:
        v = shell("settings", "get", "global", "bluetooth_on").strip()
        print("bluetooth:", "on" if v == "1" else v if v else "unknown")


def _any_match(query, els=None):
    """True if query matches any UI element (or OCR line) on screen."""
    if els is None:
        els = elements()
    for e in els:
        if match_level(query, e["text"]) or match_level(query, e["desc"]) \
                or match_level(query, e.get("icon_label", "")):
            return True
    ocr = ocr_lines()
    if ocr:
        return any(match_level(query, d["text"]) for d in ocr)
    return False


def cmd_verify(args):
    if args and args[0] == "--gone":
        query = " ".join(args[1:]).lower()
        if not query:
            print("verify --gone <text> - poll until the text is gone")
            sys.exit(1)
        deadline = time.time() + 10
        while time.time() < deadline:
            if not _any_match(query):
                print(f"GONE: {query!r} no longer on screen")
                return
            time.sleep(0.5)
        print(f"TIMEOUT: {query!r} still on screen after 10s")
        sys.exit(1)
    query = " ".join(args).lower()
    if not query:
        print("verify <text> - check if the text is on screen")
        sys.exit(1)
    for e in elements():
        if match_level(query, e["text"]) or match_level(query, e["desc"]) \
                or match_level(query, e.get("icon_label", "")):
            print(f"FOUND: {display_label(e)!r} {e['bounds']}")
            return
    ocr = ocr_lines()
    if ocr:
        for d in ocr:
            if match_level(query, d["text"]):
                print(f"FOUND (OCR): {d['text']!r} @ ({d['cx']},{d['cy']})")
                return
    print(f"NOT FOUND: {query!r}")
    sys.exit(1)


def cmd_signal():
    out = shell("dumpsys", "telephony.registry")
    net = re.search(r"mNetworkType=(\w+)", out)
    name = net.group(1) if net else "?"
    m = re.search(r"mLte=CellSignalStrengthLte:.*?rsrp=(-?\d+)", out)
    dbm = ""
    if m:
        dbm = f" rsrp {m.group(1)} dBm"
    else:
        m2 = re.search(r"rssi=(-?\d+)", out)
        if m2:
            dbm = f" rssi {m2.group(1)} dBm"
    conn = re.search(r"mDataConnectionState=(\d+)", out)
    state = {0: "disconnected", 2: "connected"}.get(
        int(conn.group(1)), "?") if conn else ""
    print(f"network: {name}  data: {state}{dbm}")


def cmd_data(args):
    a = args[0] if args else "state"
    if a == "on":
        shell("settings", "put", "global", "mobile_data", "1")
        print("mobile data: on")
    elif a == "off":
        shell("settings", "put", "global", "mobile_data", "0")
        print("mobile data: off")
    else:
        v = shell("settings", "get", "global", "mobile_data").strip()
        print("mobile data:", "on" if v == "1" else v if v else "unknown")


def cmd_storage():
    print(shell("df", "-h", "/data", "/sdcard", "/system").rstrip())


def cmd_mem():
    out = shell("cat", "/proc/meminfo")
    vals = {}
    for key in ("MemTotal", "MemFree", "MemAvailable"):
        m = re.search(rf"^{key}:\s*(\d+) kB", out, re.M)
        if m:
            vals[key] = int(m.group(1)) // 1024
    if vals:
        print(f"mem total: {vals.get('MemTotal', '?')} MB")
        if "MemAvailable" in vals:
            print(f"mem available: {vals['MemAvailable']} MB")
        else:
            print(f"mem free: {vals.get('MemFree', '?')} MB")
    else:
        print("mem: unknown")


def cmd_push(args):
    if len(args) != 2:
        print("push <local-file> <device-path>")
        sys.exit(1)
    r = adb("push", args[0], args[1])
    print(r.stdout.strip() or r.stderr.strip() or "pushed")


def cmd_pull(args):
    if not args:
        print("pull <device-path> [local-path]")
        sys.exit(1)
    r = adb("pull", args[0], args[1] if len(args) > 1 else ".")
    print(r.stdout.strip() or r.stderr.strip() or "pulled")


def cmd_ls(args):
    path = (args[0] if args else "/sdcard").rstrip("/") or "/"
    out = shell("ls", "-la", path)
    if len(out.strip().splitlines()) <= 1:
        out = shell("ls", "-la", path + "/")
    print(out.rstrip())


def cmd_cpu():
    lines = shell("top", "-n", "1", "-b").splitlines()
    if not lines:
        return
    i = 0
    for idx, line in enumerate(lines):
        if re.match(r"\s*PID\s+USER\b", line):
            i = idx
            break
    rows = lines[i + 1:]
    rows = [r for r in rows if not re.search(r"\btop -n 1 -b\b", r)]
    print("\n".join([lines[i]] + rows[:10]))


def cmd_time():
    print("phone time:", shell("date").strip())


def cmd_dpi(args):
    if args:
        print("dpi is read-only in this tool (avoid breaking layout/coords)")
        sys.exit(1)
    out = shell("wm", "density")
    phys = re.search(r"Physical density:\s*(\d+)", out)
    ovr = re.search(r"Override density:\s*(\d+)", out)
    if phys:
        extra = f" (override {ovr.group(1)})" if ovr else ""
        print("density:", phys.group(1) + extra)
    else:
        print("density: unknown")


# ---- main ----

READ_ONLY = {"cmd", "status", "shot", "ocr", "ui", "find", "sight",
             "apps", "info", "battery", "ping", "clipboard", "clip", "notify",
             "record", "top", "help", "state", "who", "wait", "list",
             "verify", "signal", "storage", "mem", "ls", "cpu", "time",
             "dpi", "pull", "run"}


def translate(cmd, args):
    """Resolve command aliases to their real handler. Used by main() and run()."""
    if cmd == "clip":
        return "clipboard", args
    if cmd == "home":
        return "key", ["home"]
    if cmd == "back":
        return "key", ["back"]
    if cmd == "recents":
        return "key", ["recents"]
    if cmd == "rotate":
        return "orient", args
    if cmd in ("screenshot", "screencap"):
        return "shot", args
    if cmd == "type":
        return "text", args
    if cmd == "bt":
        return "bluetooth", args
    if cmd == "url":
        return "open", args
    if cmd == "sleep":
        return "wait", args
    if cmd == "ram":
        return "mem", args
    return cmd, args


def cmd_run(args):
    if not args:
        print("run <script-file> - execute openadb commands, one per line")
        sys.exit(1)
    path = args[0]
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError as e:
        print(f"run: cannot read {path}: {e}")
        sys.exit(1)
    n = 0
    for n, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = shlex.split(line)
        if not parts:
            continue
        cmd, cargs = translate(parts[0], parts[1:])
        print(f">> [{n}] {line}")
        if cmd in ("help", "list"):
            print_help(cargs[0] if cargs else None)
            continue
        auto = (cmd not in READ_ONLY and bool(cargs) and cargs[-1] == "--sight")
        if auto:
            cargs = cargs[:-1]
            before_els = elements()
            before_app = focused_app()
        dispatch(cmd, cargs)
        if auto:
            diff_section(before_els, before_app)
    print(f"run complete ({n} lines)")


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "-help"):
        print_help(sys.argv[2] if len(sys.argv) > 2 else None)
        return
    if sys.argv[1] in ("-help-human", "--help-human"):
        print(HUMAN_HELP)
        return
    cmd = sys.argv[1]
    args = sys.argv[2:]
    if cmd == "help":
        print_help(args[0] if args else None)
        return
    if args and args[0] in ("-h", "--help", "-help"):
        print_help(cmd)
        return
    if cmd == "list":
        print_help()
        return
    cmd, args = translate(cmd, args)
    if cmd == "sight" and args and args[0] in ("--brief", "--json"):
        if args[0] == "--json":
            print(json.dumps(sight_json(), indent=2))
        else:
            cmd_sight(brief=True)
        return
    auto = (cmd not in READ_ONLY and bool(args) and args[-1] == "--sight")
    if auto:
        args = args[:-1]

    if cmd not in ("ping", "status"):
        check_device()

    try:
        _run(cmd, args, auto)
    except KeyboardInterrupt:
        sys.exit(0)
    except SystemExit:
        raise
    except Exception as e:
        print(f"error: {e} (device may be offline or asleep - run `ping` to "
              "check)")
        sys.exit(1)


def diff_section(before_els, before_app):
    """Print the --sight auto-confirm diff, then the current screen."""
    time.sleep(0.8)
    after_els = elements()
    after_app = focused_app()
    lines, changed = diff_report(before_els, after_els, before_app, after_app)
    print("\n===== CHANGED =====")
    if changed:
        for line in lines:
            print(line)
    else:
        print("  (nothing detectably changed - the action may not have "
              "registered, or the screen hasn't updated yet. Try `sight` "
              "to look directly, or `wait --until \"<expected text>\"`.)")
    print("\n===== SCREEN NOW =====")
    cmd_sight()


def _run(cmd, args, auto):
    before_els = elements() if auto else None
    before_app = focused_app() if auto else None
    dispatch(cmd, args)
    if auto:
        diff_section(before_els, before_app)


def dispatch(cmd, args):
    if cmd == "status":
        cmd_status()
    elif cmd == "sight":
        if args and args[0] == "--json":
            print(json.dumps(sight_json(), indent=2))
        elif args and args[0] == "--brief":
            cmd_sight(brief=True)
        else:
            cmd_sight()
    elif cmd == "ui":
        cmd_ui(args[0] if args else None)
    elif cmd == "find":
        cmd_find(" ".join(args))
    elif cmd == "top":
        cmd_top()
    elif cmd == "state":
        cmd_state(args)
    elif cmd == "who":
        cmd_who()
    elif cmd == "wait":
        cmd_wait(args)
    elif cmd == "verify":
        cmd_verify(args)
    elif cmd == "signal":
        cmd_signal()
    elif cmd == "storage":
        cmd_storage()
    elif cmd == "mem":
        cmd_mem()
    elif cmd == "push":
        cmd_push(args)
    elif cmd == "pull":
        cmd_pull(args)
    elif cmd == "ls":
        cmd_ls(args)
    elif cmd == "cpu":
        cmd_cpu()
    elif cmd == "time":
        cmd_time()
    elif cmd == "dpi":
        cmd_dpi(args)
    elif cmd == "tap":
        cmd_tap(args)
    elif cmd == "longtap":
        cmd_longtap(args)
    elif cmd == "doubletap":
        cmd_doubletap(args)
    elif cmd == "swipe":
        cmd_swipe(args)
    elif cmd == "scroll":
        cmd_scroll(args)
    elif cmd == "text":
        cmd_text(args)
    elif cmd == "key":
        cmd_key(args[0] if args else None)
    elif cmd == "open":
        cmd_open(" ".join(args))
    elif cmd == "close":
        cmd_close(args[0] if args else None)
    elif cmd == "uninstall":
        cmd_uninstall(args[0] if args else None)
    elif cmd == "clear":
        cmd_clear(args[0] if args else None)
    elif cmd == "run":
        cmd_run(args)
    elif cmd == "clipboard":
        cmd_clipboard(args)
    elif cmd == "notify":
        cmd_notify()
    elif cmd == "apps":
        cmd_apps(args[0] if args else None)
    elif cmd == "info":
        cmd_info(args[0] if args else None)
    elif cmd == "battery":
        cmd_battery()
    elif cmd == "ping":
        cmd_ping()
    elif cmd == "volume":
        cmd_volume(args)
    elif cmd == "brightness":
        cmd_brightness(args)
    elif cmd == "screen":
        cmd_screen(args)
    elif cmd == "wake":
        cmd_wake()
    elif cmd == "lock":
        cmd_lock()
    elif cmd == "unlock":
        cmd_unlock()
    elif cmd == "orient":
        cmd_orient(args)
    elif cmd == "dnd":
        cmd_dnd(args)
    elif cmd == "airplane":
        cmd_airplane(args)
    elif cmd == "wifi":
        cmd_wifi(args)
    elif cmd == "bluetooth":
        cmd_bluetooth(args)
    elif cmd == "data":
        cmd_data(args)
    elif cmd == "record":
        cmd_record(args[0] if args else None)
    elif cmd == "shot":
        cmd_shot(args)
    elif cmd == "ocr":
        cmd_ocr(args[0] if args else None)
    elif cmd == "cmd":
        r = adb("shell", *args)
        print(r.stdout, end="")
        if r.stderr.strip():
            print(r.stderr, end="")
    else:
        print("unknown command:", cmd)
        print_help()
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
