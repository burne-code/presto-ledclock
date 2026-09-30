# ICON schedule
# NAME LED Clock
# DESC Digital-analog wall clock with a seconds ring
#
# SPDX-License-Identifier: CC0-1.0

# A digital-analog LED wall clock for the Pimoroni Presto, styled after the
# Masterclock CLDNTD12: slanted 7-segment HH:MM digits with faint unlit
# segments, a ring of 60 LED dashes that fills up with the seconds, and
# always-on markers at every five-second position.
#
# Time comes from NTP; set WIFI_SSID, WIFI_PASSWORD, UTC_OFFSET and
# (optionally) DST_RULE in secrets.py. Tap the screen to change colours.

import asyncio
import machine
import math
import time

import network
import ntptime
from picovector import ANTIALIAS_X4, PicoVector, Polygon, Transform
from presto import Presto

# ---------------------------------------------------------------- settings

TWELVE_HOUR = False  # True: 1-12 with the leading zero blanked
BLINK_COLON = True  # colon on for the first half of every second
SHOW_SECONDS_DIGITS = False  # small SS readout under the main digits
SHOW_DATE = True  # YYYY-MM-DD (ISO 8601) under the time
DATE_COLOUR = (255, 20, 20)  # red, whatever the theme
SHOW_SENSORS = True  # Multi-Sensor Stick (BME280) readings above the time
SENSOR_SECONDS = 3  # each of temperature, humidity, pressure in turn
# The Presto warms the sensor. Calibrated 2026-09-30: stick 26.93 C against a
# reference 23.47 C. Humidity is corrected to match (see corrected_reading).
TEMP_OFFSET = -3.46
NTP_RESYNC_S = 3600  # how often to re-sync the RTC
RETRY_S = 60  # retry interval while Wi-Fi or NTP is failing

BRIGHTNESS = 1.0  # backlight, 0.0 - 1.0
NIGHT_BRIGHTNESS = 0.25  # used between NIGHT_START and NIGHT_END (local hours)
NIGHT_START = 23
NIGHT_END = 7

# (digits, seconds ring, 5-second markers) as RGB. Tap to cycle.
THEMES = [
    ((255, 200, 0), (0, 150, 255), (0, 220, 60)),  # amber / blue / green
    ((255, 255, 255), (255, 20, 40), (0, 120, 255)),  # white / red / blue
    ((255, 20, 20), (255, 20, 20), (255, 20, 20)),  # all red
    ((0, 230, 60), (0, 230, 60), (0, 230, 60)),  # all green
    ((0, 140, 255), (0, 140, 255), (0, 140, 255)),  # all blue
    ((255, 150, 0), (255, 150, 0), (255, 150, 0)),  # all amber
]
GHOST = 0.07  # brightness of unlit digit segments
TICK_OFF = 0.10  # brightness of seconds dashes not yet reached

try:
    from secrets import UTC_OFFSET
except ImportError:
    UTC_OFFSET = 0
try:
    from secrets import DST_RULE  # "EU", "US" or None
except ImportError:
    DST_RULE = None

# ---------------------------------------------------------------- display

presto = Presto(full_res=True)
display = presto.display
touch = presto.touch
WIDTH, HEIGHT = display.get_bounds()
CX, CY = WIDTH // 2, HEIGHT // 2
S = WIDTH / 480  # everything below is laid out for 480x480

vector = PicoVector(display)
vector.set_antialiasing(ANTIALIAS_X4)
# Keep a reference: PicoVector holds on to the transform, and a temporary
# one would be garbage-collected out from under it (freezes after seconds).
TRANSFORM = Transform()
vector.set_transform(TRANSFORM)

BLACK = display.create_pen(0, 0, 0)

bme = None
if SHOW_SENSORS:
    try:
        from breakout_bme280 import BreakoutBME280
        bme = BreakoutBME280(machine.I2C())
        bme.read()  # the first reading after power-up is garbage
    except Exception as e:  # noqa: BLE001 - no stick: just leave the row out
        print("No Multi-Sensor Stick:", e)
        bme = None


