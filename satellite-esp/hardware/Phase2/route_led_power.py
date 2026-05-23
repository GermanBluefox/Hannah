import pcbnew, math

board = pcbnew.GetBoard()

VDD_NET_NAME = "+3.3V"
GND_NET_NAME = "GND"

VIA_DRILL  = pcbnew.FromMM(0.3)
VIA_SIZE   = pcbnew.FromMM(0.6)
TRACE_W    = pcbnew.FromMM(0.25)
VIA_OFFSET = 1.5  # mm, Richtung Platinenmitte

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

nets = board.GetNetInfo().NetsByName()

# Netz suchen (mit und ohne führendem /)
def find_net(name):
    for key in [name, "/" + name]:
        if key in nets:
            return nets[key]
    print(f"FEHLER: Netz '{name}' nicht gefunden. Verfügbare Netze:")
    for k in sorted(nets.keys())[:20]:
        print(f"  {k}")
    return None

vdd_net = find_net(VDD_NET_NAME)
gnd_net = find_net(GND_NET_NAME)
if vdd_net is None or gnd_net is None:
    raise SystemExit

def add_via(x_mm, y_mm, net):
    via = pcbnew.PCB_VIA(board)
    board.Add(via)
    via.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x_mm), pcbnew.FromMM(y_mm)))
    via.SetDrill(VIA_DRILL)
    via.SetWidth(VIA_SIZE)
    via.SetNet(net)
    via.SetViaType(pcbnew.VIATYPE_THROUGH)
    return via

def add_trace(x1, y1, x2, y2, net, layer):
    t = pcbnew.PCB_TRACK(board)
    board.Add(t)
    t.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(x1), pcbnew.FromMM(y1)))
    t.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(x2), pcbnew.FromMM(y2)))
    t.SetNet(net)
    t.SetLayer(layer)
    t.SetWidth(TRACE_W)

count = 0
for fp in board.GetFootprints():
    ref = fp.GetReference()
    if not (ref.startswith('D') and ref[1:].isdigit() and 2 <= int(ref[1:]) <= 25):
        continue

    fx = pcbnew.ToMM(fp.GetPosition().x)
    fy = pcbnew.ToMM(fp.GetPosition().y)

    # Einheitsvektor weg von der Platinenmitte (nach außen)
    dx, dy = fx - cx, fy - cy
    dist = math.sqrt(dx*dx + dy*dy)
    ux, uy = dx/dist, dy/dist

    pads = {p.GetNumber(): p for p in fp.Pads()}
    vdd_pad = pads.get("2")
    gnd_pad = pads.get("4")

    if vdd_pad is None or gnd_pad is None:
        print(f"{ref}: Pad 2 oder 4 nicht gefunden, übersprungen")
        continue

    for pad, net, label in [(vdd_pad, vdd_net, "VDD"), (gnd_pad, gnd_net, "GND")]:
        px = pcbnew.ToMM(pad.GetPosition().x)
        py = pcbnew.ToMM(pad.GetPosition().y)
        vx = px + ux * VIA_OFFSET
        vy = py + uy * VIA_OFFSET
        add_via(vx, vy, net)
        add_trace(px, py, vx, vy, net, pcbnew.F_Cu)

    print(f"{ref}: OK")
    count += 1

pcbnew.Refresh()
board.Save(board.GetFileName())
print(f"Fertig — {count} LEDs versorgt.")
