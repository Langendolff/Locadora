import math, sys
from fontTools.ttLib import TTCollection
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
import uharfbuzz as hb

RED, INK, WHITE = "#E5422B", "#16181D", "#FFFFFF"
OUT = "/out"

# ---------------- símbolo: play em 3 camadas, ângulos de 30° exatos ----------------
def symbol_paths(gap, top=46, bot=210):
    half = (bot-top)/2; mid = (top+bot)/2
    L = half/math.tan(math.radians(30))
    x0 = round(128 - (L/2 + L/3)/2, 2)          # centro óptico: entre caixa e centróide
    apex = (x0+L, mid); k = L/half
    h = (bot-top-2*gap)/3
    xr = lambda y: x0 + k*(y-top) if y <= mid else x0 + k*(bot-y)
    out = []
    for a, b in [(top, top+h), (top+h+gap, top+2*h+gap), (top+2*h+2*gap, bot)]:
        pts = [(x0, a)]
        if xr(a)-x0 > .01: pts.append((xr(a), a))
        if a < mid < b: pts.append(apex)
        if xr(b)-x0 > .01: pts.append((xr(b), b))
        pts.append((x0, b))
        out.append("M" + "L".join(f"{x:.2f},{y:.2f}" for x, y in pts) + "Z")
    return out

def svg(w, h, body, title="Locadora"):
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}"><title>{title}</title>{body}</svg>\n'

def g(paths, fill, transform=""):
    t = f' transform="{transform}"' if transform else ""
    return f'<path fill="{fill}"{t} d="{" ".join(paths)}"/>'

main, small = symbol_paths(15), symbol_paths(26, top=40, bot=216)
open(f"{OUT}/locadora-symbol.svg", "w").write(svg(256, 256, g(main, RED)))
open(f"{OUT}/locadora-symbol-black.svg", "w").write(svg(256, 256, g(main, "#000")))
open(f"{OUT}/locadora-symbol-white.svg", "w").write(svg(256, 256, g(main, WHITE)))
open(f"{OUT}/locadora-symbol-small.svg", "w").write(svg(256, 256, g(small, RED)))

# ---------------- nome: Inter Display Bold convertida em formas ----------------
ttc = TTCollection("/fonts/Inter.ttc")
def pick(family, sub):
    for i, f in enumerate(ttc.fonts):
        n = f["name"]
        fam = n.getDebugName(16) or n.getDebugName(1); st = n.getDebugName(17) or n.getDebugName(2)
        if fam == family and st == sub: return i, f
    raise SystemExit("fonte não encontrada")
idx, font = pick("Inter Display", "Bold")
blob = hb.Blob.from_file_path("/fonts/Inter.ttc"); face = hb.Face(blob, idx); hbf = hb.Font(face)
upem = font["head"].unitsPerEm; cap = font["OS/2"].sCapHeight
buf = hb.Buffer(); buf.add_str("Locadora"); buf.guess_segment_properties()
hb.shape(hbf, buf, {"kern": True, "liga": True})
gs = font.getGlyphSet(); order = font.getGlyphOrder()
CAP = 112                                # altura das maiúsculas em unidades do logo
s = CAP / cap; track = -0.012 * upem     # tracking levemente fechado (display)
pen_x = 0; parts = []
for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
    name = order[info.codepoint]
    sp = SVGPathPen(gs)
    gs[name].draw(TransformPen(sp, (s, 0, 0, -s, (pen_x + pos.x_offset) * s, 0)))
    parts.append(sp.getCommands())
    pen_x += pos.x_advance + track
word_w = (pen_x - track) * s
word = " ".join(parts)                   # baseline em y=0, maiúsculas sobem até -CAP

# ---------------- lockups ----------------
# caixa real do símbolo (sem a margem do quadrado 256)
L = 82/math.tan(math.radians(30)); SX0 = 128 - (L/2 + L/3)/2; SX1 = SX0 + L; SY0, SY1 = 46, 210
PAD = 16
def lock_h(sym_fill, word_fill, cap_px=100, ratio=1.8):
    sc = cap_px/CAP                                  # escala da palavra
    ss = ratio*cap_px/(SY1-SY0)                      # escala do símbolo
    sym_w, sym_h = (SX1-SX0)*ss, (SY1-SY0)*ss
    gap = 0.42*cap_px
    H = sym_h + 2*PAD; W = sym_w + gap + word_w*sc + 2*PAD
    sym_t = f"translate({PAD - SX0*ss:.2f},{PAD - SY0*ss:.2f}) scale({ss:.4f})"
    base = PAD + sym_h/2 + cap_px/2                  # maiúsculas centradas no símbolo
    word_t = f"translate({PAD + sym_w + gap:.2f},{base:.2f}) scale({sc:.4f})"
    return svg(round(W, 1), round(H, 1), g(main, sym_fill, sym_t) + f'<path fill="{word_fill}" transform="{word_t}" d="{word}"/>')
def lock_v(sym_fill, word_fill, cap_px=100):
    sc = cap_px/CAP; ww = word_w*sc
    ss = 0.40*ww/(SX1-SX0) if 0.40*ww/(SX1-SX0)*(SY1-SY0) < 2.6*cap_px else 2.6*cap_px/(SY1-SY0)
    sym_w, sym_h = (SX1-SX0)*ss, (SY1-SY0)*ss
    gap = 0.55*cap_px
    W = max(ww, sym_w) + 2*PAD; H = sym_h + gap + cap_px + 2*PAD
    # centra o símbolo pelo centróide óptico (entre caixa e centróide do triângulo)
    opt_cx = (SX0 + (SX0 + (SX1-SX0)/3) + (SX0+SX1)/2*1)/2.5
    sym_t = f"translate({W/2 - ((SX0+SX1)/2 - L*0.08)*ss:.2f},{PAD - SY0*ss:.2f}) scale({ss:.4f})"
    word_t = f"translate({(W-ww)/2:.2f},{PAD + sym_h + gap + cap_px:.2f}) scale({sc:.4f})"
    return svg(round(W, 1), round(H, 1), g(main, sym_fill, sym_t) + f'<path fill="{word_fill}" transform="{word_t}" d="{word}"/>')
for suf, a, b in (("", RED, INK), ("-dark", RED, WHITE), ("-black", "#000", "#000"), ("-white", WHITE, WHITE)):
    open(f"{OUT}/locadora-horizontal{suf}.svg", "w").write(lock_h(a, b))
    open(f"{OUT}/locadora-stacked{suf}.svg", "w").write(lock_v(a, b))
# só o nome
open(f"{OUT}/locadora-wordmark.svg", "w").write(svg(math.ceil(word_w)+8, CAP+40, f'<path fill="{INK}" transform="translate(4,{CAP+4})" d="{word}"/>'))
print(f"palavra {word_w:.1f} x {CAP}")