def scaled(rgb, f):
    return display.create_pen(int(rgb[0] * f), int(rgb[1] * f), int(rgb[2] * f))


def theme_pens(theme):
    digit, tick, mark = theme
    return {
        "digit": scaled(digit, 1),
        "ghost": scaled(digit, GHOST),
        "small_ghost": scaled(digit, GHOST / 2),  # small cells get busy otherwise
        "tick": scaled(tick, 1),
        "tick_off": scaled(tick, TICK_OFF),
        "tick_ghost": scaled(tick, GHOST),
        "mark": scaled(mark, 1),
    }


PENS = [theme_pens(t) for t in THEMES]
DATE_ON, DATE_OFF = scaled(DATE_COLOUR, 1), scaled(DATE_COLOUR, GHOST)

# ---------------------------------------------------------------- geometry

# Seconds ring: 60 short radial dashes just inside the edge of the screen.
R_OUT, R_IN, TICK_W = 230 * S, 212 * S, 6 * S


def radial_dash(i):
    a = math.radians(i * 6)
    dx, dy = math.sin(a), -math.cos(a)  # outward, 0 = 12 o'clock
    px, py = -dy * TICK_W / 2, dx * TICK_W / 2  # half-width across
    p = Polygon()
    p.path(
        (CX + dx * R_IN + px, CY + dy * R_IN + py),
        (CX + dx * R_OUT + px, CY + dy * R_OUT + py),
        (CX + dx * R_OUT - px, CY + dy * R_OUT - py),
        (CX + dx * R_IN - px, CY + dy * R_IN - py),
    )
    return p


DASHES = [radial_dash(i) for i in range(60)]

# 7-segment digits. Segments are hexagons along the digit's centre lines,
# then the whole digit is sheared to the right like the real LED modules.
#   a
#  f b
#   g
#  e c
#   d
DIGIT_SEGMENTS = {
    0: "abcdef", 1: "bc", 2: "abdeg", 3: "abcdg", 4: "bcfg",
    5: "acdfg", 6: "acdefg", 7: "abc", 8: "abcdefg", 9: "abcdfg",
    "-": "g", " ": "",
    # Just enough letters for the units: C, Pct, HPA.
    "C": "adef", "P": "abefg", "c": "deg", "t": "defg", "H": "bcefg", "A": "abcefg",
}
DIGIT_SEGMENTS.update({str(k): v for k, v in list(DIGIT_SEGMENTS.items()) if isinstance(k, int)})
SLANT = 0.09  # horizontal shear per unit of height


def seven_segment(x, y, w, h, t, dp=False):
    """Return {segment: Polygon} for a digit whose centre-line box is at x, y,
    plus a "dp" decimal point after it when dp is set."""
    ht, g = t / 2, max(1.0, t / 7)  # half thickness, gap between segments

    def shear(px, py):
        return (x + px + (h - py) * SLANT, y + py)

    def horiz(py):
        return (
            (g, py), (g + ht, py - ht), (w - g - ht, py - ht),
            (w - g, py), (w - g - ht, py + ht), (g + ht, py + ht),
        )

    def vert(px, y0, y1):
        return (
            (px, y0 + g), (px + ht, y0 + g + ht), (px + ht, y1 - g - ht),
            (px, y1 - g), (px - ht, y1 - g - ht), (px - ht, y0 + g + ht),
        )

    shapes = {
        "a": horiz(0), "g": horiz(h / 2), "d": horiz(h),
        "f": vert(0, 0, h / 2), "b": vert(w, 0, h / 2),
        "e": vert(0, h / 2, h), "c": vert(w, h / 2, h),
    }
    out = {}
    for name, pts in shapes.items():
        p = Polygon()
        p.path(*[shear(px, py) for px, py in pts])
        out[name] = p
    if dp:
        p = Polygon()
        p.circle(int(x + w + t * 1.4), int(y + h), int(t * 0.6))
        out["dp"] = p
    return out


