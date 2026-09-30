ANTIALIAS_X4 = ANTIALIAS_X16 = 0


class Polygon:
    def __init__(self):
        self.shapes = []

    def path(self, *pts):
        self.shapes.append(("path", pts))

    def circle(self, x, y, r):
        self.shapes.append(("circle", (x, y, r)))


class Transform:
    pass


class PicoVector:
    def __init__(self, display):
        self.d = display

    def set_antialiasing(self, a):
        pass

    def set_transform(self, t):
        pass

    def draw(self, poly):
        from presto import SS
        for kind, data in poly.shapes:
            if kind == "path":
                self.d.draw.polygon([(x * SS, y * SS) for x, y in data], fill=self.d.pen)
            else:
                x, y, r = data
                self.d.draw.ellipse(((x - r) * SS, (y - r) * SS, (x + r) * SS, (y + r) * SS), fill=self.d.pen)
