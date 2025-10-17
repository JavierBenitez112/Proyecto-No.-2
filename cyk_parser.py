#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Proyecto 2 — Teoría de la Computación
CYK con:
  1) Lectura de gramática desde .txt
  2) Simplificación + conversión a CNF (eliminación de símbolos inútiles, ε, unidades, y binarización)
  3) Algoritmo CYK (programación dinámica)
  4) Medición de tiempo
  5) Reconstrucción de un parse tree

Uso:
  python cyk_parser.py --grammar english_grammar.txt --sentence "She eats a cake with a fork" --show-cnf --tree

Formato de gramática (.txt):
  - Una producción por línea:  A -> RHS1 | RHS2 | ...
  - Separar símbolos por espacios. Palabras terminales suelen ser minúsculas; no es obligatorio usar comillas.
  - Ejemplo (del enunciado):
      S  -> NP VP
      VP -> VP PP | V NP | cooks | drinks | eats | cuts
      PP -> P NP
      NP -> Det N | he | she
      V  -> cooks | drinks | eats | cuts
      P  -> in | with
      N  -> cat | dog | beer | cake | juice | meat | soup | fork | knife | oven | spoon
      Det -> a | the

Notas:
  - El programa convierte automáticamente a CNF; también admite gramáticas que ya vengan en CNF.
  - La oración se tokeniza por espacios y se normaliza a minúsculas para empatar los terminales.
