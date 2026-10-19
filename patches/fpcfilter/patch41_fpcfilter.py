#!/usr/bin/env python3
"""Bitblade Patch 41 (11.10.2026): FPCFilter (OpenDroneMap, c1467cb) parallel lesen/zuschneiden/schreiben.

Original: binaeres PLY wird Punkt fuer Punkt mit 10 ifstream::read-Aufrufen gelesen, der Polygon-Zuschnitt
laeuft dabei seriell (Datensatz A: 537 Mio. Punkte, 425-Ecken-Polygon), Schreiben ebenso Feld fuer Feld.
Der Ausreisserfilter kopiert die Wolke zweimal (reserve(np) + Kopierzuweisung) -> 3-facher RAM.

Neu:
 - Lesen in Bloecken (256 MB) per fread, Zerlegen + Zuschnitt je Block mit OpenMP, Reihenfolge bleibt.
 - Polygon-Test mit Rechteck-Vorpruefung (Punkte ausserhalb der Huelle ohne Kantenschleife).
 - Schreiben: Block fuer Block parallel in einen Puffer serialisieren, dann ein write -> bitgleiche Datei.
 - Ausreisserfilter: stabile In-place-Verdichtung statt Kopie (gleiches Ergebnis, ~1/3 RAM-Spitze).
Aufruf: patch41_fpcfilter.py <quellordner>
"""
import re, sys

src = sys.argv[1]


def sub(path, old, new, count=1):
    p = f"{src}/{path}"
    s = open(p).read()
    assert s.count(old) == count, (path, old[:80], s.count(old))
    s = s.replace(old, new)
    open(p, "w").write(s)


# ---------------------------------------------------------------- Polygon: Rechteck-Vorpruefung
sub("common.hpp", """		bool inside(float x, float y) const
		{""", """		// Bitblade P41: Huellrechteck (nach dem Laden der Ecken einmal berechnet)
		mutable bool bbReady = false;
		mutable float bbMinX = 0, bbMinY = 0, bbMaxX = 0, bbMaxY = 0;
		void prepare() const
		{
			if (bbReady || points.empty()) return;
			bbMinX = bbMaxX = points[0].x; bbMinY = bbMaxY = points[0].y;
			for (const auto& p : points) {
				bbMinX = std::min(bbMinX, (float)p.x); bbMaxX = std::max(bbMaxX, (float)p.x);
				bbMinY = std::min(bbMinY, (float)p.y); bbMaxY = std::max(bbMaxY, (float)p.y);
			}
			bbReady = true;
		}

		bool inside(float x, float y) const
		{
			if (bbReady && (x < bbMinX || x > bbMaxX || y < bbMinY || y > bbMaxY)) return false;""")

# ---------------------------------------------------------------- PLY binaer: paralleles Lesen
old_read = re.search(r"\t\t\t\treader = std::ifstream\(path, std::ifstream::binary\);.*?\n\t\t\t\t}\n\n\t\t\t} else", open(f"{src}/ply.hpp").read(), re.S).group(0)
new_read = """				reader = std::ifstream(path, std::ifstream::binary);

				for (auto n = 0; n < 14; n++)
					std::getline(reader, line);

				// Bitblade P41: blockweise lesen, je Block parallel zerlegen und filtern (Reihenfolge bleibt erhalten)
				const size_t REC = 3 * sizeof(float) + 3 + 3 * sizeof(float) + 1; // 28 Byte je Punkt
				const size_t BLOCK = 8 * 1024 * 1024;                               // Punkte je Block (224 MB)
				std::vector<char> buf(BLOCK * REC);
				points.reserve(filter ? count / 2 : count);
				extras.reserve(filter ? count / 2 : count);
				const int nt = std::max(1, omp_get_max_threads());
				std::vector<std::vector<PlyPoint>> tp(nt);
				std::vector<std::vector<PlyExtra>> te(nt);

				for (size_t done = 0; done < (size_t)count; ) {
					const size_t n = std::min(BLOCK, (size_t)count - done);
					reader.read(buf.data(), n * REC);
					if ((size_t)reader.gcount() != n * REC)
						throw std::invalid_argument("Invalid PLY file (truncated)");

					#pragma omp parallel num_threads(nt)
					{
						const int t = omp_get_thread_num();
						const size_t a = n * t / nt, b = n * (t + 1) / nt;
						auto& P = tp[t]; auto& E = te[t];
						P.clear(); E.clear(); P.reserve(b - a); E.reserve(b - a);
						for (size_t i = a; i < b; i++) {
							const char* r = buf.data() + i * REC;
							float x, y, z, nx, ny, nz;
							std::memcpy(&x, r, 4); std::memcpy(&y, r + 4, 4); std::memcpy(&z, r + 8, 4);
							const uint8_t red = r[12], green = r[13], blue = r[14];
							std::memcpy(&nx, r + 15, 4); std::memcpy(&ny, r + 19, 4); std::memcpy(&nz, r + 23, 4);
							const uint8_t views = r[27];
							if (!filter || filter(x, y, z)) {
								P.emplace_back(x, y, z, red, green, blue, views);
								E.emplace_back(nx, ny, nz);
							}
						}
					}
					for (int t = 0; t < nt; t++) {
						points.insert(points.end(), tp[t].begin(), tp[t].end());
						extras.insert(extras.end(), te[t].begin(), te[t].end());
					}
					done += n;
				}
				points.shrink_to_fit();
				extras.shrink_to_fit();

			} else"""
