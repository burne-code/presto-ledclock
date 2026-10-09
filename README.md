# Presto LED Clock

A digital-analog LED wall clock for the [Pimoroni Presto](https://shop.pimoroni.com/products/presto),
styled after the [Masterclock CLDNTD12](https://www.masterclock.com/digital-analog-clock-cldntd12.html): slanted 7-segment `HH:MM` with faint unlit
segments, a ring of 60 LED dashes that fills clockwise with the seconds, and
always-lit markers at every five-second position. Time is synced over NTP.

## Install

1. Copy `secrets.example.py` to `secrets.py` and fill it in (Wi-Fi, `UTC_OFFSET`, `DST_RULE`,
   and optionally `NTP_SERVER`, e.g. a local time server; `pool.ntp.org` is the fallback).
2. Copy both files to the Presto, e.g. with [mpremote](https://docs.micropython.org/en/latest/reference/mpremote.html):

   ```bash
   mpremote connect id:143f3655d50632fe cp led_clock.py secrets.py :
   ```

   Name the Presto explicitly: plain `mpremote` connects to the first USB serial
   device it finds, which may be something else (a monitor, another board).
   `mpremote connect list` shows the Presto's serial number. Close Thonny first:
   only one program can hold the port, and connecting stops whatever is running.

3. Pick **LED Clock** from the Presto launcher. To start it at boot instead,
   copy it as `main.py` instead.

If your Presto already has a `secrets.py` from the Pimoroni examples, just add the
`UTC_OFFSET` and `DST_RULE` lines to it.

## Use

With a [Multi-Sensor Stick](https://shop.pimoroni.com/products/multi-sensor-stick)
on the Qw/ST port, the row above the time cycles through temperature (`C`),
humidity (`Pct`) and air pressure (`HPA`), 3 seconds each. Without it, the row is
left out. The date (ISO 8601, red) sits under the time.

Tap the screen to cycle colour schemes. Options live at the top of `led_clock.py`:
12/24-hour mode, blinking colon, small seconds digits, night-time dimming, colours.

Until the time has synced over NTP, a dim status line under the digits says why
(e.g. `wifi failed NO_AP_FOUND` or `ntp failed ...`); it retries every minute.

Presto LED Clock uses a configureable NTP server in secrets.py. Setting NTP_SERVER=none will make
it use pool.ntp.org. 

## Presto gotchas found along the way

- Keep a reference to the `Transform` passed to `vector.set_transform()`; a
  temporary one gets garbage-collected and the Presto freezes seconds later.
- Don't write files while the display is running: it can hard-lock the Presto.

## Preview on a desktop

`preview/` fakes the Presto graphics API with Pillow and renders one frame:

```bash
python3 preview/render.py "2026-09-29 07:45:47" 1 SHOW_SECONDS_DIGITS=True
```

## Credits

Idea, design and hardware testing by Ruben van der Leij; code written and
debugged with Claude (Anthropic).

Styled after the Masterclock CLDNTD12 digital-analog clock. Not affiliated with
or endorsed by Masterclock, Inc.

## License

[CC0 1.0 Universal](LICENSE): dedicated to the public domain. Use it for
anything, no attribution required.
