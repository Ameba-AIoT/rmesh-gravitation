class Wall:
    def __init__(self, start_point, end_point):
        self.start_point = start_point
        self.end_point = end_point

    def get_length(self):
        return ((self.end_point[0] - self.start_point[0])**2 + (self.end_point[1] - self.start_point[1])**2)**0.5

    def check_intersection(self, loc1, loc2):
        x1, y1 = self.start_point
        x2, y2 = self.end_point
        x3, y3 = loc1
        x4, y4 = loc2

        def orientation(p, q, r):
            val = (q[1] - p[1]) * (r[0] - q[0]) - (q[0] - p[0]) * (r[1] - q[1])
            if val == 0:
                return 0
            return 1 if val > 0 else -1

        def on_segment(p, q, r):
            if (q[0] <= max(p[0], r[0]) and q[0] >= min(p[0], r[0]) and
                q[1] <= max(p[1], r[1]) and q[1] >= min(p[1], r[1])):
                return True
            return False

        # Adjust the coordinates to consider the width of the wall (15 units)
        x1 -= 7.5
        y1 -= 7.5
        x2 += 7.5
        y2 += 7.5

        o1 = orientation((x1, y1), (x2, y2), (x3, y3))
        o2 = orientation((x1, y1), (x2, y2), (x4, y4))
        o3 = orientation((x3, y3), (x4, y4), (x1, y1))
        o4 = orientation((x3, y3), (x4, y4), (x2, y2))

        if (o1 != o2 and o3 != o4):
            return True

        if (o1 == 0 and on_segment((x1, y1), (x3, y3), (x2, y2))):
            return True

        if (o2 == 0 and on_segment((x1, y1), (x4, y4), (x2, y2))):
            return True

        if (o3 == 0 and on_segment((x3, y3), (x1, y1), (x4, y4))):
            return True

        if (o4 == 0 and on_segment((x3, y3), (x2, y2), (x4, y4))):
            return True

        return False
