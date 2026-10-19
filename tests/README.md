# Test helpers

* `exif_read_test.py <images…>` – reads images with ODM's `ODM_Photo` (run inside the ODM container) and dumps the
  parsed attributes; used to verify Patch 42 changes nothing for readable images.
* `band_offset_check.py <multispectral orthophoto.tif>` – measures the offset of every band against Green with
  edge correlation in 384 px tiles (Patch 44: NIR 20 px → 1 px).
* `compare_export_openmvs.py <opensfm-dir> <original export_openmvs.py>` – runs the original and the Patch 40
  OpenMVS export on the same input and compares SHA-256 of everything written.
