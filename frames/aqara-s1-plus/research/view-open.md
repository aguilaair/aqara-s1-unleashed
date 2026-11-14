# Opening a view: where typical's 4.7 s goes on the S1 (#244)

**Status (2026-11-14): partly answered.** The open is one thread's work: HA's frontend building
the view's 50 cards on Gecko's content main thread, which is about two-thirds JavaScript. Background
load is small. The CPU runs at 1.2 GHz of its 1.608 GHz, held there by Allwinner's power HAL, not
by heat. Panel runs that split each core's time during an open, and the app-side candidates, are
still pending.

Device: Aqara S1 Plus, Android 10 (`peony-perf1`), S1 Kiosk 0.4.3 builds of main (5d0a0d2),
GeckoView 159, the radio in `thread_router`. Tools: Clarity v1 (#205 at aedb6c7d), desktop Firefox
160 with the Gecko profiler, `tools/perf-lab/`.

## Question

Clarity's typical view without a camera (`typical-nocam`, 50 cards) opens in 4.7 s on the S1. The
bar for a C is 4 s, and this is the only thing between the S1 and a C. Where does the time go, and
what can the app change? Clarity measures "open the view" from HA's own navigation (`pushState`
and `location-changed`) to usable: the first screen drawn and stable for two frames, then the main
thread running every task within 50 ms for 500 ms ([docs/perf.md](../../../docs/perf.md#usable)).

## What we tried

1. **The runs Clarity already recorded** (2026-11-14, verified, read from `report.json` and
   `refstart-<n>.json`). Two graded runs each from s1rtc6 and s1rtc7 (s1rtc7's run 2 had the screen
   go off and isn't counted):

   | Run | Drawn | Usable | `busy_ms` (longest probe wait in each second after drawn) |
   |---|---|---|---|
   | s1rtc6 #1 | 974 ms | 4896 ms | 1089, 767, 359, 211, 40 |
   | s1rtc6 #2 | 741 ms | 4533 ms | 1192, 762, 332, 161, 23 |
   | s1rtc7 #1 | 960 ms | 4969 ms | 1368, 909, 367, 171, 19 |
   | s1rtc7 #3 | 738 ms | 4463 ms | 1139, 630, 331, 166, 19 |

   The first screen is drawn in under 1 s. The other 3.6 to 4.0 s is the main thread staying busy:
   a task of 1.1 to 1.4 s right after the first screen, then shorter ones of 160 to 900 ms. The
   median is 4.7 s and the spread is ±5%, so a change smaller than about 5% needs three runs a side
   to show.

2. **What the main thread does: a desktop Gecko profile of the same open** (2026-11-14, verified
   on desktop, inferred for the S1). `tools/perf-lab/profile-view.sh` serves Clarity's fake HA and
   harness to desktop Firefox 160 at a 911 × 439 CSS viewport and 1.5 device pixels per px, opens the
   start view, then opens `typical-nocam` the way the runner does. `split.py` splits the content main
   thread's CPU from the navigation to usable. Two runs:

   | Category | Run 1 | Run 2 |
   |---|---|---|
   | JavaScript | 65.0% | 67.7% |
   | of which interpreters and JIT compiling | 30% | 25% |
   | DOM | 16.5% | 10.6% |
   | Layout (style, reflow, frame construction) | 7.6% | 7.2% |
   | Graphics (display lists) | 2.8% | 3.6% |
   | GC / CC | 1.0% | 5.4% |

   The main thread used 438 and 422 ms of CPU, and the parent process and the renderer about 50 ms
   each. Desktop drew the first screen at 0.17 to 0.22 s and was usable at 1.0 s. The S1 takes 0.86
   and 4.7 s, about the same 1 : 5.5 ratio, about 5× slower. So the open is HA's own JavaScript
   building cards (Lit templates, custom elements, shadow roots). Layout and painting are about a
   tenth of it. Gecko prefs for layout, painting or GC can move at most that tenth.

3. **Lower JIT thresholds** (2026-11-14, verified on desktop). A quarter of the JavaScript time
   runs in the interpreters or in compiling, because this is the first time the view's cards are
   built. Two settings, alternated with the default, two runs each, main-thread CPU over the open:

   | Prefs | Run 1 | Run 2 |
   |---|---|---|
   | default (`baselinejit.threshold` 100, `ion.threshold` 1500) | 274 ms | 270 ms |
   | 30 and 500 | 269 ms | 281 ms |
   | 10 and 200, `blinterp.threshold` 2 | 292 ms | 232 ms |

   The interpreted share fell from 28% to 21 to 24% (these runs' own split), but the total didn't move outside the noise.
   This was the profiler at 1 ms, on a fast core. The panel's in-order Cortex-A53 cores may treat
   interpreted code worse; that is untested (test build `244-jit`).

4. **Who else runs on the four cores** (2026-11-14, verified, read from s1rtc6's idle samples, 15 s
   each):

   | Sample | Device busy (all cores) | Kiosk main process | Tab | GPU process |
   |---|---|---|---|---|
   | Your dashboard, idle, all panes on (3 samples) | 13.1 to 15.1% | 9.6 to 9.8% of a core | 6.0 to 6.4% | 1.5% |
   | Typical with its camera playing, idle (2 samples) | 39.0 to 42.9% | 18.3 to 19.8% | 21.3 to 21.9% | 32.0 to 34.1% |

   With nothing on screen changing, the kiosk itself uses about a tenth of one core (microWakeWord
   since #181; it was 37% with openWakeWord, [idle-cpu.md](idle-cpu.md)). The open runs on one main
   thread, so three cores are mostly free. No sample was taken during an open; the panel plan in
   #244 adds one (`tools/perf-lab/cpu-trace.sh`).

5. **Priorities** (2026-11-14, verified, read-only):
   ```
   $ adb shell 'for p in <kiosk pids>; do cat /proc/$p/oom_score_adj; cut -d" " -f19 /proc/$p/stat; done'
   sh.edm.s1kiosk                                 oom 0    nice -10
   sh.edm.s1kiosk:sandboxed_tab_..._3 (the page)  oom 0    nice -10
   sh.edm.s1kiosk:gpu_...                         oom 0    nice -10
   $ adb shell 'cat /proc/<main pid>/task/<voice-mic tid>/stat'   # field 19
   voice-mic ... -19
   ```
   The page's content process already runs at foreground priority, so raising it isn't a lever.
   The microphone thread runs at `THREAD_PRIORITY_URGENT_AUDIO` (nice -19,
   `Microphone.kt:79`), and the wake word model ran on it (`VoiceEngine.kt` `onMicFrame`), so it
   took a core from the page's main thread whenever they shared one. At about a tenth of a core,
   the most that can cost an open is about 0.4 s, if every frame collided. That is unlikely with three
   cores free. Test build `244-ww-thread` moves the model to its own normal-priority thread.

6. **Memory** (2026-11-14, verified, read from s1rtc6 and logcat). The lowest `MemAvailable` during
   the graded tasks was 671 MB, against a 296 MB budget. The app's only lowmemorykiller entries in
   that logcat were of other apps' cached processes. The kiosk's own ART GC runs every 30 s, frees
   about 4 MB, and takes 140 to 700 ms on a background thread with pauses under 4 ms. Memory isn't the
   limit.

7. **The CPU clock** (2026-11-14, verified, read-only). Sampled every 0.2 s for 6 s while the heavy
   view was loading, with 3 to 20 threads runnable:
   ```
   $ adb shell 'for i in $(seq 1 30); do cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq; sleep 0.2; done' | sort | uniq -c
        30 1200000
   $ adb shell cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_available_frequencies
   408000 600000 816000 1008000 1200000 1320000 1416000 1512000 1608000
   $ adb shell 'cat /sys/class/thermal/cooling_device0/cur_state /sys/class/thermal/thermal_zone0/temp /sys/class/thermal/thermal_zone0/trip_point_0_temp'
   0
   55369
   70000
   ```
   All four cores share one policy, and it sat at 1.2 GHz under full load. The thermal cooling device
   was off (55 °C, the first passive trip is 70 °C). [idle-cpu.md](idle-cpu.md) saw the same 1.2 GHz
   with the screen on and 1.512 GHz with it off. `scaling_max_freq` and `scaling_governor` belong to
   `system` (mode 660) and aren't readable over adb without root.

   Who sets it, read from the strings of `/vendor/lib/hw/power.peony.so` (Allwinner's "AW Power HAL",
   service `vendor.power-hal-1-0`; not copied into the repo): it writes
   `/sys/devices/system/cpu/cpufreq/policy0/scaling_max_freq`, and has scenes named `NORMAL MODE`,
   `LAUNCH_MODE`, `HOME MODE`, `BENCHMARK MODE`, `BG_MUSIC MODE` and `BOOTCOMPLETE MODE`, the
   frequencies `1200000` and `1512000`, and `persist.vendor.power.enable` (`power_init disable scene
   control`). So the 1.2 GHz is the HAL's normal scene, and an app launch (`POWER_HINT_LAUNCH`) is
   what lifts it for a moment. Which scene sets which ceiling is not yet read from the code. If the
   open scales with the clock, 1.608 GHz would take 4.7 s to about 3.5 s. That is untested. An app
   can't change the scene: Android 10 gives apps no power hints, so this is a root-side question.

## Result

| Part of the 4.7 s | Share | How sure |
|---|---|---|
| First screen drawn | 0.74 to 0.97 s | verified (4 runs) |
| Main thread busy after it | 3.6 to 4.0 s | verified (4 runs) |
| of which HA's JavaScript | about two-thirds | desktop profile, inferred for the S1 |
| of which DOM | 11 to 17% | desktop profile |
| of which layout and painting | about a tenth | desktop profile |
| Background CPU from the kiosk | about 0.1 of one core at idle | verified (idle samples); not yet measured during an open |
| The clock | 1.2 GHz of 1.608, set by the vendor's power HAL | verified (sysfs reads, HAL strings) |

| Lever | Ceiling | Evidence | Where |
|---|---|---|---|
| The CPU clock: the HAL's normal scene caps it at 1.2 GHz | about 25% (4.7 → 3.5 s), if the open scales with the clock | verified cap, untested gain | Root side, not the app |
| Wake word model off the urgent-audio thread | at most about 8% (0.4 s); likely under 3% | read from code and idle samples | App, `244-ww-thread` |
| JIT tier-up thresholds | no change on desktop | verified on desktop (2 runs a side) | App prefs, `244-jit` |
| Layout, paint and GC prefs | about a tenth at most | desktop profile | ruled out as a main lever |
| Content process priority | none: already foreground | verified | ruled out |
| Memory pressure | none: 671 MB free at the peak | verified | ruled out |

So the app alone has little to cut from this open. The big parts are HA's frontend's own work and
the CPU clock the vendor leaves the S1 at.

## How to reproduce

- The desktop profile (this computer only, touches no device): `tools/perf-lab/profile-view.sh
  /tmp/tn typical-nocam --perf <a Clarity checkout with typical-nocam>`. It needs desktop Firefox,
  and the fake HA's frontend cache (`~/.cache/glassworks-perf`, fetched by Clarity on its first run).
  With `--prefs FILE` it adds `user_pref` lines, as for the JIT runs.
- The clock and priorities: the read-only commands above.
- The cores during an open (read-only, adds a little load): `tools/perf-lab/cpu-trace.sh <serial>
  out.trace` while Clarity runs, then `python3 -I tools/perf-lab/cpu-align.py out.trace <clarity
  out dir> --view typical-nocam`.

## Open questions

- How busy the four cores and the page's main thread are during an open on the S1, and at which
  clock (the panel plan in #244, `cpu-trace.sh`).
- Whether moving the wake word model off the urgent-audio thread (`244-ww-thread`) or lower JIT
  thresholds (`244-jit`) move typical-nocam on the panel (three graded runs a side).
- How much a 1.608 GHz ceiling gives, and what it costs in heat. The S1 idles at 55 to 67 °C and
  its first passive trip is 70 °C. Which HAL scene sets which ceiling, from the code at
  `power_hint_platform` and `power_set_interactive_platform`.
- Clarity opens views with `pushState` and no touch. A real tap on a view tab is an input event,
  and Android's PowerManagerService passes user activity to the power HAL as an `INTERACTION` hint
  (not checked in this build). Whether this HAL boosts on it is unknown: none of its strings name it.
