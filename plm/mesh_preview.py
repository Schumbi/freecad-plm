import math
import struct
import zlib
from pathlib import Path


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def normalize(vector):
    length = math.sqrt(dot(vector, vector))
    if length == 0:
        return (0.0, 0.0, 0.0)
    return (vector[0] / length, vector[1] / length, vector[2] / length)


VIEW_DIRECTIONS = {
    "front": ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, -1.0, 0.0)),
    "back": ((-1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, 1.0, 0.0)),
    "left": ((0.0, -1.0, 0.0), (0.0, 0.0, 1.0), (-1.0, 0.0, 0.0)),
    "right": ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0)),
    "top": ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
    "bottom": ((1.0, 0.0, 0.0), (0.0, -1.0, 0.0), (0.0, 0.0, -1.0)),
    "isometric": (
        normalize((1.0, -1.0, 0.0)),
        normalize((1.0, 1.0, 2.0)),
        normalize((1.0, 1.0, -1.0)),
    ),
}


def read_stl(path):
    data = Path(path).read_bytes()
    if len(data) >= 84:
        triangle_count = struct.unpack_from("<I", data, 80)[0]
        expected_size = 84 + triangle_count * 50
        if expected_size == len(data):
            return read_binary_stl(data, triangle_count)
    return read_ascii_stl(data.decode("utf-8", errors="ignore"))


def read_binary_stl(data, triangle_count):
    triangles = []
    offset = 84
    for _ in range(triangle_count):
        offset += 12
        vertices = []
        for _ in range(3):
            vertices.append(struct.unpack_from("<fff", data, offset))
            offset += 12
        offset += 2
        triangles.append(tuple(vertices))
    return triangles


def read_ascii_stl(text):
    vertices = []
    triangles = []
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) == 4 and parts[0] == "vertex":
            vertices.append((float(parts[1]), float(parts[2]), float(parts[3])))
            if len(vertices) == 3:
                triangles.append(tuple(vertices))
                vertices = []
    return triangles


def render_stl_views(stl_path, output_dir, revision_code, width=400, height=300):
    triangles = read_stl(stl_path)
    if not triangles:
        raise RuntimeError("Das Vorschau-Mesh enthaelt keine Dreiecke.")

    output_dir = Path(output_dir)
    artifacts = []
    for view_name in ("front", "back", "left", "right", "top", "bottom", "isometric"):
        path = output_dir / f"{revision_code}-{view_name}.png"
        render_view(triangles, view_name, path, width=width, height=height)
        artifacts.append({"path": str(path), "artifact_type": "png", "view_name": view_name})
    return artifacts


def render_view(triangles, view_name, output_path, width=400, height=300):
    right, up, forward = VIEW_DIRECTIONS[view_name]
    projected_triangles = []
    xs = []
    ys = []
    for triangle in triangles:
        projected = []
        for vertex in triangle:
            x = dot(vertex, right)
            y = dot(vertex, up)
            z = dot(vertex, forward)
            projected.append((x, y, z))
            xs.append(x)
            ys.append(y)
        projected_triangles.append((triangle, projected))

    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x = max(max_x - min_x, 1e-9)
    span_y = max(max_y - min_y, 1e-9)
    margin = 0.08
    scale = min(width * (1.0 - margin * 2.0) / span_x, height * (1.0 - margin * 2.0) / span_y)
    center_x = (min_x + max_x) / 2.0
    center_y = (min_y + max_y) / 2.0

    color = bytearray([255, 255, 255] * width * height)

    for original, projected in projected_triangles:
        screen = []
        for x, y, z in projected:
            sx = (x - center_x) * scale + width / 2.0
            sy = height / 2.0 - (y - center_y) * scale
            screen.append((sx, sy, z))

        draw_edge(screen[0], screen[1], color, width, height)
        draw_edge(screen[1], screen[2], color, width, height)
        draw_edge(screen[2], screen[0], color, width, height)

    write_png(output_path, width, height, bytes(color))


def draw_edge(a, b, color, width, height):
    x1, y1, _ = a
    x2, y2, _ = b
    steps = max(abs(x2 - x1), abs(y2 - y1), 1)
    for step in range(int(steps) + 1):
        t = step / steps
        x = int(round(x1 + (x2 - x1) * t))
        y = int(round(y1 + (y2 - y1) * t))
        if 0 <= x < width and 0 <= y < height:
            offset = (y * width + x) * 3
            color[offset : offset + 3] = b"\x2b\x35\x3c"


def write_png(path, width, height, rgb):
    rows = []
    stride = width * 3
    for y in range(height):
        rows.append(b"\x00" + rgb[y * stride : (y + 1) * stride])
    compressed = zlib.compress(b"".join(rows), level=1)
    Path(path).write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + png_chunk(b"IDAT", compressed)
        + png_chunk(b"IEND", b"")
    )


def png_chunk(kind, data):
    checksum = zlib.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)
