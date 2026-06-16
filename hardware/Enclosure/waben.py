import Part, FreeCAD as App, math
doc = App.ActiveDocument

# ── Parameter ──────────────────────────────────────────────
R        = 5.0 * math.pi / (2.0 * math.sqrt(3))  # 4.534mm: exakt 2 Waben/Ecke
cell_R   = R - 0.6                                 # ~3.93mm, ~1mm Wand
depth    = 1.0
half_xy  = 49.0
corner_r = 10.0
flat_min = -(half_xy - corner_r)   # -39mm
flat_max =  (half_xy - corner_r)   # +39mm
margin   = R + 2

col_spacing = R * math.sqrt(3)
row_spacing = 1.5 * R
arc_len     = corner_r * math.pi / 2

TOTAL_H  = 98.0
UT_Z_MAX = 83.0
OT_Z_MAX = 15.0
OT_Z_MIN    = 83.0  # Oberteil liegt in Weltkoordinaten Z=83..98
OT_Z_MAX    = 98.0

CORNERS = [
    (+39.0, +39.0, 0,              math.pi/2),
    (-39.0, +39.0, math.pi/2,      math.pi),
    (-39.0, -39.0, math.pi,        3*math.pi/2),
    (+39.0, -39.0, 3*math.pi/2,    2*math.pi),
]

print("R=%.4f  col=%.4f  arc=%.4f  ratio=%.4f" % (R, col_spacing, arc_len, arc_len/col_spacing))

# ── Hilfsfunktionen ────────────────────────────────────────
def col_off(row_idx):
    return (row_idx % 2) * (col_spacing / 2)

def gap_to_flat_max(c_off):
    n = math.floor((flat_max - flat_min - c_off) / col_spacing)
    return flat_max - (flat_min + c_off + n * col_spacing)

# ── Prismen (flache Waende) ────────────────────────────────
def hex_pts(cx, cy, r):
    return [(cx + r*math.cos(math.pi/2 + k*math.pi/3),
             cy + r*math.sin(math.pi/2 + k*math.pi/3)) for k in range(6)]

def prism_x(h, z, x, s):
    pts = hex_pts(h, z, cell_R)
    v = [App.Vector(x, p[0], p[1]) for p in pts] + [App.Vector(x, pts[0][0], pts[0][1])]
    return Part.Face(Part.Wire([Part.LineSegment(v[i],v[i+1]).toShape() for i in range(6)])).extrude(App.Vector(s*depth,0,0))

def prism_y(h, z, y, s):
    pts = hex_pts(h, z, cell_R)
    v = [App.Vector(p[0], y, p[1]) for p in pts] + [App.Vector(pts[0][0], y, pts[0][1])]
    return Part.Face(Part.Wire([Part.LineSegment(v[i],v[i+1]).toShape() for i in range(6)])).extrude(App.Vector(0,s*depth,0))

# ── Prismen (Ecken, radial) ────────────────────────────────
def corner_prism(ax, ay, z, tx, ty, ix, iy):
    verts = []
    for k in range(6):
        alpha = math.pi/2 + k*math.pi/3
        verts.append(App.Vector(
            ax + cell_R * math.sin(alpha) * tx,
            ay + cell_R * math.sin(alpha) * ty,
            z  + cell_R * math.cos(alpha)))
    verts.append(verts[0])
    face = Part.Face(Part.Wire([Part.LineSegment(verts[i],verts[i+1]).toShape() for i in range(6)]))
    return face.extrude(App.Vector(ix*depth, iy*depth, 0))

def corner_prisms_for_row(cx, cy, t0, t1, z, c_off):
    gap = gap_to_flat_max(c_off)
    prisms = []
    s = col_spacing - gap
    while s < arc_len + cell_R:
        theta = t0 + s / corner_r
        ax = cx + corner_r * math.cos(theta)
        ay = cy + corner_r * math.sin(theta)
        tx = -math.sin(theta)
        ty =  math.cos(theta)
        ix = (cx - ax) / corner_r
        iy = (cy - ay) / corner_r
        prisms.append(corner_prism(ax, ay, z, tx, ty, ix, iy))
        s += col_spacing
    return prisms

# ── Zeilen generieren (mit optionalem Z-Offset fuer Grid-Alignment) ──
def gen_rows(z_min_local, z_max_local, z_offset=0.0):
    """z_offset: global_Z = local_Z + z_offset (Naht-Alignment)"""
    rows = []
    first_row = math.floor((z_min_local + z_offset - margin) / row_spacing)
    row_idx = first_row
    while True:
        local_z = row_idx * row_spacing - z_offset
        if local_z > z_max_local + margin: break
        rows.append((row_idx, local_z))
        row_idx += 1
    return rows

# ── Cutter aufbauen ────────────────────────────────────────
def build_cutter(rows):
    solids = []
    for (row_idx, z) in rows:
        c_off = col_off(row_idx)
        h = flat_min - margin + c_off
        while h <= flat_max + col_spacing:
            solids.append(prism_x(h, z, +half_xy, -1))
            solids.append(prism_x(h, z, -half_xy, +1))
            solids.append(prism_y(h, z, +half_xy, -1))
            solids.append(prism_y(h, z, -half_xy, +1))
            h += col_spacing
    print("  %d Prismen (%d Zeilen)" % (len(solids), len(rows)))
    return Part.Compound(solids)

# ── Alte Objekte loeschen ──────────────────────────────────
for name in ["Front_base_Waben", "Back_base_Waben", "Top_Base_Waben"]:
    old = doc.getObject(name)
    if old: doc.removeObject(name)

# ── Unterteil (Front + Back, Z 0..83) ─────────────────────
print("Unterteil (Z 0..83):")
ut_cutter = build_cutter(gen_rows(0, UT_Z_MAX, z_offset=0))
for name in ["Body", "Body001"]:
    obj = doc.getObject(name)
    print("  Schneide %s ..." % obj.Label)
    feat = doc.addObject("Part::Feature", obj.Label + "_Waben")
    feat.Shape = obj.Shape.cut(ut_cutter)
    print("  -> fertig")

# ── Oberteil (top-up, kein invert_x, Z-Offset=83) ─────────
print("Oberteil (top-up, Z %d..%d):" % (OT_Z_MIN, OT_Z_MAX))
ot_cutter = build_cutter(gen_rows(OT_Z_MIN, OT_Z_MAX, z_offset=0))
obj = doc.getObject("Body002")
print("  Schneide %s ..." % obj.Label)
feat = doc.addObject("Part::Feature", "Top_Base_Waben")
feat.Shape = obj.Shape.cut(ot_cutter)
feat.Placement = obj.Placement  # Placement vom Original-Body kopieren
print("  -> fertig")

# ── BaseFeature-Links der Honeycombs-Bodies wiederherstellen ───────────────
# Die Links brechen wenn *_Waben-Objekte geloescht und neu erstellt werden.
doc.getObject("BaseFeature").BaseFeature   = doc.getObject("Front_base_Waben")
doc.getObject("BaseFeature001").BaseFeature = doc.getObject("Back_base_Waben")
doc.getObject("BaseFeature002").BaseFeature = doc.getObject("Top_Base_Waben")

doc.recompute()
print("=== Fertig! R=%.4fmm ===" % R)
