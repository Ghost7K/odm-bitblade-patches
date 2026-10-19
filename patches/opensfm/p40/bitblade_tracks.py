"""Bitblade Patch 40 (11.10.2026): schnelle Spurbildung fuer OpenSfM create_tracks.

Original (tracking.py): Merkmale Bild fuer Bild laden; Union-Find in reinem Python ueber jedes Treffer-Paar;
danach je Beobachtung Python-Indexzugriffe auf numpy-Felder. Datensatz A: 569 s auf 1 Kern.

Hier:
 - Merkmale mit 16 Threads laden (zlib entpackt ohne GIL).
 - Zusammenhangskomponenten mit scipy.sparse.csgraph (C) statt Python-Union-Find.
 - Reihenfolge exakt wie im Original: Das Original legt die Spuren in der Reihenfolge an, in der das jeweils
   ZUERST gesehene Element einer Komponente in der Folge (im1,f1),(im2,f2),... auftaucht; innerhalb einer Spur
   ebenfalls nach erstem Auftreten. Genau diese Ordnung wird hier aus den Indizes des ersten Auftretens gebildet.
 - Beobachtungswerte werden vorab vektoriell gesammelt; die Schleife ruft nur noch pymap auf.
Ergebnis: gleiche Spur-IDs, gleiche Beobachtungen in gleicher Einfuegereihenfolge -> tracks.csv bitgleich.
"""
import typing as t
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from opensfm import pymap


def load_features(dataset, images):
    def one(im):
        return im, dataset.load_features(im)

    features, colors, segmentations, instances = {}, {}, {}, {}
    with ThreadPoolExecutor(16) as ex:
        for im, fd in ex.map(one, images):   # map liefert in Eingabereihenfolge
            if not fd:
                continue
            features[im] = fd.points[:, :3]
            colors[im] = fd.colors
            sd = fd.semantic
            if sd:
                segmentations[im] = sd.segmentation
                if sd.has_instances():
                    instances[im] = sd.instances
    return features, colors, segmentations, instances


def create_tracks_manager(features, colors, segmentations, instances, matches, min_length):
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    # Bild-Indizes (nur als Schluesselteil; Reihenfolge spielt keine Rolle)
    names = sorted({im for pair in matches for im in pair})
    idx = {im: i for i, im in enumerate(names)}
    seq = []
    for (im1, im2), m in matches.items():
        m = np.asarray(m, dtype=np.int64).reshape(-1, 2)
        if len(m) == 0:
            continue
        s = np.empty(2 * len(m), dtype=np.int64)
        s[0::2] = (idx[im1] << 32) | m[:, 0]
        s[1::2] = (idx[im2] << 32) | m[:, 1]
        seq.append(s)
    tm = pymap.TracksManager()
    if not seq:
        return tm
    S = np.concatenate(seq)
    del seq
    keys, first, inv = np.unique(S, return_index=True, return_inverse=True)
    n = len(keys)
    a, b = inv[0::2], inv[1::2]
    g = coo_matrix((np.ones(len(a), dtype=np.int8), (a, b)), shape=(n, n)).tocsr()
    ncomp, lab = connected_components(g, directed=False)
    del g, a, b, inv, S

    # Komponenten-Reihenfolge = erstes Auftreten eines ihrer Elemente; Elemente je Komponente nach erstem Auftreten
    cfirst = np.full(ncomp, np.iinfo(np.int64).max, dtype=np.int64)
    np.minimum.at(cfirst, lab, first)
    crank = np.empty(ncomp, dtype=np.int64)
    crank[np.argsort(cfirst, kind="stable")] = np.arange(ncomp)
    order = np.lexsort((first, crank[lab]))          # Knoten in Ausgabereihenfolge
    img = (keys >> 32).astype(np.int64)
    feat = (keys & 0xFFFFFFFF).astype(np.int64)

    # Gute Spuren: Laenge >= min_length und kein Bild doppelt
    size = np.bincount(lab, minlength=ncomp)
    pair = np.unique(lab.astype(np.int64) * len(names) + img)
    uniq = np.bincount(pair // len(names), minlength=ncomp)
    good = (size >= min_length) & (uniq == size)
    tid = -np.ones(ncomp, dtype=np.int64)
    gc = np.nonzero(good)[0]
    tid[gc[np.argsort(crank[gc], kind="stable")]] = np.arange(len(gc))

    sel = order[good[lab[order]]]
    t_ids = tid[lab[sel]]
    i_ids = img[sel]
    f_ids = feat[sel]

    NO_VALUE = pymap.Observation.NO_SEMANTIC_VALUE
    # Werte je Bild vektoriell holen, dann in Ausgabereihenfolge durchlaufen
    xs = np.zeros(len(sel)); ys = np.zeros(len(sel)); ss = np.zeros(len(sel))
    rs = np.zeros(len(sel), np.int64); gs = np.zeros(len(sel), np.int64); bs = np.zeros(len(sel), np.int64)
    segv = np.full(len(sel), NO_VALUE, dtype=np.int64); insv = np.full(len(sel), NO_VALUE, dtype=np.int64)
    has = np.zeros(len(sel), bool)
    o = np.argsort(i_ids, kind="stable")          # einmal nach Bild gruppieren
    bounds = np.searchsorted(i_ids[o], np.arange(len(names) + 1))
    for i, im in enumerate(names):
        if im in features:
            _fill(o[bounds[i]:bounds[i + 1]], im, f_ids, features, colors, segmentations, instances,
                  xs, ys, ss, rs, gs, bs, segv, insv, has)

    L = [x.tolist() for x in (t_ids, i_ids, f_ids, xs, ys, ss, rs, gs, bs, segv, insv, has)]
    tstr = [str(k) for k in range(len(gc))]
    Obs, add = pymap.Observation, tm.add_observation
    for tk, ik, fk, x, y, s, r, g_, b_, sg, ins, h in zip(*L):
        if not h:
            continue
        add(names[ik], tstr[tk], Obs(x, y, s, r, g_, b_, fk, sg, ins))
    return tm


def _fill(w, im, f_ids, features, colors, segmentations, instances, xs, ys, ss, rs, gs, bs, segv, insv, has):
    if len(w) == 0:
        return
    f = f_ids[w]
    p = features[im][f]
    xs[w], ys[w], ss[w] = p[:, 0], p[:, 1], p[:, 2]
    c = colors[im][f]
    rs[w], gs[w], bs[w] = c[:, 0], c[:, 1], c[:, 2]
    if im in segmentations:
        segv[w] = segmentations[im][f]
    if im in instances:
        insv[w] = instances[im][f]
    has[w] = True
