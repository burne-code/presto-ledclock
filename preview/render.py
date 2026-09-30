"""Render preview PNGs of led_clock.py on the desktop.

usage: python3 render.py "2026-09-29 09:45:37" [theme] [option=value ...]
"""
import calendar, os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "mock"))
import presto

when = calendar.timegm(time.strptime(sys.argv[1], "%Y-%m-%d %H:%M:%S"))
theme = int(sys.argv[2]) if len(sys.argv) > 2 else 0
overrides = dict(a.split("=") for a in sys.argv[3:])

os.environ["TZ"] = "UTC"; time.tzset()
time.time = lambda: when
time.ticks_ms = lambda: 0
_mk = time.mktime
time.mktime = lambda t: int(_mk(tuple(t) + (0,) * (9 - len(t))))
time.ticks_diff = lambda a, b: a - b
class Done(Exception): pass
def stop(ms): raise Done
time.sleep_ms = stop

src = open(os.path.join(os.path.dirname(__file__), "..", "led_clock.py")).read()
for k, v in overrides.items():
    src = src.replace(f"\n{k} = ", f"\n{k} = {v}  # ", 1)
src = src.replace("theme = 0\n", f"theme = {theme}\n")
try:
    exec(compile(src, "led_clock.py", "exec"), {"__name__": "__main__"})
except Done:
    pass
out = sys.argv[1].replace(" ", "_").replace(":", "") + f"_t{theme}.png"
presto.FRAMES[-1].save(out)
print(out)
