"""
bitblade-patch 32 (10.10.2026): schnelle Netz-Dezimierung vor ReconstructMesh.
ODM dezimiert das Poisson-Netz mit OpenMVS ReconstructMesh (vcglib-Quadric, 1 Kern): Datensatz A 143 Mio. -> 20 Mio.
Flaechen in 21 min. Hier: Binaer-PLY direkt per numpy lesen, Quadric-Dezimierung mit fast_simplification
(Fast-Quadric-Mesh-Simplification, C++), Ergebnis als Binaer-PLY schreiben. Danach ruft der Wrapper das
originale ReconstructMesh mit unveraenderten Argumenten auf (Bereinigung remove-spurious etc.; keine Dezimierung mehr noetig).
Labor (Teilszene Halle, 48 Mio. -> 3,1 Mio. Flaechen): 106 s + 28 s statt 490 s, Abstand Wolke->Netz gleich
(Median 5,88 statt 5,96 cm, p95 21,6 statt 21,7 cm).
Aufruf: bitblade_fastdecimate.py <ein.ply> <aus.ply> <ziel_flaechen>   Exit 0 = ok, 2 = nicht noetig, sonst Fehler.
"""
import sys, time, numpy as np

def read_ply(fn):
    f = open(fn, 'rb'); hdr = []; elems = []
    while True:
        l = f.readline().decode('ascii', 'replace').strip(); hdr.append(l)
        if l.startswith('format') and 'binary_little_endian' not in l: raise RuntimeError('nur binary_little_endian: ' + l)
        if l.startswith('element'): _, name, n = l.split(); elems.append([name, int(n), []])
        elif l.startswith('property'): elems[-1][2].append(l.split()[1:])
        elif l == 'end_header': break
    T = {'float': '<f4', 'float32': '<f4', 'double': '<f8', 'float64': '<f8', 'uchar': 'u1', 'uint8': 'u1', 'char': 'i1', 'int8': 'i1',
         'int': '<i4', 'int32': '<i4', 'uint': '<u4', 'uint32': '<u4', 'short': '<i2', 'int16': '<i2', 'ushort': '<u2', 'uint16': '<u2'}
    off = f.tell(); f.close(); V = F = None
    for name, n, props in elems:
        if name == 'vertex':
            dt = np.dtype([(p[-1], T[p[0]]) for p in props])
            a = np.memmap(fn, dtype=dt, mode='r', offset=off, shape=(n,)); off += n * dt.itemsize
            V = np.column_stack([a['x'], a['y'], a['z']]).astype(np.float64)
        elif name == 'face':
            p = props[0]
            if p[0] != 'list' or len(props) != 1: raise RuntimeError('Flaechenformat nicht unterstuetzt: %s' % props)
            dt = np.dtype([('n', T[p[1]]), ('v', T[p[2]], (3,))])
            a = np.memmap(fn, dtype=dt, mode='r', offset=off, shape=(n,)); off += n * dt.itemsize
            if not np.all(a['n'][:1000] == 3) or not np.all(a['n'] == 3): raise RuntimeError('nicht nur Dreiecke')
            F = np.ascontiguousarray(a['v'], dtype=np.int32)
        else:
            raise RuntimeError('unerwartetes Element ' + name)
    return V, F

def write_ply(fn, V, F):
    with open(fn, 'wb') as f:
        f.write(('ply\nformat binary_little_endian 1.0\nelement vertex %d\nproperty float x\nproperty float y\nproperty float z\n'
                 'element face %d\nproperty list uchar int vertex_indices\nend_header\n' % (len(V), len(F))).encode())
        f.write(np.ascontiguousarray(V, dtype='<f4').tobytes())
        fa = np.empty(len(F), dtype=np.dtype([('n', 'u1'), ('v', '<i4', (3,))])); fa['n'] = 3; fa['v'] = F
        f.write(fa.tobytes())

if __name__ == '__main__':
    src, dst, target = sys.argv[1], sys.argv[2], int(float(sys.argv[3]))
    t0 = time.time(); V, F = read_ply(src); t1 = time.time()
    print('[bitblade] Patch 32: %d Flaechen gelesen (%.0f s), Ziel %d' % (len(F), t1 - t0, target), flush=True)
    if target <= 0 or len(F) <= 1.5 * target:
        print('[bitblade] Patch 32: Dezimierung nicht noetig', flush=True); sys.exit(2)
    import fast_simplification
    # Ursprung abziehen: float32 im Dezimierer, UTM-Koordinaten wuerden Genauigkeit kosten
    o = V.mean(0); Vs, Fs = fast_simplification.simplify((V - o).astype(np.float32), F, target_reduction=1.0 - target / len(F))
    t2 = time.time()
    write_ply(dst, Vs.astype(np.float64) + o, Fs)
    print('[bitblade] Patch 32: %d -> %d Flaechen in %.0f s (gesamt %.0f s)' % (len(F), len(Fs), t2 - t1, time.time() - t0), flush=True)
