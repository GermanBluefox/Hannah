import pcbnew, math

board = pcbnew.GetBoard()

# Platinenmitte
cx, cy = None, None
for d in board.GetDrawings():
    if d.GetLayer() == pcbnew.Edge_Cuts and d.GetClass() == "PCB_SHAPE":
        if d.GetShape() == pcbnew.SHAPE_T_CIRCLE:
            cx = pcbnew.ToMM(d.GetCenter().x)
            cy = pcbnew.ToMM(d.GetCenter().y)
            break

if cx is None:
    print("FEHLER: Kein Edge.Cuts-Kreis gefunden")
    raise SystemExit

# Vias und Traces im LED-Ring-Bereich (35–45mm vom Mittelpunkt) auf +3.3V oder GND löschen
TARGET_NETS = {"+3.3V", "GND", "/+3.3V", "/GND"}
RING_MIN = 35.0
RING_MAX = 45.0

to_delete = []

for via in board.GetTracks():
    net_name = via.GetNetname()
    if net_name not in TARGET_NETS:
        continue
    x = pcbnew.ToMM(via.GetPosition().x)
    y = pcbnew.ToMM(via.GetPosition().y)
    r = math.sqrt((x - cx)**2 + (y - cy)**2)
    if RING_MIN <= r <= RING_MAX:
        # Nur Vias und kurze Traces (< 3mm)
        if via.GetClass() == "PCB_VIA":
            to_delete.append(via)
        elif via.GetClass() == "PCB_TRACK":
            sx = pcbnew.ToMM(via.GetStart().x)
            sy = pcbnew.ToMM(via.GetStart().y)
            ex = pcbnew.ToMM(via.GetEnd().x)
            ey = pcbnew.ToMM(via.GetEnd().y)
            length = math.sqrt((sx-ex)**2 + (sy-ey)**2)
            if length < 3.0:
                to_delete.append(via)

for item in to_delete:
    board.Remove(item)

pcbnew.Refresh()
board.Save(board.GetFileName())
print(f"{len(to_delete)} Elemente entfernt.")
