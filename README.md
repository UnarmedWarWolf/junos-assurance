# Junos Assurance

A desktop GUI (Windows and macOS) for reaching Junos switches through a jump host, styled after Cisco DNA Center's
Assurance view. Built for ISP engineers who are new to the Junos CLI.

## Run it

### Windows
* **With Python installed:** double-click `run_windows.bat`. It finds a working Python 3.9 or newer.
  The first run installs the required packages for your user account; after that the app opens
  straight away. If something goes wrong, run `run_windows.bat console` from a Command Prompt to keep
  the error messages visible. If Python is missing, install it from python.org and tick
  **"Add python.exe to PATH"** during setup.
* **Without Python on each PC:** run `build_windows_exe.bat` once on any Windows machine that has
  Python. It produces `dist\JunosAssurance\JunosAssurance.exe`. Zip the `dist\JunosAssurance`
  folder and share it; engineers just unzip it and run the `.exe`.

Settings are stored in `%APPDATA%\JunosAssurance\`. Passwords go into Windows Credential Manager
(entries named *JunosAssurance*). Unexpected errors are written to `error.log` in the same folder.

### macOS
Double-click `run_mac.command`. If macOS blocks it, right-click and choose **Open**. Settings are
stored in `~/.junos_assurance/` and passwords in the Keychain.

### Manual
```
py -3 -m pip install --user -r requirements.txt
py -3 main.py
```
Requires Python 3.9 or newer.

## Connecting through the jump host

The jump host (bastion) is in its own domain. The app connects the same way as `ssh -J`:

1. It logs in to the **jump host** with your **P-Number** and **password + VIP code**.
2. It opens a tunnel through the jump host to the switch on port 22. The jump host looks up the switch
   name, so names in the jump host's domain work.
3. It logs in to the **switch** inside that tunnel. By default it uses the same P-Number and password.
   If the switches use a different account, tick **Switch uses a different login** and enter the
   switch username and password. If the switch rejects the login, the VIP box opens so you can retry
   with password + a new code.
4. When the Junos prompt (`P1234567@switch>`) appears, the dashboard starts filling in.

Steps:
1. Enter the **Jump host** (`host` or `host:port`), **Username (P-Number)**, **Password** and the
   **Switch hostname**. These are remembered, along with your recent switch names. If
   **Remember passwords** is ticked, passwords are saved in the system keychain, never in a file.
2. Click **Connect**, or press Enter in the hostname box. Type your VIP code in the small box and press
   Enter.

**⚙ Settings → Connection**
| Setting | Use |
|---|---|
| Connection method | **Jump host** (default) tunnels straight to the switch. **Bastion shell** logs in to a shell on the bastion and types `ssh <switch>` for you. (Automatic falls back to this when the jump host blocks tunnels.) |
| Jump host login name | `{username}` by default. Use `DOMAIN\{username}` or `{username}@jump.example.com` if the jump host domain needs it. |
| Switch domain suffix | Added to short switch names. For example, `net.example.com` turns `qfx-01` into `qfx-01.net.example.com`. Leave it blank if the jump host resolves short names. |
| Switch login | *Password only* (you're asked for a VIP code if it's rejected) or *Password + a new VIP code* every time. |

## Layout

```
┌ Header: brand · breadcrumb ··········· connection pill · 🔔 alerts · ☾ dark mode · user · ⚙ ┐
│ Icon │ Side panel (click the icon │ Device tabs   [qfx-01 ●] [edw-02 ●]  [+ New]           │
│ menu │ again to collapse it)      │  Health ring · KPI tiles                              │
│      │ Connect · Devices ·        │  Port map                                             │
│      │ Commands · Monitor         │  Flap list │ Admin up · Link down │ Port health        │
│      │                            │  CLI │ Automation output              │ Interface 360  │
└──────┴────────────────────────────┴───────────────────────────────────────────────────────┘
```

The left icon menu opens one panel at a time. Click the same icon again to collapse it and give the
dashboard more room.

| Panel | What's in it |
|---|---|
| **Connect** | Jump host, P-Number, password, optional separate switch login, switch hostname. |
| **Devices** | Your saved switch list. Search by name, site, role or tags. Favorites (★) are pinned to the top. A colored dot shows each switch's last health score. Double-click a switch to connect. You can add or edit switches, or import/export them as a CSV file with the columns `hostname, site, role, tags, notes`. |
| **Commands** | The automation command drop-down, the troubleshooting playbooks, and buttons to save or explain the last output. |
| **Monitor** | Background refresh controls, before/after snapshots, the alert list and session-log settings. |

## Multiple switches in tabs

Every connection opens in its own tab, with a colored dot showing its health. Connect opens a new tab
if the current one is already connected. Use **+ New** for another switch. Each tab keeps its own
session, dashboard, CLI and background checks, so you can watch both ends of a link side by side.

## Dashboard (per tab)

* **Health score ring:** 0–100, worked out from enabled ports without link, weak or critical optics
  on live links, and recent flaps. **Healthy** is 90+, **Fair** is 70–89 and **Poor** is below 70.
  Hover over the ring to see what lowered the score.
* **Port Map:** a front-panel view of the switch, one block per FPC/PIC, with even ports on top and
  odd ports below like the real faceplate. **Green** = up, **amber** = up but optics are weak,
  **red** = admin up / link down, **gray** = disabled. A red or amber dot means the port flapped in
  the last hour or within the flap window. Hover over a port for a summary, or click it to open
  Interface 360.
* **Flap List, Admin Up · Link Down, Port Health (Optics):** the always-on health tables. The optics
  table has an **Rx trend** column (for example `▼ 2.3 dB`) showing how much the receive light changed
  over the trend window.
* These refresh in the background every 120 s (configurable). Background commands share a queue
  with your own commands, so CLI output never gets mixed up. **Double-click** any row to open that
  port in Interface 360.

## Interface 360

A side panel for one port, showing:
* admin, link, health and recent-flap status
* **troubleshooting buttons:** "Why is it down?", "Why is it flapping?" and "Why errors?"
* an Rx light gauge against the optic's own warning and alarm levels, plus Tx and per-lane readings
* **light history:** a sparkline of Rx over the last 72 hours with the change over the trend window
* speed, MTU, traffic rates, input, CRC, framing and output errors, and carrier transitions
* the LLDP neighbor and the last 15 log lines for the port
* buttons that run the extensive, optics and log commands in the CLI
* **Copy ticket note**, which puts a ready-to-paste summary on the clipboard

## Light-level history and trends

Every background refresh saves each port's Rx/Tx light to a local database (`history.db` in the
settings folder, kept for 30 days by default). That history drives the sparklines, the Rx trend
column and the **light degrading** alert. A slowly dropping Rx, for example from a dirty connector
or a failing optic, shows up days before the port goes down.

## Troubleshooting playbooks

Guided checks that run the right commands in order and give a plain-English verdict:

| Playbook | Checks | Example verdict |
|---|---|---|
| **Why is this port down?** | Admin state, optic present, Rx/Tx light, errors and flap history, LLDP neighbor, logs | "No light is reaching this port from the far end", followed by steps: check the far-end port, check the fiber patch, clean the connectors, test the fiber path |
| **Why is this port flapping?** | Flap history, light stability, CRC/framing errors, LACP and link log events | "Weak or unstable light is the most likely cause" |
| **Why does this port have errors?** | Error counters vs. light levels | "CRC/framing errors with healthy light", followed by steps: clean, swap the optic, then the patch cable |

Every step shows its command and raw output, so engineers learn the process. **Copy report** puts the
whole result on the clipboard for a ticket. You can start a playbook from Interface 360, from the
Commands panel, or from the command drop-down.

## Before/after snapshots

In **Monitor → Take snapshot now**, the app refreshes and saves every port's state, light level and
last flap. After maintenance, open **Snapshots & compare… → Compare with now** (or compare any two
snapshots). The result lists exactly what changed: ports that went down or came up, admin changes,
new flaps, Rx changes of 1 dB or more, and optics that disappeared. You can export it to Excel.

## Desktop alerts

While the app is open, it raises an alert when:
* a port flaps
* a port that was up goes down
* an optic drops from OK to warning or critical
* an Rx trend drops by more than the configured amount (2 dB by default)

Alerts appear under the 🔔 bell and in the Monitor panel. When the app is in the background (or the
alert is for a different tab), they also appear as a Windows notification. You can turn notifications
off in Monitor or Settings.

## Session logs

Each session is saved automatically to `Documents\JunosAssurance Logs\<date>\<switch>_<time>.log`,
with a timestamp on every command you send. This is useful for audits and shift handovers. Use
**Monitor → Open logs folder** to find them, or change the folder in Settings.

## CLI

Always visible. Type any command and press Enter.
* **Tab** completes commands (`sh` + Tab gives `show …`) and interface names (`show interfaces xe-0/0/1` + Tab)
* **↑/↓** for history, end a line with `?` for Junos help, **Ctrl+C** stops a running command
* **Ctrl+F** finds text in the output (Enter for next, Shift+Enter for previous); all matches are highlighted
* The **Filter lines** box shows only matching lines, live, like `| match` but without re-running the
  command. `down|flap` matches either word.
* **Explain** annotates the last command's output in plain English. For example, "Carrier
  transitions: 7" becomes "The link has dropped 7 times since the counters were last cleared", and
  an Rx reading gets a verdict on whether it's healthy, weak or no light.
* **Save ▾** saves the session as a Word (.docx) or Excel (.xlsx) file, keeping the colors.

Colors: **red** = down/failed/error · **amber** = warning · **green** = up/enabled/OK ·
**purple** = interface names (xe-0/0/0, ge-1/0/13, et-0/0/48, ae0…).

## Automation Commands

The **Select a command** drop-down groups commands by category: Basic, Flaps, Optics Diagnostics,
Chassis / Hardware, Layer 2 / Routing, Logs, Connectivity and Troubleshooting Playbooks. Hover over a
command to see what it does. Commands marked `…` need a value, such as an interface name. A pop-up
explains the value and offers interface autocomplete. If the value is optional, you can choose
**Run as is** to skip it. Output appears in the **Automation Output** panel, which has its own filter,
**Explain**, **Run again** and **Save to Excel…** buttons. The Excel file has a *Table* sheet split
into columns and a *Raw* sheet.

To add commands, edit `CATALOG` in `app/commands.py`. Use `{name}` for a required value and
`[[ ... {name}]]` for an optional part.

## Dark mode

Click **☾** in the header (or use Settings → Logs & Appearance) to switch between the white default
theme and a dark theme for night shifts. The change applies instantly to every open tab.

## Files

```
main.py                start-up
run_windows.bat        Windows launcher
build_windows_exe.bat  build a stand-alone .exe
run_mac.command        macOS launcher
app/main_window.py     window shell: header, icon menu, side panels, tabs, alerts
app/device_tab.py      one switch: dashboard, health score, alerts, snapshots, CLI, Interface 360
app/ssh_session.py     jump-host tunnel / bastion shell, command queue
app/commands.py        automation command catalog
app/playbooks.py       troubleshooting playbooks and verdicts
app/explainer.py       "Explain this output" rules
app/parsers.py         parsing for terse / descriptions / flaps / optics / extensive / LLDP
app/history.py         light-level history and snapshots (SQLite) + snapshot diff
app/inventory.py       saved device list + CSV import/export
app/session_log.py     automatic session logs
app/exporters.py       Word and Excel export
app/theme.py           light/dark colors, highlighting rules, stylesheet
app/widgets.py         tiles, health ring, sparkline, tables, CLI, find/filter, dialogs
app/dialogs.py         explain, playbook, snapshot and device dialogs
app/portmap.py         port map, light gauge, Interface 360 panel
app/config.py          saved settings and keychain password
```
