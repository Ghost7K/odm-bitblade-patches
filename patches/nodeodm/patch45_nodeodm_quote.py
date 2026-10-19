#!/usr/bin/env python3
# Patch 45: NodeODM libs/odmRunner.js shQuote -> POSIX single quoting.
# Since NodeODM 7328aba, shQuote strips every " from option values, so JSON options (--boundary, the WebODM crop
# polygon) arrive broken at ODM ("... is not a valid JSON string"). Windows behaviour is unchanged.
# Upstream PR: https://github.com/OpenDroneMap/NodeODM/pull/275
import sys
p = sys.argv[1] if len(sys.argv) > 1 else "/var/www/libs/odmRunner.js"
s = open(p).read()
old = '''const shQuote = s =>  {
    s = String(s).replace(/"/g, "")
    return `"${s}"`;
}'''
new = '''const shQuote = s =>  {
    s = String(s);
    if (os.platform() === "win32"){
        // cmd.exe: wrap in double quotes (double quotes inside values are not supported)
        s = s.replace(/"/g, "");
        return `"${s}"`;
    }else{
        // POSIX shell: single quotes keep the value literally (including double quotes,
        // as needed by JSON options such as --boundary); escape embedded single quotes
        return `'${s.replace(/'/g, `'\\\\''`)}'`;
    }
}'''
if "POSIX shell: single quotes" in s:
    print("Patch 45 already active"); sys.exit(0)
if old not in s:
    print("ERROR Patch 45: original shQuote not found"); sys.exit(1)
open(p, "w").write(s.replace(old, new))
print("Patch 45 active (odmRunner.js shQuote)")
