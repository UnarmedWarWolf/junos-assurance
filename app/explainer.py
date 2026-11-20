"""'Explain this output' – annotates Junos command output in plain English (rules-based, no Qt).

explain(text) -> {"summary": [(text, key)], "notes": [(line_no, line, meaning, key)]}
key is a color key: "up" / "warning" / "down" / None.
"""
import re

from .parsers import _dbm, parse_ago, fmt_age

R = re.compile


def _rx_meaning(dbm):
    if dbm is None:
        return "", None
    if dbm <= -30:
        return "No light at all. The far end isn't sending, or the fiber is broken/disconnected.", "down"
    if dbm < -14:
        return "Very low. Most 10G optics lose the link around here. Clean the fiber or check the path.", "down"
    if dbm < -10:
        return "Weak but usually workable. Worth cleaning connectors before it gets worse.", "warning"
    if dbm > 2:
        return "Very strong. On short runs this can overload the receiver (may need an attenuator).", "warning"
    return "Healthy receive level.", "up"


def _n(s):
    return int(s.replace(",", ""))


def _rule_list():
    """(regex, function(match, line) -> (meaning, key) or None)"""
    rules = []

    def rule(pattern, flags=re.I):
        def deco(fn):
            rules.append((R(pattern, flags), fn))
            return fn
        return deco

    @rule(r"Physical interface:\s*([^,\s]+),\s*([^,]+),\s*Physical link is (\w+)")
    def _phys(m, _l):
        name, admin, link = m.group(1), m.group(2).strip(), m.group(3)
        if "down" in admin.lower() or "disabled" in admin.lower():
            return f"{name} is turned off in the configuration (administratively down).", "warning"
        if link.lower() == "up":
            return f"{name} is enabled and the link is up: it sees the far end.", "up"
        return f"{name} is enabled but has NO link. The far end isn't seen (check light, cable, far-end port).", "down"

    @rule(r"Last flapped\s*:\s*(.*)")
    def _flap(m, _l):
        v = m.group(1).strip()
        if v.lower().startswith("never"):
            return "The link has never changed state since the switch booted.", "up"
        age = parse_ago(v)
        if age is None:
            return f"The last time the link went down or up: {v}.", None
        key = "down" if age < 3600 else ("warning" if age < 86400 else None)
        return f"The link last went down/up {fmt_age(age)}.", key

    @rule(r"^\s*Description\s*:\s*(.+)")
    def _desc(m, _l):
        return f"Free-text label set by engineers. Often the circuit/customer: \"{m.group(1).strip()}\".", None

    @rule(r"Speed:\s*([^,\s]+)")
    def _speed(m, _l):
        return f"Configured/negotiated port speed is {m.group(1)}. Both ends must match.", None

    @rule(r"MTU:\s*(\d+)")
    def _mtu(m, _l):
        return f"Largest frame this port will pass: {m.group(1)} bytes. Mismatched MTUs cause drops.", None

    @rule(r"(Input|Output) rate\s*:\s*(\d+)\s*bps\s*\((\d+)\s*pps\)")
    def _rate(m, _l):
        from .parsers import fmt_bps
        d = "receiving" if m.group(1) == "Input" else "sending"
        return f"Right now the port is {d} {fmt_bps(int(m.group(2)))} ({_n(m.group(3)):,} packets/s).", None

    @rule(r"Carrier transitions:\s*([\d,]+)")
    def _carrier(m, _l):
        n = _n(m.group(1))
        key = "down" if n > 20 else ("warning" if n > 2 else None)
        return f"The link has dropped {n:,} times since the counters were last cleared.", key

    @rule(r"CRC/Align errors\s+([\d,]+)\s+([\d,]+)")
    def _crc(m, _l):
        rx = _n(m.group(1))
        if rx:
            return (f"{rx:,} frames arrived corrupted (bad checksum). Usually a dirty fiber, a bad optic "
                    f"or a damaged cable.", "down")
        return "No corrupted frames received. The physical layer looks clean.", "up"

    @rule(r"^\s*Errors:\s*([\d,]+).*Framing errors:\s*([\d,]+)")
    def _inerr(m, _l):
        e, f = _n(m.group(1)), _n(m.group(2))
        if e or f:
            return f"{e:,} input errors and {f:,} framing errors were received. Look at fiber/optic health.", "warning"
        return "No input or framing errors.", "up"

    @rule(r"^\s*(Input|Output) errors\s*:\s*$")
    def _errhdr(m, _l):
        return f"The next line breaks down {m.group(1).lower()} error counters.", None

    @rule(r"(Laser output power|Laser output power|Tx power)\s*:\s*(.*dBm)")
    def _tx(m, _l):
        d = _dbm(m.group(2))
        if d is None:
            return None
        if d <= -30:
            return "This optic is NOT transmitting: no light leaving the port. The optic may be dead or disabled.", "down"
        return f"Light this optic is sending toward the far end: {d:.2f} dBm.", None

    @rule(r"(Receiver signal average optical power|Laser receiver power|Laser rx power)\s*:\s*(.*dBm)")
    def _rx(m, _l):
        d = _dbm(m.group(2))
        if d is None:
            return None
        meaning, key = _rx_meaning(d)
        return f"Light received from the far end: {d:.2f} dBm. {meaning}", key

    @rule(r"(rx|receiver)[^:]*power (low|high) (alarm|warning) threshold\s*:\s*(.*dBm)")
    def _thr(m, _l):
        d = _dbm(m.group(4))
        side = "below" if m.group(2).lower() == "low" else "above"
        lvl = m.group(3).lower()
        return f"The optic raises a {lvl} if receive light goes {side} {d:.2f} dBm.", None

    @rule(r"^\s*(.*?(alarm|warning))\s*:\s*(On|Off)\s*$")
    def _flag(m, _l):
        if m.group(3).lower() == "on":
            return f"ACTIVE: {m.group(1).strip()} is on right now.", "down" if "alarm" in m.group(2).lower() else "warning"
        return None

    @rule(r"Laser bias current\s*:\s*([\d.]+)\s*mA")
    def _bias(m, _l):
        return f"Current driving the laser: {m.group(1)} mA. A sudden rise often means the laser is aging.", None

    @rule(r"Module temperature\s*:\s*(-?\d+)\s*degrees C")
    def _temp(m, _l):
        t = int(m.group(1))
        if t >= 70:
            return f"Optic is hot ({t} °C). Check airflow/fans; hot optics fail early.", "warning"
        return f"Optic temperature {t} °C is normal.", None

    @rule(r"Module voltage\s*:\s*([\d.]+)\s*V")
    def _volt(m, _l):
        return f"Supply voltage to the optic ({m.group(1)} V). Normally about 3.3 V.", None

    @rule(r"^((?:xe|ge|et|mge|fe)-\d+/\d+/\d+(?::\d+)?)(\.\d+)?\s+(up|down)\s+(up|down)\b")
    def _terse(m, _l):
        name = m.group(1) + (m.group(2) or "")
        admin, link = m.group(3), m.group(4)
        if admin == "down":
            return f"{name}: disabled in the configuration.", "warning"
        if link == "down":
            return f"{name}: enabled but no link.", "down"
        return f"{name}: enabled with link.", "up"

    @rule(r"(\d+) packets transmitted, (\d+) packets received, ([\d.]+)% packet loss")
    def _ping(m, _l):
        loss = float(m.group(3))
        key = "up" if loss == 0 else ("down" if loss >= 50 else "warning")
        return f"Sent {m.group(1)} pings, got {m.group(2)} replies: {loss:g}% loss.", key

    @rule(r"round-trip min/avg/max/stddev = ([\d.]+)/([\d.]+)/([\d.]+)")
    def _rtt(m, _l):
        return f"Round-trip time: average {m.group(2)} ms (best {m.group(1)}, worst {m.group(3)}).", None

    @rule(r"SNMP_TRAP_LINK_(DOWN|UP).*?ifName (\S+)")
    def _trap(m, line):
        when = line[:15] if re.match(r"^[A-Z][a-z]{2}\s+\d+\s+[\d:]+", line) else "this time"
        state = "lost link" if m.group(1) == "DOWN" else "regained link"
        return f"{m.group(2)} {state} at {when}.", "down" if m.group(1) == "DOWN" else "up"

    @rule(r"No alarms currently active")
    def _noalarm(m, _l):
        return "The chassis reports no active alarms.", "up"

    @rule(r"^\s*\d{4}-\d\d-\d\d .*\b(Major|Minor)\b\s+(.*)")
    def _alarm(m, _l):
        return f"{m.group(1)} chassis alarm: {m.group(2).strip()}.", "down" if m.group(1) == "Major" else "warning"

    @rule(r"^(System|Port|Chassis) (name|ID|description)\s*:\s*(.+)")
    def _lldp(m, _l):
        what = {"system": "The neighbor device's name", "port": "The neighbor's port",
                "chassis": "The neighbor's chassis ID"}[m.group(1).lower()]
        return f"{what}: {m.group(3).strip()}.", None

    @rule(r"^Junos:\s*(\S+)")
    def _ver(m, _l):
        return f"Junos software release running on this switch: {m.group(1)}.", None

    @rule(r"^Model:\s*(\S+)")
    def _model(m, _l):
        return f"Hardware model: {m.group(1)}.", None

    @rule(r"System booted:\s*(.*)")
    def _boot(m, _l):
        return f"The switch last rebooted: {m.group(1).strip()}.", None

    @rule(r"Last configured:\s*(.*)")
    def _cfg(m, _l):
        return f"Last configuration change: {m.group(1).strip()}.", None

    @rule(r"^\s*(error:|syntax error|unknown command)(.*)")
    def _err(m, _l):
        return "Junos rejected the command. Check the spelling, or try ending the line with ? for help.", "down"

    return rules


RULES = _rule_list()


def explain(text: str) -> dict:
    notes = []
    counts = {"down": 0, "warning": 0, "up": 0}
    for i, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        for rx, fn in RULES:
            m = rx.search(line)
            if not m:
                continue
            res = fn(m, line)
            if res:
                meaning, key = res
                notes.append((i, line.rstrip(), meaning, key))
                if key in counts:
                    counts[key] += 1
                break
    summary = []
    if not notes:
        summary.append(("No known fields were recognized in this output. The explainer covers interfaces, "
                        "optics, errors, flaps, LLDP, ping, logs, alarms and version/uptime.", None))
    else:
        if counts["down"]:
            summary.append((f"{counts['down']} problem{'s' if counts['down'] != 1 else ''} found", "down"))
        if counts["warning"]:
            summary.append((f"{counts['warning']} warning{'s' if counts['warning'] != 1 else ''}", "warning"))
        if counts["up"]:
            summary.append((f"{counts['up']} healthy reading{'s' if counts['up'] != 1 else ''}", "up"))
        summary.append((f"{len(notes)} lines explained", None))
    return {"summary": summary, "notes": notes}
