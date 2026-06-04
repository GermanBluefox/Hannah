import pcbnew
import math

board = pcbnew.GetBoard()
target_lengths = [1.3250, 0.8132]
epsilon = 0.003

found = []
for track in board.GetTracks():
    if track.GetClass() not in ('PCB_TRACK', 'TRACK'):
        continue
    if track.GetNetname() != '+3.3V':
        continue
    if track.GetLayer() != pcbnew.F_Cu:
        continue

    start = track.GetStart()
    end   = track.GetEnd()
    dx = (end.x - start.x) / 1e6
    dy = (end.y - start.y) / 1e6
    length = math.sqrt(dx*dx + dy*dy)

    for t in target_lengths:
        if abs(length - t) < epsilon:
            track.SetSelected()
            found.append((pcbnew.ToMM(start.x), pcbnew.ToMM(start.y),
                          pcbnew.ToMM(end.x),   pcbnew.ToMM(end.y), length))
            break

pcbnew.Refresh()
print(f"{len(found)} Segmente markiert:")
for s in found:
    print(f"  ({s[0]:.3f},{s[1]:.3f}) -> ({s[2]:.3f},{s[3]:.3f})  {s[4]:.4f}mm")
