"""Guided troubleshooting playbooks (pure logic, no Qt).

A playbook is a list of steps. Each step runs one Junos command, then
analyzes the output into a status (ok / warn / fail / info) and a plain-English
finding. Facts are collected in `ctx`, and the playbook's verdict function
turns them into a headline and recommended actions.
"""
import re
from dataclasses import dataclass, field
from typing import Callable, List

from .parsers import (evaluate_optics, parse_extensive, parse_lldp, parse_optics, parse_terse, parse_ago,
                      fmt_age, split_port)

OK, WARN, FAIL, INFO = "ok", "warn", "fail", "info"


@dataclass
class Step:
    title: str
    command: str                                   # {if} is replaced by the interface
    analyze: Callable                              # (output, ctx) -> (status, finding)


@dataclass
class Playbook:
    key: str
    name: str
    description: str
    steps: List[Step]
    verdict: Callable                              # ctx -> (status, headline, [advice])


@dataclass
class StepResult:
    title: str
    command: str
    output: str
    status: str
    finding: str


@dataclass
class PlaybookRun:
    playbook: Playbook
    iface: str
    warn_default: float = -12.0
    alarm_default: float = -15.0
    ctx: dict = field(default_factory=dict)
    results: List[StepResult] = field(default_factory=list)

    def __post_init__(self):
        self.ctx.update(iface=self.iface, warn_default=self.warn_default, alarm_default=self.alarm_default)

    @property
    def done(self):
        return len(self.results) >= len(self.playbook.steps)

    def next_command(self):
        if self.done:
            return None
        return self.playbook.steps[len(self.results)].command.replace("{if}", self.iface)

    def current_step(self):
        return None if self.done else self.playbook.steps[len(self.results)]

    def feed(self, output: str) -> StepResult:
        step = self.playbook.steps[len(self.results)]
        try:
            if re.search(r"^\s*(error:|syntax error|unknown command)", output, re.I | re.M):
                status, finding = FAIL, "Junos returned an error: " + output.strip().splitlines()[0][:160]
                self.ctx.setdefault("errors", []).append(step.title)
            else:
                status, finding = step.analyze(output, self.ctx)
        except Exception as e:  # noqa: BLE001
            status, finding = INFO, f"Could not analyze this output ({e})"
        r = StepResult(step.title, step.command.replace("{if}", self.iface), output, status, finding)
        self.results.append(r)
        return r

    def verdict(self):
        try:
            return self.playbook.verdict(self.ctx)
        except Exception as e:  # noqa: BLE001
            return INFO, "Could not reach a verdict", [str(e)]


# ================================================================== steps
def a_state(out, ctx):
    t = parse_terse(out).get(ctx["iface"])
    if t is None:
        if not out.strip():
            ctx["missing"] = True
            return FAIL, "The switch returned nothing for this interface – check the name."
        return INFO, "Couldn't read the admin/link state from the output."
    ctx["admin"], ctx["link"] = t["admin"], t["link"]
    if t["admin"] == "down":
        return FAIL, "The port is administratively disabled (turned off in the configuration)."
    if t["link"] == "down":
        return FAIL, "The port is enabled (admin up) but has no link."
    return OK, "The port is enabled and the link is up."


def a_optics(out, ctx):
    data = parse_optics(out)
    entry = data.get(ctx["iface"]) or (next(iter(data.values())) if len(data) == 1 else None)
    if not entry or (not entry["rx"] and not entry["tx"]):
        ctx["optic"] = False
        return WARN, ("No optic diagnostics returned. Either no transceiver is installed, it's a DAC/copper "
                      "cable, or the optic doesn't report light levels.")
    ctx["optic"] = True
    health, worst, reason = evaluate_optics(entry, ctx["warn_default"], ctx["alarm_default"])
    tx = min(entry["tx"]) if entry["tx"] else None
    ctx.update(health=health, rx=worst, tx=tx, thr=entry["thr"])
    txt = f"Rx {worst:.2f} dBm" if worst is not None else "Rx –"
    txt += f", Tx {tx:.2f} dBm" if tx is not None else ""
    if tx is not None and tx <= -30:
        ctx["tx_dead"] = True
        return FAIL, f"{txt}. This optic is not transmitting any light."
    status = {"OK": OK, "Warning": WARN, "Critical": FAIL, "No Light": FAIL}.get(health, INFO)
    meaning = {"OK": "light levels are healthy", "Warning": "receive light is weak",
               "Critical": "receive light is below the alarm level", "No Light": "no light is being received",
               "N/A": "no receive reading"}.get(health, reason)
    return status, f"{txt} – {meaning} ({reason})."


