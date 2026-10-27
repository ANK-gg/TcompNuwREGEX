import io, json, html
from flask import Flask, render_template, request, send_file
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph
from reportlab.lib.styles import getSampleStyleSheet

app = Flask(__name__)
ENUNCIADO = ("Lenguaje formal para el registro de ingreso y salida de vehículos de la Playa de Estacionamiento Central (Lima). "
             "El control de acceso genera un archivo con una instrucción por línea (INGRESO o SALIDA, placa y hora). "
             "El compilador valida el léxico, la sintaxis (LR) y la semántica, y traduce el archivo a SQL y JSON "
             "para reducir los errores de registro de placas del 14 % a 0 %.")
EJEMPLO = "INGRESO: ABC-123 08:30\nINGRESO: XYZ-789 08:45\nSALIDA: ABC-123 10:45\nSALIDA: XYZ-789 09:15"
E = "ε"

# ---------- Léxico: ER -> AFND -> AFD (todo generado por código) ----------
def lit(w): return [(c, 0) for c in w]
SPECS = {
    "TOK_INGRESO": ("INGRESO:", lit("INGRESO:")),
    "TOK_SALIDA": ("SALIDA:", lit("SALIDA:")),
    "PLACA": ("[A-Z]{3}-?[0-9]{3}", [("A-Z", 0)] * 3 + [("-", 1)] + [("0-9", 0)] * 3),
    "HORA": ("[0-9]{2}:[0-9]{2}", [("0-9", 0), ("0-9", 0), (":", 0), ("0-9", 0), ("0-9", 0)]),
}
def match(s, c):
    if s == "A-Z": return "A" <= c <= "Z"
    if s == "0-9": return c in "0123456789"
    return c == s
def nfa(spec):
    T = []
    for i, (s, opt) in enumerate(spec):
        T.append((i, s, i + 1))
        if opt: T.append((i, E, i + 1))
    return {"Q": list(range(len(spec) + 1)), "q0": 0, "F": {len(spec)}, "T": T}
def clo(S, T):
    S = set(S); pend = list(S)
    while pend:
        x = pend.pop()
        for a, s, b in T:
            if a == x and s == E and b not in S: S.add(b); pend.append(b)
    return frozenset(S)
def to_dfa(N):
    T = N["T"]; syms = sorted({s for _, s, _ in T if s != E})
    s0 = clo({N["q0"]}, T); names = {s0: 0}; order = [s0]; D = []; i = 0
    while i < len(order):
        S = order[i]; i += 1
        for s in syms:
            U = {b for a, x, b in T if a in S and x == s}
            if not U: continue
            U = clo(U, T)
            if U not in names: names[U] = len(order); order.append(U)
            D.append((names[S], s, names[U]))
    return {"Q": list(range(len(order))), "q0": 0, "F": {names[S] for S in order if N["F"] & S}, "T": D}
def run(D, w):
    q = D["q0"]
    for c in w:
        nx = [b for a, s, b in D["T"] if a == q and match(s, c)]
        if not nx: return False
        q = nx[0]
    return q in D["F"]