"""

import argparse
import time
import sys
from collections import defaultdict, deque
from typing import Dict, List, Set, Tuple, Optional

RHS = Tuple[str, ...]         # una producción A -> X1 X2 ... Xk se representa como tupla
Grammar = Dict[str, Set[RHS]] # mapa: NoTerminal -> conjunto de RHS (tuplas)

# ------------------------------------------------------------
# Utilidades de lectura y escritura
# ------------------------------------------------------------

def is_nonterminal(sym: str) -> bool:
    # Regla práctica: si inicia con mayúscula (p.ej., S, NP, Det) lo tratamos como NoTerminal
    return len(sym) > 0 and sym[0].isupper()

def parse_grammar(path: str) -> Grammar:
    """
    Lee el archivo de gramática y devuelve un diccionario:
        G[A] = { (X1, X2, ...), (...), ... }
    Ignora líneas vacías o comentarios (líneas que inician con '#').
    """
    G: Grammar = defaultdict(set)
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "->" not in line:
                raise ValueError(f"Línea inválida (falta '->'): {line}")
            left, right = [x.strip() for x in line.split("->", 1)]
            if not left:
                raise ValueError(f"Izquierda vacía: {line}")
            alts = [alt.strip() for alt in right.split("|")]
            for alt in alts:
                if alt == "" or alt == "ε" or alt == "e" or alt == "epsilon":
                    G[left].add(tuple())  # epsilon
                else:
                    G[left].add(tuple(alt.split()))
    return G

def pretty_grammar(G: Grammar, title="Gramática"):
    lines = [f"=== {title} ==="]
    for A in sorted(G.keys()):
        rhss = [" ".join(rhs) if rhs else "ε" for rhs in sorted(G[A])]
        lines.append(f"{A} -> " + " | ".join(rhss))
    return "\n".join(lines)

# ------------------------------------------------------------
# Simplificación y Conversión a CNF
# ------------------------------------------------------------

def remove_non_generating(G: Grammar) -> Grammar:
    """
    Elimina símbolos no generadores (que nunca derivan cadenas de terminales).
    """
    generating: Set[str] = set()
    changed = True
    while changed:
        changed = False
        for A, rhss in G.items():
            if A in generating:
                continue
            for rhs in rhss:
                # rhs es generadora si todos los símbolos son terminales o NT generadores
                ok = True
                for X in rhs:
                    if is_nonterminal(X) and X not in generating:
                        ok = False
                        break
                if ok:
                    generating.add(A)
                    changed = True
                    break

    # filtrar G dejando solo A generadores y RHS con símbolos permitidos
    G2: Grammar = defaultdict(set)
    for A, rhss in G.items():
        if A not in generating:  # descartar NT no generador
            continue
        for rhs in rhss:
            keep = True
            for X in rhs:
                if is_nonterminal(X) and X not in generating:
                    keep = False
                    break
            if keep:
                G2[A].add(rhs)
    return G2

def reachable_from_start(G: Grammar, S: str) -> Set[str]:
    """
    Símbolos alcanzables desde S.
    """
    reachable: Set[str] = {S}
    q = deque([S])
    while q:
        A = q.popleft()
        for rhs in G.get(A, []):
            for X in rhs:
                if is_nonterminal(X) and X not in reachable:
                    reachable.add(X)
                    q.append(X)
    return reachable

def remove_unreachable(G: Grammar, S: str) -> Grammar:
    R = reachable_from_start(G, S)
    G2: Grammar = defaultdict(set)
    for A in G:
        if A in R:
            for rhs in G[A]:
                # filtrar RHS que contengan no terminales inalcanzables
                if all((not is_nonterminal(X)) or (X in R) for X in rhs):
                    G2[A].add(rhs)
    return G2

def eliminate_epsilon(G: Grammar, S: str) -> Tuple[Grammar, bool]:
    """
    Elimina producciones ε excepto quizá S -> ε si S puede derivar ε.
    Retorna (G_sin_epsilon, keep_start_epsilon).
    """
    # 1) Encontrar NT anulables
    nullable: Set[str] = set()
    changed = True
    while changed:
        changed = False
        for A, rhss in G.items():
            if A in nullable:
                continue
            for rhs in rhss:
                if len(rhs) == 0 or all(is_nonterminal(X) and X in nullable for X in rhs):
                    nullable.add(A)
                    changed = True
                    break

    # 2) Construir nuevas RHS quitando combinaciones de anulables
    G2: Grammar = defaultdict(set)
    for A, rhss in G.items():
        for rhs in rhss:
            if len(rhs) == 0:
                # omitimos ε por ahora; lo agregamos al final si aplica
                continue
            # generar subconjuntos donde se borran NT anulables
            indices_nullable = [i for i, X in enumerate(rhs) if is_nonterminal(X) and X in nullable]
            # enumerar todas las máscaras de borrado
            n = len(indices_nullable)
            masks = range(1 << n)
            seen_local = set()
            for m in masks:
                # construir nueva rhs
                new_rhs = []
                skip_idx = {indices_nullable[j] for j in range(n) if (m & (1 << j))}
                for i, X in enumerate(rhs):
                    if i not in skip_idx:
                        new_rhs.append(X)
                new_rhs = tuple(new_rhs)
                if len(new_rhs) == 0:
                    # ε: la agregamos solo si A es S, lo manejamos al final
                    pass
                else:
                    if new_rhs not in seen_local:
                        G2[A].add(new_rhs)
                        seen_local.add(new_rhs)

    # 3) Conservar S -> ε si S era anulable
    keep_start_epsilon = (S in nullable)
    if keep_start_epsilon:
        G2[S].add(tuple())

    return G2, keep_start_epsilon

def eliminate_unit(G: Grammar) -> Grammar:
    """
    Elimina producciones unitarias A -> B (con A,B no terminales).
    """
    unit_pairs = set()  # (A,B) si A =>* B por unidades
    for A in G:
        unit_pairs.add((A, A))

    changed = True
    while changed:
        changed = False
        for A, rhss in G.items():
            for rhs in rhss:
                if len(rhs) == 1 and is_nonterminal(rhs[0]):
                    B = rhs[0]
                    for (X, Y) in list(unit_pairs):
                        pass
                    if (A, B) not in unit_pairs:
                        unit_pairs.add((A, B))
                        changed = True

        # Cierre transitivo simple
        more = True
        while more:
            more = False
            for (A, B) in list(unit_pairs):
                for (C, D) in list(unit_pairs):
                    if B == C and (A, D) not in unit_pairs:
                        unit_pairs.add((A, D))
                        more = True

    # Construir G' sin unidades
    G2: Grammar = defaultdict(set)
    for A in G:
        # Agregar todas las RHS no unitarias de B para cada (A,B)
        for (X, B) in unit_pairs:
            if X != A:
                continue
            for rhs in G.get(B, set()):
                if len(rhs) == 1 and is_nonterminal(rhs[0]):
                    # unit — saltar
                    continue
                G2[A].add(rhs)
    return G2

def terminals_to_unaries(G: Grammar) -> Tuple[Grammar, Dict[str, str]]:
    """
    En RHS de longitud >= 2, reemplaza terminales por nuevos preterminales T_x:
       A -> B a C  ==>  A -> B Ta C,  con Ta -> a
    Devuelve la gramática modificada y el mapa terminal->preterminal.
    """
    Tmap: Dict[str, str] = {}  # terminal -> preterminal
    G2: Grammar = defaultdict(set)
    fresh_id = 0

    def get_preterminal(a: str) -> str:
        nonlocal fresh_id
        if a not in Tmap:
            name = f"T_{a}"
            # evitar colisiones
            while name in G or name in G2:
                fresh_id += 1
                name = f"T_{a}_{fresh_id}"
            Tmap[a] = name
            G2[name].add((a,))
        return Tmap[a]

    for A, rhss in G.items():
        for rhs in rhss:
            if len(rhs) >= 2:
                new_rhs = []
                for X in rhs:
                    if is_nonterminal(X):
                        new_rhs.append(X)
                    else:
                        new_rhs.append(get_preterminal(X))
                G2[A].add(tuple(new_rhs))
            else:
                # longitud 0 o 1 se copian, no forzamos unarios A->a (CNF lo permite)
                G2[A].add(rhs)

    return G2, Tmap

def binarize(G: Grammar) -> Grammar:
    """
    Para RHS con longitud > 2, introduce NT intermedios:
      A -> B C D  ==>  A -> B X1, X1 -> C D
    """
    G2: Grammar = defaultdict(set)
    fresh = 0

    for A, rhss in G.items():
        for rhs in rhss:
            if len(rhs) <= 2:
                G2[A].add(rhs)
                continue
            # romper en cadena binaria
            symbols = list(rhs)
            left = symbols[0]
            rest = symbols[1:]
            # construir A -> left X1; X1 -> next X2; ...; Xk -> last-1 last
            prev_left = left
            for i in range(len(rest) - 2):
                fresh += 1
                Z = f"BIN_{A}_{fresh}"
                G2[A if i == 0 else last_Z].add((prev_left, Z))
                prev_left = rest[i]
                last_Z = Z
            # cerrar con los dos últimos
            G2[last_Z].add((prev_left, rest[-1]))

    return G2

def to_cnf(G: Grammar, start_symbol: str) -> Grammar:
    """
    Pipeline estándar:
      1) Eliminar no generadores
      2) Eliminar inalcanzables
      3) Eliminar ε
      4) Eliminar unitarias
      5) Reemplazar terminales en RHS largas
      6) Binarizar
    """
    # Copia defensiva
    Gwork: Grammar = defaultdict(set)
    for A, rhss in G.items():
        for rhs in rhss:
            Gwork[A].add(rhs)

    # 1) & 2)
    Gwork = remove_non_generating(Gwork)
    Gwork = remove_unreachable(Gwork, start_symbol)

    # 3) ε
    Gwork, keep_start_epsilon = eliminate_epsilon(Gwork, start_symbol)

    # 4) unitarias
    Gwork = eliminate_unit(Gwork)

    # 5) terminales en RHS >= 2
    Gwork, _ = terminals_to_unaries(Gwork)

    # 6) binarizar
    Gwork = binarize(Gwork)

    # Asegurar que si S -> ε era válido se mantenga (permitido en CNF extendida)
    if keep_start_epsilon:
        Gwork[start_symbol].add(tuple())

    return Gwork

# ------------------------------------------------------------
# Algoritmo CYK + backpointers para árbol
# ------------------------------------------------------------

BackPtr = Tuple[int, str, str, Optional[Tuple], Optional[Tuple]]
# (k, B, C, left_ptr, right_ptr) para A@cell(i,j)

def cyk(sentence: List[str], G: Grammar, S: str):
    """
    CYK clásico con tabla P[i][j] (i=start, j=len), i in [0..n-1], j in [1..n-i]
    Además de P, construimos backpointers para reconstruir árbol.
    """
    n = len(sentence)
    if n == 0:
        # cadena vacía: aceptar si S -> ε
        accepts = any(len(rhs) == 0 for rhs in G.get(S, []))
        return accepts, {}, {}

    # Indexar producciones inversamente:
    #  A->a   ==>  term_index[a] contiene A
    #  A->BC  ==>  bin_index[(B,C)] contiene A
    term_index: Dict[str, Set[str]] = defaultdict(set)
    bin_index: Dict[Tuple[str, str], Set[str]] = defaultdict(set)

    for A, rhss in G.items():
        for rhs in rhss:
            if len(rhs) == 1 and not is_nonterminal(rhs[0]):
                term_index[rhs[0]].add(A)
            elif len(rhs) == 2 and is_nonterminal(rhs[0]) and is_nonterminal(rhs[1]):
                bin_index[(rhs[0], rhs[1])].add(A)
            elif len(rhs) == 0:
                # ε no participa en relleno de base, pero importa para n==0 (arriba)
                pass
            else:
                # Si llega aquí, la gramática no está en CNF estricta; se puede manejar,
                # pero el pipeline debe haberla reducido. Aún así, intentamos ignorar.
                pass

    # P: tabla de conjuntos
    P: List[List[Set[str]]] = [[set() for _ in range(n + 1)] for _ in range(n)]
    # backpointers: key: (i, j, A) -> BackPtr
    back: Dict[Tuple[int, int, str], BackPtr] = {}

    # Base: long=1
    for i, w in enumerate(sentence):
        for A in term_index.get(w, set()):
            P[i][1].add(A)
            back[(i, 1, A)] = (-1, w, "", None, None)  # hoja: A -> w

    # Largos 2..n
    for L in range(2, n + 1):
        for i in range(0, n - L + 1):
            for k in range(1, L):
                left_len = k
                right_len = L - k
                Bs = P[i][left_len]
                Cs = P[i + left_len][right_len]
                if not Bs or not Cs:
                    continue
                for B in Bs:
                    for C in Cs:
                        for A in bin_index.get((B, C), set()):
                            if A not in P[i][L]:
                                P[i][L].add(A)
                                back[(i, L, A)] = (k, B, C, (i, left_len, B), (i + left_len, right_len, C))

    return (S in P[0][n]), P, back

def build_tree(back: Dict[Tuple[int, int, str], BackPtr], i: int, L: int, A: str):
    """
    Reconstruye árbol como tuplas anidadas:
      (A, left_subtree, right_subtree)  o  (A, 'terminal')
    """
    key = (i, L, A)
    if key not in back:
        return (A,)  # sin información (degradado)
    k, B, C, left_ptr, right_ptr = back[key]
    if k == -1:
        # hoja: (i,1,A) con terminal
        return (A, B)  # B aquí guarda el terminal en back[(i,1,A)] = (-1, w, "", ...)
    # rama binaria
    left_tree = build_tree(back, *left_ptr)
    right_tree = build_tree(back, *right_ptr)
    return (A, left_tree, right_tree)

def print_tree(tree, indent=""):
    """
    Impresión bonita del árbol.
    """
    if len(tree) == 2 and isinstance(tree[1], str):
        # hoja
        print(f"{indent}{tree[0]} → {tree[1]}")
    elif len(tree) == 1:
        print(f"{indent}{tree[0]}")
    else:
        A, L, R = tree
        print(f"{indent}{A}")
        print_tree(L, indent + "  ")
        print_tree(R, indent + "  ")

# ------------------------------------------------------------
# CLI
# ------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="CYK con conversión a CNF, tiempo y parse tree")
    ap.add_argument("--grammar", required=True, help="Ruta al archivo .txt con la gramática")
    ap.add_argument("--sentence", required=True, help="Oración en inglés a validar")
    ap.add_argument("--start", default="S", help="Símbolo inicial (default: S)")
    ap.add_argument("--show-cnf", action="store_true", help="Imprimir gramática en CNF resultante")
    ap.add_argument("--tree", action="store_true", help="Imprimir árbol de derivación si acepta")
    args = ap.parse_args()

    # 1) Leer gramática
    G = parse_grammar(args.grammar)

    # 2) Convertir a CNF
    Gcnf = to_cnf(G, args.start)

    if args.show_cnf:
        print(pretty_grammar(Gcnf, title="CNF"))

    # 3) Preparar oración (normalizamos a minúsculas)
    sent = [tok.strip() for tok in args.sentence.strip().split() if tok.strip()]
    sent = [w.lower() for w in sent]
    print(f"Oración: {' '.join(sent)}\n")

    # 4) CYK + tiempo
    t0 = time.perf_counter()
    accepts, P, back = cyk(sent, Gcnf, args.start)
    dt = (time.perf_counter() - t0) * 1000.0  # ms

    # 5) Salidas requeridas
    print("Resultado:", "SÍ" if accepts else "NO")
    print(f"Tiempo: {dt:.3f} ms")

    # 6) Árbol (si acepta)
    if accepts and args.tree:
        print("\nParse tree:")
        tree = build_tree(back, 0, len(sent), args.start)
        print_tree(tree)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
            print("ERROR:", e)
            sys.exit(1)