def a_errors(out, ctx):
    d = parse_extensive(out)
    ctx["ext"] = d
    crc, framing = d.get("crc_rx", 0) or 0, d.get("in_framing errors", 0) or 0
    in_err, carrier = d.get("in_errors", 0) or 0, d.get("out_carrier transitions")
    ctx.update(crc=crc, framing=framing, in_errors=in_err, carrier=carrier)
    lf = d.get("last_flapped", "")
    ctx["flap_age"] = parse_ago(lf) if lf else None
    bits = []
    if d.get("speed"):
        bits.append(f"speed {d['speed']}")
    if carrier is not None:
        bits.append(f"{carrier} carrier transitions (link drops) since counters were cleared")
    if lf:
        bits.append(f"last flapped {fmt_age(ctx['flap_age']) if ctx['flap_age'] is not None else lf}")
    extra = ("; " + "; ".join(bits)) if bits else ""
    if crc or framing:
        return WARN, f"{crc:,} CRC and {framing:,} framing errors – frames are arriving corrupted{extra}."
    if in_err:
        return WARN, f"{in_err:,} input errors (no CRC/framing errors){extra}."
    return OK, f"No input errors{extra}."


def a_lldp(out, ctx):
    d = parse_lldp(out, ctx["iface"])
    ctx["lldp"] = d
    if d:
        return OK, f"Neighbor is {d.get('system', 'unknown')} on port {d.get('port_id', '?')}."
    if ctx.get("link") == "down":
        return INFO, "No LLDP neighbor (expected while the link is down)."
    return WARN, "No LLDP neighbor seen. The far end may not run LLDP, or it isn't a network device."


def a_logs(out, ctx):
    lines = [ln for ln in out.splitlines() if ln.strip()]
    downs = [ln for ln in lines if re.search(r"LINK_DOWN|link down|ifOperStatus down|Down$", ln, re.I)]
    ups = [ln for ln in lines if re.search(r"LINK_UP|link up|ifOperStatus up", ln, re.I)]
    lacp = [ln for ln in lines if "LACP" in ln.upper()]
    ctx.update(log_downs=len(downs), log_ups=len(ups), log_lacp=len(lacp))
    if not lines:
        return OK, "No recent log messages mention this interface."
    last = lines[-1][:15] if re.match(r"^[A-Z][a-z]{2}\s+\d+\s+[\d:]+", lines[-1]) else ""
    msg = f"{len(downs)} link-down and {len(ups)} link-up messages in the last {len(lines)} log lines"
    if lacp:
        msg += f", {len(lacp)} LACP messages"
    if last:
        msg += f"; most recent at {last}"
    return (WARN if len(downs) >= 3 else INFO), msg + "."


S_STATE = Step("Admin and link state", "show interfaces {if} terse | no-more", a_state)
S_OPTICS = Step("Optic and light levels", "show interfaces diagnostics optics {if} | no-more", a_optics)
S_ERRORS = Step("Error counters and flap history",
                'show interfaces {if} extensive | match "Physical interface|Speed|MTU|rate|errors|Errors|'
                'transitions|Last flapped" | no-more', a_errors)
S_LLDP = Step("Far-end neighbor (LLDP)", "show lldp neighbors interface {if} | no-more", a_lldp)
S_LOGS = Step("Recent log messages", "show log messages | match {if} | last 30 | no-more", a_logs)

CLEAN = "Clean both fiber connectors and the optic ports with a proper fiber cleaner, then reseat them."


# ================================================================ verdicts
def _missing(ctx):
    return (FAIL, "Interface not found",
            ["Check the interface name (for example xe-0/0/1 vs ge-0/0/1).",
             "Run 'show interfaces terse' to list the ports on this switch."])


def v_down(ctx):
    if ctx.get("missing"):
        return _missing(ctx)
    i = ctx["iface"]
    if ctx.get("admin") == "down":
        return (WARN, "The port is administratively disabled",
                [f"It is turned off in the configuration ('set interfaces {i} disable').",
                 f"If it should be in service: configure → delete interfaces {i} disable → commit.",
                 "Check the port description and ticket history before enabling it."])
    if ctx.get("link") == "up":
        adv = ["Nothing is wrong right now."]
        if ctx.get("flap_age") is not None and ctx["flap_age"] < 86400:
            adv.append(f"It last flapped {fmt_age(ctx['flap_age'])}. Run 'Why is this port flapping?' if it keeps happening.")
        return OK, "The port is up and has link", adv
    if ctx.get("optic") is False:
        sp = split_port(i)
        pic_cmd = f"show chassis pic fpc-slot {sp[1]} pic-slot {sp[2]}" if sp else "show chassis hardware"
        return (FAIL, "No optic detected (or the optic doesn't report light levels)",
                ["Check that the optic is fully seated in the port.",
                 "If this is a DAC/copper port, check the cable at both ends.",
                 f"Run '{pic_cmd}' to see which optics the switch detects."])
    if ctx.get("tx_dead"):
        return (FAIL, "This switch's optic is not transmitting",
                ["The laser in the local optic is off or has failed. Replace the optic.",
                 "Once it's replaced, check the far end receives light."])
    rx, health = ctx.get("rx"), ctx.get("health")
    if health == "No Light":
        return (FAIL, "No light is reaching this port from the far end",
                ["Check the far-end port is up and not disabled.",
                 "Check the fiber patch: correct ports, Tx/Rx not swapped, no breaks or tight bends.",
                 CLEAN,
                 "If the far end shows good Tx light, test the fiber path (patch panels, splices)."])
    if health == "Critical":
        return (FAIL, f"Received light is too low for a link ({rx:.2f} dBm)",
                [CLEAN, "Check patch panels, splices and jumpers along the path for loss.",
                 "Check both optics are the same type (LR/SR/ER, wavelength) and the span isn't too long."])
    if health == "Warning":
        return (WARN, f"Light is weak ({rx:.2f} dBm) and there is no link",
                [CLEAN, "Check both ends use matching optic types and speed."])
    return (WARN, "Light looks fine, but there is no link",
            ["Check both ends are set to the same speed (e.g. 10G vs 1G) and use matching optic types.",
             "Check the far-end port isn't disabled or error-disabled.",
             "Check the logs for LACP or other protocol errors.",
             "Swap the optic, then the patch cable, to isolate a faulty part."])