def svg(A, p, path=()):
    n = len(A["Q"]); W = 80 * n + 20; X = lambda q: 50 + 80 * q
    hot = set(path); hs = {A["q0"]} | {b for _, b in path}
    mk = lambda d: '<marker id="%s" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0L8,4L0,8z" fill="%s"/></marker>' % d
    o = [f'<svg viewBox="0 0 {W} 130" width="{W}" height="130"><defs>{mk(("m", "#475569"))}{mk(("mh", "#0f766e"))}</defs>',
         f'<line x1="{X(0)-38}" y1="90" x2="{X(0)-19}" y2="90" stroke="#475569" marker-end="url(#m)"/>']
    g = {}
    for a, s, b in A["T"]: g.setdefault((a, b), []).append(s)
    for (a, b), ss in g.items():
        lab = ", ".join(ss); mx = (X(a) + X(b)) / 2
        h = (a, b) in hot
        st = 'stroke="#0f766e" stroke-width="3" marker-end="url(#mh)"' if h else 'stroke="#475569" marker-end="url(#m)"'
        fw = 700 if h else 400
        if b == a + 1:
            o.append(f'<line x1="{X(a)+18}" y1="90" x2="{X(b)-19}" y2="90" {st}/><text x="{mx}" y="82" text-anchor="middle" font-size="11" font-weight="{fw}">{lab}</text>')
        else:
            c = 72 - 40 * (b - a)
            o.append(f'<path d="M{X(a)},72 Q{mx},{c} {X(b)},72" fill="none" {st}/><text x="{mx}" y="{(72+c)/2-4}" text-anchor="middle" font-size="11" font-weight="{fw}">{lab}</text>')
    for q in A["Q"]:
        col = "#0f766e" if q in A["F"] else "#475569"
        o.append(f'<circle cx="{X(q)}" cy="90" r="18" fill="{"#ccfbf1" if q in hs else "#fff"}" stroke="{col}" stroke-width="2"/>')
        if q in A["F"]: o.append(f'<circle cx="{X(q)}" cy="90" r="14" fill="none" stroke="{col}"/>')
        o.append(f'<text x="{X(q)}" y="94" text-anchor="middle" font-size="12">{p}{q}</text>')
    return "".join(o) + "</svg>"
def camino(D, w):
    q, pasos, edges = D["q0"], [], []
    for c in w:
        nx = [(s, b) for a, s, b in D["T"] if a == q and match(s, c)]
        if not nx:
            pasos.append((f"q{q}", c, "—", "error")); return pasos, edges, False, f"sin transición desde q{q} con «{c}»"
        s, b = nx[0]; pasos.append((f"q{q}", c, s, f"q{b}")); edges.append((q, b)); q = b
    ok = q in D["F"]
    return pasos, edges, ok, (f"termina en q{q}, estado final" if ok else f"termina en q{q}, que no es final")
def vista_placas(toks, bad):
    D = DFAS["PLACA"]; vistos = {}
    cand = [(l, n) for t, l, n in toks if t == "PLACA"] + [(w, n) for w, n in bad if len(w) >= 5 and any(c.isalpha() for c in w) and any(c.isdigit() for c in w)]
    for w, n in cand: vistos.setdefault(w, []).append(n)
    out = []
    for w, ls in vistos.items():
        pasos, edges, ok, motivo = camino(D, w)
        out.append(dict(lex=w, lineas=", ".join(map(str, ls)), pasos=pasos, ok=ok, motivo=motivo, svg=svg(D, "q", edges)))
    return out
def quint(A, p):
    al = sorted({s for _, s, _ in A["T"] if s != E})
    return (f"Q = {{{', '.join(p+str(q) for q in A['Q'])}}} | Σ = {{{', '.join(al)}}} | δ = ver tabla | "
            f"q0 = {p}0 | F = {{{', '.join(p+str(q) for q in sorted(A['F']))}}}")
ATOMOS = []; DFAS = {}
for name, (er, spec) in SPECS.items():
    N = nfa(spec); D = to_dfa(N); DFAS[name] = D
    ATOMOS.append(dict(nombre=name, er=er, qn=quint(N, "n"), qd=quint(D, "q"), sn=svg(N, "n"), sd=svg(D, "q"),
                       tn=[(f"n{a}", s, f"n{b}") for a, s, b in N["T"]], td=[(f"q{a}", s, f"q{b}") for a, s, b in D["T"]]))
def lex(text):
    toks, errs, bad = [], [], []
    for n, line in enumerate(text.splitlines(), 1):
        for w in line.split():
            for name, D in DFAS.items():
                if run(D, w): toks.append((name, w, n)); break
            else: errs.append(f"Línea {n}: lexema no reconocido «{w}»"); bad.append((w, n))
    return toks, errs, bad

