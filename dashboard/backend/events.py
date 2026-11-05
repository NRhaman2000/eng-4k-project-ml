"""Derive history events by comparing consecutive packets.

Every event is something the firmware reported (state, fault, bypass,
balancing) or an advisory dashboard warning. Nothing here makes a decision.
"""


def diff_events(prev, cur):
    base = {"timestamp": cur.timestamp, "source": cur.source, "seq": cur.seq}
    out = []

    def add(kind, message, cell=None, detail=None):
        out.append({**base, "kind": kind, "cell": cell, "detail": detail, "message": message})

    if prev is None or prev.system_state != cur.system_state:
        frm = prev.system_state if prev else None
        add("STATE", f"State {frm or 'start'} → {cur.system_state}", detail=f"{frm}->{cur.system_state}")

    pf = (prev.fault.active, prev.fault.type, prev.fault.cell) if prev else (False, None, None)
    cf = (cur.fault.active, cur.fault.type, cur.fault.cell)
    if pf != cf:
        if pf[0]:
            add("FAULT_CLEARED", f"Firmware cleared {pf[1]}" + (f" on cell {pf[2]}" if pf[2] else ""),
                cell=pf[2], detail=pf[1])
        if cf[0]:
            add("FAULT_REPORTED", f"Firmware reported {cf[1]}" + (f" on cell {cf[2]}" if cf[2] else ""),
                cell=cf[2], detail=cf[1])

    prev_cells = {c.id: c for c in prev.cells} if prev else {}
    for c in cur.cells:
        p = prev_cells.get(c.id)
        if bool(c.bypassed) != bool(p.bypassed if p else False):
            add("CELL_BYPASSED" if c.bypassed else "CELL_RESTORED",
                f"Cell {c.id} {'bypassed (isolated)' if c.bypassed else 'back in the string'}", cell=c.id)
        if bool(c.balancing) != bool(p.balancing if p else False):
            add("BALANCING_START" if c.balancing else "BALANCING_STOP",
                f"Cell {c.id} balancing {'started' if c.balancing else 'stopped'}", cell=c.id)

    pw = {(w.code, w.cell) for w in prev.warnings} if prev else set()
    cw = {(w.code, w.cell): w for w in cur.warnings}
    for key, w in cw.items():
        if key not in pw:
            add("WARNING_RAISED", w.message, cell=w.cell, detail=w.code)
    for code, cell in pw - set(cw):
        add("WARNING_CLEARED", f"{code} cleared" + (f" on cell {cell}" if cell else ""), cell=cell, detail=code)

    pi = {i.field for i in prev.invalid} if prev else set()
    ci = {i.field: i for i in cur.invalid}
    for field, inv in ci.items():
        if field not in pi:
            add("INVALID_READING", f"{field} = {inv.value} not plausible ({inv.reason}); shown as N/A",
                detail=field)
    for field in pi - set(ci):
        add("READING_RESTORED", f"{field} plausible again", detail=field)
    return out
