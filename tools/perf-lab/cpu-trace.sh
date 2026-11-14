#!/bin/bash
# Who uses the S1's four cores while a view opens (MIT). Read-only on the device: one adb shell
# that reads /proc/stat, the CPU clock and the kiosk's processes (and their main and voice
# threads) every 250 ms with shell builtins, and writes nothing there. It costs the device one
# `sleep` exec per sample, so a run traced with it is a diagnostic run, not a graded one.
# Stop it with Ctrl-C (or kill its PID). cpu-align.py lines it up with a Clarity run (#244).
#
#   ADB=... tools/perf-lab/cpu-trace.sh SERIAL OUT.trace
set -u
SERIAL=$1 OUT=$2
ADB=${ADB:-$HOME/Library/Android/sdk/platform-tools/adb}
exec "$ADB" -s "$SERIAL" shell '
i=0
while :; do
  if [ $((i % 20)) -eq 0 ]; then
    echo "E $(date +%s.%N) $(cat /proc/uptime)"
    L=$(ps -A -o PID,NAME | grep -E "sh\.edm\.s1kiosk|otbr-agent|zigbeed")
    T=""
    m=$(echo "$L" | while read pid name; do [ "$name" = sh.edm.s1kiosk ] && echo $pid; done)
    if [ -n "$m" ]; then
      for t in /proc/$m/task/*; do
        read -r c < $t/comm 2>/dev/null
        case "$c" in voice-*) T="$T $m:${t##*/}:$c" ;; esac
      done
    fi
  fi
  i=$((i + 1))
  read -r up rest < /proc/uptime
  echo "U $up"
  n=0
  while read -r l && [ $n -lt 5 ]; do echo "C $l"; n=$((n + 1)); done < /proc/stat
  read -r f < /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq
  echo "F $f"
  echo "$L" | while read pid name; do
    read -r s < /proc/$pid/stat 2>/dev/null && echo "P $pid $name|$s"
    read -r s < /proc/$pid/task/$pid/stat 2>/dev/null && echo "M $pid $name|$s"
  done
  for x in $T; do
    p=${x%%:*}; r=${x#*:}; t=${r%%:*}; c=${r#*:}
    read -r s < /proc/$p/task/$t/stat 2>/dev/null && echo "H $t $c|$s"
  done
  sleep 0.25
done' > "$OUT"