# ---------- Sintáctico: análisis LR (SLR) ----------
RULES = [("S'", ["L"]), ("L", ["L", "I"]), ("L", ["I"]), ("I", ["TI", "P", "H"]), ("I", ["TS", "P", "H"])]
ACT = {(0, "TI"): "s3", (0, "TS"): "s4", (1, "TI"): "s3", (1, "TS"): "s4", (1, "$"): "acc",
       (3, "P"): "s6", (4, "P"): "s7", (6, "H"): "s8", (7, "H"): "s9"}
for s_, r_ in [(2, 2), (5, 1), (8, 3), (9, 4)]:
    for t_ in ("TI", "TS", "$"): ACT[(s_, t_)] = f"r{r_}"
GOTO = {(0, "L"): 1, (0, "I"): 2, (1, "I"): 5}
MAP = {"TOK_INGRESO": "TI", "TOK_SALIDA": "TS", "PLACA": "P", "HORA": "H"}
TABLA_LR = [[s] + [ACT.get((s, t), "") for t in ("TI", "TS", "P", "H", "$")] + [GOTO.get((s, n), "") for n in ("L", "I")] for s in range(10)]
def lr(toks):
    inp = [(MAP[t], t, l, n) for t, l, n in toks] + [("$", "$", "", 0)]
    st = [(0, None)]; i = 0; tr = []
    while True:
        s = st[-1][0]; a = inp[i][0]; act = ACT.get((s, a))
        pila = str(st[0][0]) + "".join(f" {n[0]}{q}" for q, n in st[1:])
        rest = " ".join(x[0] for x in inp[i:])
        if act is None:
            return tr, None, f"Error sintáctico: no se esperaba {inp[i][1]}" + (f" en la línea {inp[i][3]}" if inp[i][3] else " al final de la entrada")
        if act == "acc": tr.append((pila, rest, "aceptar")); return tr, ("S'", [st[1][1]], ""), None
        if act[0] == "s":
            tr.append((pila, rest, "desplazar " + act[1:])); st.append((int(act[1:]), (inp[i][1], [], inp[i][2]))); i += 1
        else:
            lhs, rhs = RULES[int(act[1:])]
            ch = [st.pop()[1] for _ in rhs][::-1]
            tr.append((pila, rest, f"reducir {lhs} → {' '.join(rhs)}"))
            st.append((GOTO[(st[-1][0], lhs)], (lhs, ch, "")))
def tree_svg(root):
    pos = {}; cnt = [0]; mx = [0]
    def lay(n, d):
        mx[0] = max(mx[0], d)
        if not n[1]: x = 50 + 85 * cnt[0]; cnt[0] += 1
        else: xs = [lay(c, d + 1) for c in n[1]]; x = sum(xs) / len(xs)
        pos[id(n)] = (x, 30 + 50 * d); return x
    lay(root, 0); ln, tx = [], []
    def walk(n):
        x, y = pos[id(n)]
        for c in n[1]:
            cx, cy = pos[id(c)]; ln.append(f'<line x1="{x}" y1="{y+5}" x2="{cx}" y2="{cy-14}" stroke="#94a3b8"/>'); walk(c)
        tx.append(f'<text x="{x}" y="{y}" text-anchor="middle" font-size="12" font-weight="{600 if n[1] else 400}">{n[0]}</text>')
        if n[2]: tx.append(f'<text x="{x}" y="{y+15}" text-anchor="middle" font-size="11" fill="#0f766e">{n[2]}</text>')
    walk(root); W = 85 * cnt[0] + 20; H = 50 * mx[0] + 60
    return f'<svg viewBox="0 0 {W} {H}" width="{W}" height="{H}">' + "".join(ln) + "".join(tx) + "</svg>"

