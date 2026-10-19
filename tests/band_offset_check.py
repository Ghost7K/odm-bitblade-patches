import sys,numpy as np,rasterio,collections
from numpy.fft import fft2,ifft2
from scipy import ndimage as nd
with rasterio.open(sys.argv[1]) as d: a=d.read(); desc=d.descriptions
names=[x or '' for x in desc]; gi=names.index('Green'); m=a[-1]>0
def gm(x): x=nd.gaussian_filter(x.astype(np.float32),1.5); return np.hypot(nd.sobel(x,0),nd.sobel(x,1))
def ncc(x,y,R=30):
    x=(x-x.mean())/(x.std()+1e-9); y=(y-y.mean())/(y.std()+1e-9)
    r=np.real(ifft2(fft2(x)*np.conj(fft2(y))))/x.size
    s=np.fft.fftshift(r); c=r.shape[0]//2; s=s[c-R:c+R+1,c-R:c+R+1]
    i=np.unravel_index(s.argmax(),s.shape); return (int(i[0]-R),int(i[1]-R)), s.max(), s[R,R]
W=384
for b,n in enumerate(names[:-1]):
  if b==gi: continue
  out=[]
  for yy in range(0,a.shape[1]-W,W):
    for xx in range(0,a.shape[2]-W,W):
      if m[yy:yy+W,xx:xx+W].mean()<0.99: continue
      out.append(ncc(gm(a[gi,yy:yy+W,xx:xx+W]),gm(a[b,yy:yy+W,xx:xx+W])))
  mag=np.array([np.hypot(*o[0]) for o in out])
  print(n,len(out),'Top',collections.Counter(o[0] for o in out).most_common(3),'|d| Median %.1f p90 %.1f'%(np.median(mag),np.percentile(mag,90)),'NCC bei 0: %.2f'%np.median([o[2] for o in out]))
