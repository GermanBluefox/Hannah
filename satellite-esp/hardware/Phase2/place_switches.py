import pcbnew, math

board = pcbnew.GetBoard()

# Platinenmitte aus Edge.Cuts-Kreis
cx, cy = None, None
for d in board.GetDrawings():
    if d.GetLayer() == pcbnew.Edge_Cuts and d.GetClass() == "PCB_SHAPE":
        if d.GetShape() == pcbnew.SHAPE_T_CIRCLE:
            cx = pcbnew.ToMM(d.GetCenter().x)
            cy = pcbnew.ToMM(d.GetCenter().y)
            break

if cx is None:
    print("FEHLER: Kein Kreis auf Edge.Cuts gefunden")
    raise SystemExit

print(f"Platinenmitte: ({cx:.2f}, {cy:.2f}) mm")

radius = 17.0

for fp in board.GetFootprints():
    ref = fp.GetReference()
    if ref.startswith('SW') and ref[2:].isdigit() and int(ref[2:]) >= 3:
        pos = fp.GetPosition()
        fx = pcbnew.ToMM(pos.x)
        fy = pcbnew.ToMM(pos.y)

        # Winkel aus aktueller Position berechnen
        dx = fx - cx
        dy = fy - cy
        angle = math.degrees(math.atan2(dy, dx))

        # Auf 17mm Radius setzen, Winkel beibehalten
        nx = cx + radius * math.cos(math.radians(angle))
        ny = cy + radius * math.sin(math.radians(angle))

        fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(nx), pcbnew.FromMM(ny)))
        print(f"{ref}: Winkel={angle:.1f}° → ({nx:.2f}, {ny:.2f})")

pcbnew.Refresh()
board.Save(board.GetFileName())
print("Fertig!")