# ---------- Semántico y traducción ----------
def sem(toks):
    rows, errs, dentro, recs = [], [], {}, []
    for k in range(0, len(toks), 3):
        t, p, h = toks[k:k + 3]; n = k // 3 + 1; ln = t[2]; pl = p[1].replace("-", ""); pn = f"{pl[:3]}-{pl[3:]}"
        hh, mm = map(int, h[1].split(":"))
        if hh > 23 or mm > 59: errs.append(f"Línea {ln}: hora fuera de rango «{h[1]}»"); continue
        mins = hh * 60 + mm
        if t[0] == "TOK_INGRESO":
            if pl in dentro: errs.append(f"Línea {ln}: la placa {pn} ya tiene un ingreso abierto"); continue
            dentro[pl] = (mins, h[1]); recs.append({"placa": pn, "ingreso": h[1], "salida": None, "minutos": None})
            rows.append((f"Instrucción {n}", "Sintetizado", f"placa={pn}, hora={h[1]} → ingreso abierto"))
        else:
            if pl not in dentro: errs.append(f"Línea {ln}: la placa {pn} no tiene ingreso previo"); continue
            m0, h0 = dentro[pl]
            if mins <= m0: errs.append(f"Línea {ln}: la salida {h[1]} no es posterior al ingreso {h0}"); continue
            del dentro[pl]; r = next(r for r in recs if r["placa"] == pn and r["salida"] is None)
            r["salida"] = h[1]; r["minutos"] = mins - m0
            rows.append((f"Instrucción {n}", "Heredado", f"hora_ingreso={h0} heredada del ingreso → permanencia={mins-m0} min"))
    return rows, errs, recs
def to_sql(recs):
    o = ["CREATE TABLE IF NOT EXISTS registro (placa VARCHAR(7), hora_ingreso TIME, hora_salida TIME, minutos INT);"]
    for r in recs:
        o.append(f"INSERT INTO registro (placa, hora_ingreso) VALUES ('{r['placa']}', '{r['ingreso']}');")
        if r["salida"]: o.append(f"UPDATE registro SET hora_salida='{r['salida']}', minutos={r['minutos']} WHERE placa='{r['placa']}' AND hora_salida IS NULL;")
    return "\n".join(o)
def analizar(texto):
    r = dict(toks=[], errs=[], trace=[], tree="", rows=[], sql="", json="", placas=[])
    r["toks"], r["errs"], bad = lex(texto)
    r["placas"] = vista_placas(r["toks"], bad)
    if r["errs"] or not r["toks"]:
        if not r["toks"] and not r["errs"]: r["errs"] = ["Entrada vacía: escribe o carga al menos una instrucción."]
        return r
    r["trace"], root, err = lr(r["toks"])
    if err: r["errs"] = [err]; return r
    r["tree"] = tree_svg(root)
    r["rows"], r["errs"], recs = sem(r["toks"])
    r["sql"] = to_sql(recs); r["json"] = json.dumps(recs, ensure_ascii=False, indent=2)
    return r

@app.route("/", methods=["GET", "POST"])
def index():
    texto, res = EJEMPLO, None
    if request.method == "POST":
        f = request.files.get("archivo")
        texto = f.read().decode("utf-8", "ignore") if f and f.filename else request.form.get("texto", "")
        res = analizar(texto)
    return render_template("index.html", enunciado=ENUNCIADO, texto=texto, res=res, atomos=ATOMOS, tabla_lr=TABLA_LR, reglas=RULES)

@app.route("/reporte", methods=["POST"])
def reporte():
    r = analizar(request.form.get("texto", "")); ss = getSampleStyleSheet(); e = html.escape
    s = [Paragraph("Reporte de traducción: registro de placas", ss["Title"]), Paragraph("Tokens generados", ss["Heading2"])]
    s += [Paragraph(f"Línea {n}: {e(t)} = {e(l)}", ss["Normal"]) for t, l, n in r["toks"]]
    if r["errs"]: s += [Paragraph("Errores", ss["Heading2"])] + [Paragraph(e(x), ss["Normal"]) for x in r["errs"]]
    s.append(Paragraph("Traducción a SQL", ss["Heading2"]))
    s += [Paragraph(e(x), ss["Code"]) for x in r["sql"].splitlines()]
    b = io.BytesIO(); SimpleDocTemplate(b, pagesize=A4).build(s); b.seek(0)
    return send_file(b, mimetype="application/pdf", as_attachment=True, download_name="reporte.pdf")

if __name__ == "__main__":
    app.run(debug=True)