def digit_row(count, w, h, t, gap, colon_w, top, dp=False):
    """Lay out `count` digits centred horizontally, with room for a colon
    in the middle when colon_w > 0. Returns (digits, colon_x)."""
    total = count * w + (count - 1) * gap + colon_w + t
    x = CX - total / 2 + t / 2 - h * SLANT / 2
    digits, colon_x = [], None
    for i in range(count):
        if colon_w and i == count // 2:
            colon_x = x - gap / 2 + colon_w / 2
            x += colon_w
        digits.append(seven_segment(x, top, w, h, t, dp))
        x += w + gap
    return digits, colon_x


DIG_W, DIG_H, DIG_T = 52 * S, 100 * S, 13 * S
DIG_GAP, COLON_W = 22 * S, 26 * S
ROW_GAP = 26 * S  # between the time and each small row under it
SEC_W, SEC_H, SEC_T = 20 * S, 38 * S, 6 * S
DATE_W, DATE_H, DATE_T = 18 * S, 30 * S, 5 * S
SENS_W, SENS_H, SENS_T, SENS_CELLS = 20 * S, 34 * S, 6 * S, 8

# Centre the whole stack: optional sensor row, the time, then optional
# seconds and date rows.
above = SENS_H + ROW_GAP if bme else 0
below = (ROW_GAP + SEC_H if SHOW_SECONDS_DIGITS else 0) + (ROW_GAP + DATE_H if SHOW_DATE else 0)
DIG_TOP = CY - (above + DIG_H + below) / 2 + above
SENSOR_CELLS, _ = digit_row(SENS_CELLS, SENS_W, SENS_H, SENS_T, 13 * S, 0,
                            DIG_TOP - above, dp=True) if bme else ([], None)
MAIN_DIGITS, COLON_X = digit_row(4, DIG_W, DIG_H, DIG_T, DIG_GAP, COLON_W, DIG_TOP)

COLON = []
for frac in (0.3, 0.7):
    cy = DIG_TOP + DIG_H * frac
    c = Polygon()
    c.circle(int(COLON_X + (DIG_H - DIG_H * frac) * SLANT), int(cy), int(DIG_T * 0.6))
    COLON.append(c)

row_top = DIG_TOP + DIG_H + ROW_GAP
SEC_DIGITS, _ = digit_row(2, SEC_W, SEC_H, SEC_T, 12 * S, 0, row_top)
if SHOW_SECONDS_DIGITS:
    row_top += SEC_H + ROW_GAP
# Ten cells for YYYY-MM-DD; the dashes are a lone middle segment, as on LED displays.
DATE_CELLS, _ = digit_row(10, DATE_W, DATE_H, DATE_T, 8 * S, 0, row_top) if SHOW_DATE else ([], None)

# ---------------------------------------------------------------- time


def utc_mktime(y, mo, d, h=0):
    # The Presto's RTC has no time zone: mktime/gmtime are plain UTC.
    return time.mktime((y, mo, d, h, 0, 0, 0, 0))


def sunday_on_or_before(y, mo, d):
    wday = time.gmtime(utc_mktime(y, mo, d))[6]  # Monday = 0
    return d - (wday + 1) % 7


def dst_active(utc):
    y = time.gmtime(utc)[0]
    if DST_RULE == "EU":  # last Sunday of March/October, 01:00 UTC
        start = utc_mktime(y, 3, sunday_on_or_before(y, 3, 31), 1)
        end = utc_mktime(y, 10, sunday_on_or_before(y, 10, 31), 1)
    elif DST_RULE == "US":  # 2nd Sunday of March to 1st Sunday of November, 02:00 local
        start = utc_mktime(y, 3, sunday_on_or_before(y, 3, 14), 2) - UTC_OFFSET * 3600
        end = utc_mktime(y, 11, sunday_on_or_before(y, 11, 7), 1) - UTC_OFFSET * 3600
    else:
        return False
    return start <= utc < end


def local_time():
    utc = time.time()
    offset = UTC_OFFSET + (1 if dst_active(utc) else 0)
    return time.gmtime(utc + int(offset * 3600))


