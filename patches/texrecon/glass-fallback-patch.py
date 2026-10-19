# Bitblade Patch 22 v2 (08.10.2026): mvs-texturing Zwei-Pass-Ansicht-Auswahl fuer Glas/Fassaden.
# Nur aktiv mit Umgebungsvariable BITBLADE_TEX_FALLBACK=1 (sonst bit-identisch zum bisherigen Verhalten).
#  Pass 1: unveraendert streng (Rueckseiten-Culling, 75 Grad, Verdeckung = alle 3 Eckpunkt-Strahlen frei).
#  Pass 2: NUR fuer Flaechen, die in Pass 1 keine einzige Ansicht bekommen haben (sonst geloescht = Loch):
#          Rueckseiten erlaubt (hinter Glas rekonstruierte Innenflaechen zeigen nach innen), 88 Grad,
#          Verdeckung reduziert nur die Qualitaet (0 Treffer 1.0, 1 Treffer 0.3, 2-3 Treffer 0.05), Rueckseite x0.7.
#          v3: Fallback-Qualitaeten je Flaeche auf das 99,5%-Perzentil der strengen Qualitaeten skaliert (beste Ansicht
#          = 0.8*P), damit die Datenkosten zwischen den Kandidaten unterscheiden (sonst alle ~1 -> Nachbar-Ansicht gewinnt).
#          Die photometrische Ausreisser-Erkennung (gauss_clamping) laeuft danach normal ueber diese Kandidaten.
import sys
p = sys.argv[1] + '/libs/tex/calculate_data_costs.cpp'; s = open(p).read()
assert 'bitblade-fallback' not in s and 'bitblade-lenient' not in s
def rep(a, b):
    global s; assert s.count(a) == 1, a; s = s.replace(a, b)
rep('#include "util.h"', '''#include "util.h"
#include <cstdlib>
/* bitblade-fallback */
static const bool bb_fallback = std::getenv("BITBLADE_TEX_FALLBACK") != nullptr;
static bool bb_pass2 = false;
static std::vector<char> const * bb_only_faces = nullptr;''')
rep('''                std::size_t face_id = i / 3;
''', '''                std::size_t face_id = i / 3;
                if (bb_only_faces && !(*bb_only_faces)[face_id]) continue;
                bool bb_back = false; int bb_hits = 0;
''')
rep('if (viewing_angle < 0.0f || viewing_direction.dot(view_to_face_vec) < 0.0f)',
    'bb_back = viewing_angle < 0.0f;\n                    if ((!bb_pass2 && viewing_angle < 0.0f) || viewing_direction.dot(view_to_face_vec) < 0.0f)')
rep('if (std::acos(viewing_angle) > MATH_DEG2RAD(settings.nadir_mode ? 90.0f : 75.0f))',
    'if (std::acos(bb_pass2 ? std::fabs(viewing_angle) : viewing_angle) > MATH_DEG2RAD(settings.nadir_mode ? 90.0f : (bb_pass2 ? 88.0f : 75.0f)))')
rep('''                        if (bvh_tree.intersect(ray, &hit)) {
                            visible = false;
                            break;
                        }
                    }
                    if (!visible && !settings.nadir_mode) continue;''', '''                        if (bvh_tree.intersect(ray, &hit)) {
                            visible = false;
                            if (!bb_pass2) break;
                            ++bb_hits;
                        }
                    }
                    if (!visible && !settings.nadir_mode && !bb_pass2) continue;''')
rep('''                if (info.quality == 0.0) continue;
''', '''                if (info.quality == 0.0) continue;
                if (bb_pass2 && !settings.nadir_mode) {
                    info.quality *= (bb_hits == 0 ? 1.0f : (bb_hits == 1 ? 0.3f : 0.05f)) * (bb_back ? 0.7f : 1.0f);
                    if (info.quality <= 0.0f) continue;
                }
''')
rep('''    calculate_face_projection_infos(mesh, texture_views, settings, &face_projection_infos);
''', '''    calculate_face_projection_infos(mesh, texture_views, settings, &face_projection_infos);
    if (bb_fallback) {
        std::vector<char> only(num_faces, 0); std::size_t n = 0;
        for (std::size_t i = 0; i < num_faces; ++i)
            if (face_projection_infos[i].empty()) { only[i] = 1; ++n; }
        std::cout << "\\tbitblade fallback: " << n << " faces without strict view -> second pass" << std::endl;
        if (n > 0) {
            std::vector<float> qs; std::size_t cnt = 0;
            for (std::size_t i = 0; i < num_faces; ++i)
                for (FaceProjectionInfo const & info : face_projection_infos[i])
                    if ((cnt++ % 7) == 0) qs.push_back(info.quality);
            float bb_p = 1.0f;
            if (!qs.empty()) {
                std::size_t k = std::min(qs.size() - 1, (std::size_t)(qs.size() * 0.995));
                std::nth_element(qs.begin(), qs.begin() + k, qs.end()); bb_p = qs[k];
            }
            std::vector<float>().swap(qs);
            bb_only_faces = &only; bb_pass2 = true;
            calculate_face_projection_infos(mesh, texture_views, settings, &face_projection_infos);
            bb_only_faces = nullptr; bb_pass2 = false;
            for (std::size_t i = 0; i < num_faces; ++i) {
                if (!only[i] || face_projection_infos[i].empty()) continue;
                float mx = 0.0f;
                for (FaceProjectionInfo const & info : face_projection_infos[i]) mx = std::max(mx, info.quality);
                if (mx <= 0.0f) continue;
                float f = 0.8f * bb_p / mx;
                for (FaceProjectionInfo & info : face_projection_infos[i]) info.quality *= f;
            }
            std::cout << "\tbitblade fallback: strict quality percentile " << bb_p << std::endl;
            std::size_t m = 0;
            for (std::size_t i = 0; i < num_faces; ++i) if (only[i] && !face_projection_infos[i].empty()) ++m;
            std::cout << "\\tbitblade fallback: " << m << " of " << n << " faces got a view in pass 2" << std::endl;
        }
    }
''')
open(p, 'w').write(s); print('Patch 22v3 OK')
