"""Line a cpu-trace.sh trace up with a Clarity run's view opens (MIT). Reads files only.

For each graded view open in the run (refstart-<n>.json: navigation to usable), prints the device's
busy share of all cores, the CPU clock it ran at, and each kiosk process's (and its main thread's,
and the voice threads') share of one core over that window. Used for #244.

  python3 -I tools/perf-lab/cpu-align.py TRACE CLARITY_OUT_DIR [--view typical-nocam]
"""
import bisect
import collections
import glob
import json
import os
import sys

trace, outdir = sys.argv[1:3]
only = sys.argv[sys.argv.index("--view") + 1] if "--view" in sys.argv else None
HZ = 100


def jiffies(stat):
    f = stat.rpartition(")")[2].split()
    return int(f[11]) + int(f[12])  # utime + stime (fields 14 and 15)


samples = []  # (uptime, {key: jiffies}, cpu_busy, cpu_total, freq)
offset = None  # epoch - uptime
cur = None
for line in open(trace, errors="replace"):
    kind, _, rest = line.rstrip("\n").partition(" ")
    if kind == "E":
        epoch, up = rest.split()[:2]
        offset = float(epoch) - float(up)
    elif kind == "U":
        if cur:
            samples.append(cur)
        cur = [float(rest), {}, 0, 0, None]
    elif cur is None:
        continue
    elif kind == "C" and rest.startswith("cpu "):
        v = [int(x) for x in rest.split()[1:8]]
        cur[2], cur[3] = sum(v) - v[3] - v[4], sum(v)
    elif kind == "F":
        cur[4] = int(rest)
    elif kind in ("P", "M", "H"):
        head, _, stat = rest.partition("|")
        ident, name = head.split(" ", 1)
        key = {"P": name, "M": name + " [main thread]", "H": "  thread " + name}[kind]
        try:
            cur[1][key] = jiffies(stat)
        except (IndexError, ValueError):
            pass
if cur:
    samples.append(cur)
times = [s[0] for s in samples]


def window(t0, t1):
    i, j = bisect.bisect_left(times, t0), bisect.bisect_right(times, t1) - 1
    if i >= j:
        return None
    a, b = samples[i], samples[j]
    dt = b[0] - a[0]
    shares = {k: 100 * (b[1][k] - a[1][k]) / HZ / dt for k in b[1] if k in a[1]}
    freqs = collections.Counter(s[4] for s in samples[i:j + 1])
    return dt, 100 * (b[2] - a[2]) / max(1, b[3] - a[3]), shares, freqs


for path in sorted(glob.glob(os.path.join(outdir, "refstart-*.json"))):
    r = json.load(open(path))
    for view, t in (r.get("tiers") or {}).items():
        p = (t or {}).get("page") or {}
        u = p.get("usable") or {}
        if (only and view != only) or "nav_ms" not in p or u.get("interactive_ms") is None:
            continue
        o = p["origin_epoch_ms"] / 1000
        t0, t1 = o + p["nav_ms"] / 1000 - offset, o + u["interactive_ms"] / 1000 - offset
        w = window(t0, t1)
        print(f"run {r.get('run')} {view}: opens in {u['interactive_ms'] - p['nav_ms']:.0f} ms")
        if not w:
            print("  not in the trace")
            continue
        dt, busy, shares, freqs = w
        print(f"  traced {dt:.2f} s; device busy {busy:.0f}% of all cores; clock {dict(freqs)}")
        for k, v in sorted(shares.items(), key=lambda kv: -kv[1]):
            if v >= 1:
                print(f"  {v:6.1f}% of a core  {k.replace('_disable_art_image_', '')}")
