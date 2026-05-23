import pcbnew

board = pcbnew.GetBoard()

cx, cy = 58.5, 57.5
r = 17.0

# Diamond: oben, unten, links, rechts
positions = {
    'SW4': (cx,      cy - r),   # oben
    'SW3': (cx,      cy + r),   # unten
    'SW5': (cx - r,  cy),       # links
    'SW6': (cx + r,  cy),       # rechts
}

for fp in board.GetFootprints():
    ref = fp.GetReference()
    if ref in positions:
        x, y = positions[ref]
        fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)))
        print(f"{ref} -> ({x:.1f}, {y:.1f})")

board.Save(board.GetFileName())
pcbnew.Refresh()
print("Fertig.")