# Shown under the clock while the time is unsynced. Deliberately not a log
# file: writing to flash while the display is running can hang the Presto.
status = ""


def log(*args):
    global status
    status = " ".join(str(a) for a in args)
    print(status)


def wlan_status():
    names = {v: k for k, v in network.__dict__.items() if k.startswith("STAT_")}
    s = network.WLAN(network.STA_IF).status()
    return names.get(s, s)


def connect_wifi():
    """First connection: bounded, instead of ezwifi's 10 x 60 s default."""
    try:
        ok = asyncio.get_event_loop().run_until_complete(
            presto.wifi.connect(timeout=20, retries=2))
    except Exception as e:  # noqa: BLE001 - e.g. no secrets: run from the RTC
        log("wifi error", repr(e))
        return False
    log("wifi", "connected" if ok else "failed", wlan_status())
    return bool(ok)


def retry_wifi():
    """Later attempts: kick off a non-blocking connect and check next time."""
    wlan = network.WLAN(network.STA_IF)
    if wlan.isconnected():
        return True
    try:
        from secrets import WIFI_PASSWORD, WIFI_SSID
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
    except Exception as e:  # noqa: BLE001
        log("wifi retry error", repr(e))
    return False


def sync_time():
    try:
        ntptime.settime()
    except Exception as e:  # noqa: BLE001 - keep ticking on the RTC
        log("ntp failed", repr(e))
        return False
    log("time synced")
    return True


# ---------------------------------------------------------------- sensors


def sensor_text(phase, reading):
    """Readout for the sensor row: value right-aligned in four cells, a blank,
    then the unit, so the units line up like on a panel meter."""
    temperature, pressure, humidity = reading
    if phase == 0:
        value, unit = "%.1f" % temperature, "C"
    elif phase == 1:
        value, unit = "%d" % round(humidity), "Pct"
    else:
        value, unit = "%d" % round(pressure / 100), "HPA"
    return value, unit


def to_cells(value, unit):
    """[(char, decimal_point)] for SENSOR_CELLS; a '.' lights the previous cell's dot."""
    cells = []
    for ch in value:
        if ch == "." and cells:
            cells[-1] = (cells[-1][0], True)
        else:
            cells.append((ch, False))
    cells = [(" ", False)] * (4 - len(cells)) + cells[-4:]
    cells += [(" ", False)] + [(ch, False) for ch in unit]
    return (cells + [(" ", False)] * SENS_CELLS)[:SENS_CELLS]


def saturation_pressure(temperature):
    # Magnus formula (hPa); only the ratio between two temperatures is used.
    return 6.112 * math.exp(17.62 * temperature / (243.12 + temperature))


def corrected_reading(reading):
    """Apply TEMP_OFFSET. The sensor measures relative humidity in air it has
    warmed itself, which holds more water, so it reads low: scale it by the
    ratio of saturation vapour pressures at the measured and true temperatures."""
    temperature, pressure, humidity = reading
    true_temperature = temperature + TEMP_OFFSET
    humidity *= saturation_pressure(temperature) / saturation_pressure(true_temperature)
    return true_temperature, pressure, min(humidity, 100.0)


def read_sensor():
    try:
        return corrected_reading(bme.read())
    except Exception as e:  # noqa: BLE001 - a glitch: keep the last reading
        print("BME280 read failed:", e)
        return None


# ---------------------------------------------------------------- drawing


def draw_digit(segments, value, on, off, dp=False):
    lit = DIGIT_SEGMENTS.get(value, "") if value is not None else ""
    for name, poly in segments.items():
        if name == "dp" and not dp:
            continue  # unlit decimal points just add noise
        display.set_pen(on if name == "dp" or name in lit else off)
        vector.draw(poly)


