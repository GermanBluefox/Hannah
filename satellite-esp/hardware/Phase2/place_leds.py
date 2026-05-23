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

# Alle SK6812 LEDs sammeln
leds = {}
for fp in board.GetFootprints():
    if 'SK6812' in str(fp.GetFPID().GetLibItemName()):
        leds[fp.GetReference()] = fp

print(f"{len(leds)} SK6812MINI-E LEDs gefunden")

# DIN (Pin 2) und DOUT (Pin 4) Netze pro LED ermitteln
din_net = {}
dout_net = {}
for ref, fp in leds.items():
    for pad in fp.Pads():
        n = pad.GetNumber()
        net = pad.GetNetname()
        if n == '2':
            din_net[ref] = net
        elif n == '4':
            dout_net[ref] = net

# Kette aufbauen
din_to_ref = {net: ref for ref, net in din_net.items()}
chain = {}
for ref in leds:
    dout = dout_net.get(ref)
    if dout and dout in din_to_ref:
        chain[ref] = din_to_ref[dout]

# Startpunkt: LED deren DIN am LED_RING_DATA haengt
start = None
for ref, net in din_net.items():
    if 'RING' in net or 'DATA' in net:
        start = ref
        break
if start is None:
    all_nexts = set(chain.values())
    for ref in leds:
        if ref not in all_nexts:
            start = ref
            break

# Kette traversieren
ordered = []
current = start
visited = set()
while current and current not in visited:
    ordered.append(current)
    visited.add(current)
    current = chain.get(current)

print(f"Kette: {ordered}")

# Natuerliche DOUT-Richtung aus Pad-Positionen bei 0-Grad-Rotation ermitteln
first_fp = leds[ordered[0]]
first_fp.SetOrientationDegrees(0)
fp_pos = first_fp.GetPosition()
din_local = None
dout_local = None
for pad in first_fp.Pads():
    lx = pcbnew.ToMM(pad.GetPosition().x - fp_pos.x)
    ly = pcbnew.ToMM(pad.GetPosition().y - fp_pos.y)
    if pad.GetNumber() == '2':
        din_local = (lx, ly)
    elif pad.GetNumber() == '4':
        dout_local = (lx, ly)

# Richtung DIN→DOUT im lokalen Footprint-Frame bei 0-Grad
natural_angle = math.degrees(math.atan2(
    dout_local[1] - din_local[1],
    dout_local[0] - din_local[0]
))
print(f"DIN lokal: {din_local}, DOUT lokal: {dout_local}")
print(f"Natuerliche DOUT-Richtung: {natural_angle:.1f} Grad")

# LEDs platzieren
radius = 40.0
num = len(ordered)
for i, ref in enumerate(ordered):
    fp = leds[ref]
    angle_deg = i * 360.0 / num
    angle_rad = math.radians(angle_deg)

    x = cx + radius * math.cos(angle_rad)
    y = cy + radius * math.sin(angle_rad)
    fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)))

    fp.SetOrientationDegrees(-(angle_deg + 90))

pcbnew.Refresh()
board.Save(board.GetFileName())
print("Fertig!")