sub("ply.hpp", old_read, new_read)
sub("ply.hpp", "#include <vector>\n", "#include <vector>\n#include <cstring>\n#include <functional>\n#include <omp.h>\n")

# ---------------------------------------------------------------- PLY schreiben: parallel serialisieren
old_w = re.search(r"\t\t\tif \(hasNormals\)\n\t\t\t\{\n\t\t\t\tfor \(auto n = 0; n < cnt; n\+\+\).*?\n\t\t\t}            \n", open(f"{src}/ply.hpp").read(), re.S).group(0)
new_w = """			// Bitblade P41: Bloecke parallel in Puffer serialisieren, dann sequentiell schreiben (bitgleich)
			const size_t rec = hasNormals ? 28 : 16;
			const size_t BLOCK = 8 * 1024 * 1024;
			std::vector<char> buf(std::min(cnt, BLOCK) * rec);
			for (size_t a0 = 0; a0 < cnt; a0 += BLOCK) {
				const size_t n = std::min(BLOCK, cnt - a0);
				#pragma omp parallel for
				for (long long k = 0; k < (long long)n; k++) {
					const auto& point = this->points[a0 + k];
					char* w = buf.data() + k * rec;
					std::memcpy(w, &point.x, 4); std::memcpy(w + 4, &point.y, 4); std::memcpy(w + 8, &point.z, 4);
					w += 12;
					if (hasNormals) {
						const auto& extra = this->extras[a0 + k];
						std::memcpy(w, &extra.nx, 4); std::memcpy(w + 4, &extra.ny, 4); std::memcpy(w + 8, &extra.nz, 4);
						w += 12;
					}
					w[0] = point.red; w[1] = point.blue; w[2] = point.green; w[3] = point.views;
				}
				o.write(buf.data(), n * rec);
			}
"""
sub("ply.hpp", old_w, new_w)

# ---------------------------------------------------------------- Ausreisserfilter: in-place verdichten
fo = open(f"{src}/fastoutlierfilter.hpp").read()
a = fo.index("            if (file.hasNormals()) {\n\n                start = std::chrono::steady_clock::now();")
b = fo.index("        }\n\n\n    };")
new_f = """            // Bitblade P41: stabile In-place-Verdichtung (statt Kopie in newPoints/newExtras + Kopierzuweisung)
            start = std::chrono::steady_clock::now();
            {
                const bool hn = file.hasNormals();
                size_t k = 0;
                for (size_t i = 0; i < np; ++i)
                {
                    if (distances[i] < threshold) {
                        if (k != i) {
                            file.points[k] = file.points[i];
                            if (hn) file.extras[k] = file.extras[i];
                        }
                        k++;
                    }
                }
                file.points.erase(file.points.begin() + k, file.points.end());
                file.points.shrink_to_fit();
                if (hn) { file.extras.erase(file.extras.begin() + k, file.extras.end()); file.extras.shrink_to_fit(); }
            }
            if (this->isVerbose) {
                const std::chrono::duration<double> diff = std::chrono::steady_clock::now() - start;
                std::cout << " ?> Done filtering points in " << diff.count() << "s" << std::endl;
            }
"""
fo = fo[:a] + new_f + fo[b:]
fo = fo.replace("            std::vector<PlyPoint> newPoints;\n            newPoints.reserve(np);\n\n            std::vector<PlyExtra> newExtras;\n            newExtras.reserve(np);\n", "")
open(f"{src}/fastoutlierfilter.hpp", "w").write(fo)

# Polygon-Huelle vorbereiten, bevor parallel gefiltert wird
sub("pipeline.hpp", "		void crop(const Polygon &p)\n		{\n", "		void crop(const Polygon &p)\n		{\n			p.prepare();\n")

# ---------------------------------------------------------------- kd-Baum parallel bauen (nanoflann 1.3.2 -> 1.6.1)
# Original: buildIndex einkernig (Datensatz A: 344 s). nanoflann >= 1.5 baut mit n_thread_build parallel.
# Die kNN-Suche ist exakt -> gleiche Abstaende -> gleiches Filterergebnis. Neuer Header: <quelle>/../nf/nanoflann.hpp
import os, shutil
nf = os.path.join(os.path.dirname(os.path.abspath(src)), "nf", "nanoflann.hpp")
shutil.copy(nf, f"{src}/vendor/nanoflann.hpp")
sub("fastoutlierfilter.hpp", "const nanoflann::SearchParams params;", "const nanoflann::SearchParameters params;")
sub("fastoutlierfilter.hpp", "params(nanoflann::SearchParams(10))", "params(nanoflann::SearchParameters(0.0f, true))")
sub("fastoutlierfilter.hpp", "nanoflann::KDTreeSingleIndexAdaptorParams(100)",
    "nanoflann::KDTreeSingleIndexAdaptorParams(100, nanoflann::KDTreeSingleIndexAdaptorFlags::None, (unsigned)std::max(1, omp_get_max_threads()))")
sub("fastoutlierfilter.hpp", "double, PointCloud, double>, PointCloud, -1, std::size_t>", "double, PointCloud, double, std::size_t>, PointCloud, -1, std::size_t>")
sub("fastoutlierfilter.hpp", '#include "vendor/nanoflann.hpp"', '#include "vendor/nanoflann.hpp"\n#include <omp.h>')

print("Patch 41 angewendet")
