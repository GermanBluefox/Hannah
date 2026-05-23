import pcbnew
import math

board = pcbnew.GetBoard()
cx = pcbnew.FromMM(58.5)
cy = pcbnew.FromMM(57.5)

moved = 0
for fp in board.GetFootprints():
    if fp.GetReference().startswith('D') and 'SK6812' in fp.GetValue():
        pos = fp.GetPosition()
        dx, dy = pos.x - cx, pos.y - cy
        dist = math.sqrt(dx*dx + dy*dy)
        if dist == 0:
            continue
        factor = (dist - pcbnew.FromMM(0.2)) / dist
        fp.SetPosition(pcbnew.VECTOR2I(int(cx + dx*factor), int(cy + dy*factor)))
        moved += 1

board.Save(board.GetFileName())
pcbnew.Refresh()
print(f"{moved} LEDs um 0.2mm nach innen verschoben.")
