"""Desktop stand-in for the Presto display, drawn with Pillow."""
from PIL import Image, ImageDraw

SS = 4  # supersampling factor for anti-aliasing
FRAMES = []


class Display:
    def __init__(self, size):
        self.size = size
        self.img = Image.new("RGB", (size * SS, size * SS))
        self.draw = ImageDraw.Draw(self.img)
        self.pen = (0, 0, 0)

    def set_font(self, f):
        pass

    def measure_text(self, t, scale=1):
        return len(t) * 6 * scale

    def get_bounds(self):
        return self.size, self.size

    def create_pen(self, r, g, b):
        return (r, g, b)

    def set_pen(self, pen):
        self.pen = pen

    def clear(self):
        self.draw.rectangle((0, 0, self.img.width, self.img.height), fill=self.pen)

    def text(self, text, x, y, wrap=0, scale=1):
        self.draw.text((x * SS, y * SS), text, fill=self.pen)


class Touch:
    state = False

    def poll(self):
        pass


class Wifi:
    async def connect(self, timeout=60, retries=10):
        return False


class Presto:
    def __init__(self, full_res=False):
        self.display = Display(480 if full_res else 240)
        self.touch = Touch()
        self.wifi = Wifi()

    def set_backlight(self, v):
        pass

    def connect(self):
        pass

    def update(self):
        FRAMES.append(self.display.img.resize(
            (self.display.size, self.display.size), Image.LANCZOS))