def v_flap(ctx):
    if ctx.get("missing"):
        return _missing(ctx)
    age, carrier = ctx.get("flap_age"), ctx.get("carrier")
    when = f" (last flap {fmt_age(age)})" if age is not None else ""
    if ctx.get("health") in ("Warning", "Critical", "No Light"):
        return (WARN, f"Weak or unstable light is the most likely cause{when}",
                [CLEAN, "Check patch panels and jumpers for loose connections or tight bends.",
                 "If light stays weak after cleaning, swap the optic, then the far-end optic."])
    if ctx.get("crc") or ctx.get("framing"):
        return (WARN, f"Physical-layer errors are present{when}",
                [CLEAN, "Swap the patch cable, then the optic, to find the faulty part.",
                 f"Clear the counters (clear interfaces statistics {ctx['iface']}) and watch whether errors return."])
    if ctx.get("log_lacp"):
        return (WARN, f"LACP messages suggest a LAG/bundle problem{when}",
                ["Check the LAG configuration matches on both ends (LACP active/passive, members).",
                 "Check the far-end device logs for the same time."])
    if ctx.get("log_downs", 0) >= 2 or (age is not None and age < 3600):
        return (WARN, f"The link is bouncing, but light and errors look normal here{when}",
                ["Check the far-end device logs. It may be resetting the port.",
                 "Check for power or maintenance work at the far end.",
                 "If it continues, swap the optic and the patch cable to isolate."])
    extra = f" Carrier transitions: {carrier}." if carrier is not None else ""
    return OK, f"No current signs of flapping{when}", ["Light, errors and logs look normal." + extra]


def v_errors(ctx):
    if ctx.get("missing"):
        return _missing(ctx)
    crc, framing, inerr = ctx.get("crc", 0), ctx.get("framing", 0), ctx.get("in_errors", 0)
    if (crc or framing) and ctx.get("health") in ("Warning", "Critical"):
        return (WARN, "The errors are most likely caused by low light",
                [CLEAN, "Check patch panels and jumpers along the path.", "Replace the optic if light stays low."])
    if crc or framing:
        return (WARN, "CRC/framing errors with healthy light",
                ["A dirty or damaged connector is still possible. " + CLEAN,
                 "Swap the optic, then the patch cable, to isolate the fault.",
                 "Check the far end for output errors or a failing optic.",
                 f"Clear counters (clear interfaces statistics {ctx['iface']}) and check whether they keep rising."])
    if inerr:
        return (INFO, "Input errors without CRC errors",
                ["These are usually drops from congestion, policing or MTU mismatches rather than a physical fault.",
                 "Check the MTU matches on both ends."])
    return OK, "No errors on this port", ["Counters are clean."]


PLAYBOOKS = [
    Playbook("down", "Why is this port down?",
             "Checks admin state, the optic, light levels, the far-end neighbor and the logs, then explains "
             "the most likely cause.", [S_STATE, S_OPTICS, S_ERRORS, S_LLDP, S_LOGS], v_down),
    Playbook("flap", "Why is this port flapping?",
             "Looks at flap history, light stability, physical errors and log events to find why a link "
             "keeps going up and down.", [S_STATE, S_ERRORS, S_OPTICS, S_LOGS, S_LLDP], v_flap),
    Playbook("errors", "Why does this port have errors?",
             "Reads the error counters and light levels to tell a fiber/optic problem from congestion.",
             [S_STATE, S_ERRORS, S_OPTICS], v_errors),
]


def get_playbook(key):
    return next(p for p in PLAYBOOKS if p.key == key)