def draw(t, colon_on, pens, synced, sensor_cells):
    hour, minute, second = t[3], t[4], t[5]
    if TWELVE_HOUR:
        hour = hour % 12 or 12

    display.set_pen(BLACK)
    display.clear()

    for i, dash in enumerate(DASHES):
        if i % 5 == 0:
            display.set_pen(pens["mark"])
        elif i <= second:
            display.set_pen(pens["tick"])
        else:
            display.set_pen(pens["tick_off"])
        vector.draw(dash)

    on, off = pens["digit"], pens["ghost"]
    for cell, (ch, dp) in zip(SENSOR_CELLS, sensor_cells or ()):
        draw_digit(cell, ch, on, pens["small_ghost"], dp)

    draw_digit(MAIN_DIGITS[0], hour // 10 if hour >= 10 or not TWELVE_HOUR else None, on, off)
    draw_digit(MAIN_DIGITS[1], hour % 10, on, off)
    draw_digit(MAIN_DIGITS[2], minute // 10, on, off)
    draw_digit(MAIN_DIGITS[3], minute % 10, on, off)

    display.set_pen(pens["digit"] if colon_on else pens["ghost"])
    for dot in COLON:
        vector.draw(dot)

    if SHOW_SECONDS_DIGITS:
        # Like the real clock, the small seconds match the ring colour.
        draw_digit(SEC_DIGITS[0], second // 10, pens["tick"], pens["tick_ghost"])
        draw_digit(SEC_DIGITS[1], second % 10, pens["tick"], pens["tick_ghost"])

    if SHOW_DATE:
        year, month, day = t[0], t[1], t[2]
        chars = [year // 1000 % 10, year // 100 % 10, year // 10 % 10, year % 10, "-",
                 month // 10, month % 10, "-", day // 10, day % 10]
        for cell, value in zip(DATE_CELLS, chars):
            draw_digit(cell, value, DATE_ON, DATE_OFF)

    if not synced:
        # Not on the real clock: a dim status line while the time is unconfirmed.
        display.set_pen(pens["tick_off"])
        display.set_font("bitmap8")
        w = display.measure_text(status, 2)
        display.text(status, CX - w // 2, int(CY + 150 * S), WIDTH, 2)

    presto.update()


def message(text):
    display.set_pen(BLACK)
    display.clear()
    display.set_pen(PENS[0]["digit"])
    display.text(text, int(40 * S), CY - 10, WIDTH - int(80 * S), 3)
    presto.update()


# ---------------------------------------------------------------- main


def main():
    presto.set_backlight(BRIGHTNESS)
    message("Connecting...")
    synced = connect_wifi() and sync_time()
    last_attempt = time.time()

    theme = 0
    was_touched = False
    last_second = None
    second_start = time.ticks_ms()
    last_frame = None
    backlight = None
    reading = read_sensor() if bme else None
    phase = None
    sensor_cells = None

    while True:
        touch.poll()
        if touch.state and not was_touched:
            theme = (theme + 1) % len(THEMES)
        was_touched = touch.state

        now = time.time()
        if now != last_second:
            last_second = now
            second_start = time.ticks_ms()
        colon_on = not BLINK_COLON or time.ticks_diff(time.ticks_ms(), second_start) < 500

        if bme and now // SENSOR_SECONDS % 3 != phase:
            phase = now // SENSOR_SECONDS % 3
            reading = read_sensor() or reading
            sensor_cells = to_cells(*sensor_text(phase, reading)) if reading else None

        frame = (now, colon_on, theme)
        if frame != last_frame:
            last_frame = frame
            t = local_time()

            hour = t[3]
            night = (hour >= NIGHT_START or hour < NIGHT_END) if NIGHT_START > NIGHT_END \
                else NIGHT_START <= hour < NIGHT_END
            level = NIGHT_BRIGHTNESS if night else BRIGHTNESS
            if level != backlight:
                presto.set_backlight(level)
                backlight = level

            draw(t, colon_on, PENS[theme], synced, sensor_cells)

        if now - last_attempt >= (NTP_RESYNC_S if synced else RETRY_S):
            last_attempt = now
            if retry_wifi():
                ok = sync_time()
                synced = ok or synced  # an hourly miss keeps the good time
            else:
                log("wifi still down", wlan_status())

        time.sleep_ms(20)


main()
