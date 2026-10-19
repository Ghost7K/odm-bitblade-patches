import sys, json
sys.path.insert(0, '/code')
from opendm import types
def d(p):
    x = types.ODM_Photo(p).__dict__.copy(); return {k: (str(v) if not isinstance(v,(int,float,str,type(None),bool)) else v) for k,v in x.items()}
for f in sys.argv[1:]:
    try:
        r = d(f); print('OK', f.split('/')[-1], r.get('camera_model'), r.get('latitude'), r.get('altitude'), r.get('speed_x'), r.get('yaw'))
        json.dump(r, open('/tmp/' + f.split('/')[-1] + '.json', 'w'), sort_keys=True)
    except Exception as e: print('FEHLER', f.split('/')[-1], type(e).__name__)
