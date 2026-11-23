import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

INPUT_SVG = Path("profile-3d-contrib/profile-night-green.svg")
OUTPUT_SVG = Path("profile-3d-contrib/profile-night-pacman.svg")

# Cores usadas pelo profile-3d-contrib (tema night-green)
FLOOR_COLORS = {"#2d333b", "#161b22", "#ebedf0", "#22272e"}
ACTIVE_COLORS = {"#0e4429", "#006d32", "#26a641", "#39d353"}


def parse_points(points_str: str):
    nums = [float(v) for v in re.findall(r"[-+]?\d*\.?\d+", points_str)]
    return [(nums[i], nums[i + 1]) for i in range(0, len(nums) - 1, 2)]


def polygon_centroid(pts):
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


def extract_grid_cells(root):
    """
    Lê todos os losangos do piso no SVG do profile-3d-contrib e reconstrói
    a matriz (semana, dia) -> (cx, cy, tem_bloco, elemento_grupo).
    """
    candidates = []

    # Mapeia cada <polygon> ao seu <g> pai para poder animar o bloco inteiro depois
    parent_map = {child: parent for parent in root.iter() for child in parent}

    for poly in root.iter():
        if not poly.tag.endswith("polygon"):
            continue
        pts_attr = poly.attrib.get("points", "")
        pts = parse_points(pts_attr)
        if len(pts) != 4:
            continue

        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        w = max(xs) - min(xs)
        h = max(ys) - min(ys)

        # Losangos do tabuleiro isométrico têm proporção ~2:1 e largura ~12-18px
        if 8.0 <= w <= 26.0 and 4.0 <= h <= 14.0 and abs((w / h) - 2.0) < 0.35:
            cx, cy = polygon_centroid(pts)
            fill = (poly.attrib.get("fill") or "").lower()
            candidates.append((cx, cy, fill, parent_map.get(poly)))

    if not candidates:
        raise RuntimeError("Não foi possível localizar as células isométricas no SVG.")

    # Projeta no espaço da grade isométrica: u = cx/dx + cy/dy (semana), v = cy/dy - cx/dx (dia)
    # No profile-3d-contrib, dx ~= 8.66 e dy ~= 5.0 (razão sqrt(3):1 ou 2:1)
    dx, dy = 8.66025, 5.0
    projected = []
    for cx, cy, fill, grp in candidates:
        u = (cx / dx + cy / dy) / 2.0
        v = (cy / dy - cx / dx) / 2.0
        projected.append((u, v, cx, cy, fill, grp))

    u_min = min(p[0] for p in projected)
    v_min = min(p[1] for p in projected)

    # Agrupa pelo ponto mais baixo (piso) de cada coluna (semana, dia)
    grid = {}
    for u, v, cx, cy, fill, grp in projected:
        col = round(u - u_min)
        row = round(v - v_min)
        if not (0 <= col <= 53 and 0 <= row <= 6):
            continue

        is_active = fill in ACTIVE_COLORS
        # Mantém a coordenada base (maior cy = base do bloco no piso)
        if (col, row) not in grid:
            grid[(col, row)] = {
                "cx": cx,
                "cy": cy,
                "active": is_active,
                "group": grp,
            }
        else:
            if cy > grid[(col, row)]["cy"]:
                grid[(col, row)]["cx"] = cx
                grid[(col, row)]["cy"] = cy
            if is_active:
                grid[(col, row)]["active"] = True
                grid[(col, row)]["group"] = grp

    return grid


def build_serpentine_route(grid):
    """Gera o caminho percorrendo todas as colunas e linhas existentes no grid."""
    cols = sorted({c for c, _ in grid.keys()})
    route = []
    for idx, col in enumerate(cols):
        rows = sorted([r for c, r in grid.keys() if c == col], reverse=(idx % 2 == 1))
        for row in rows:
            route.append((col, row))
    return route


def main():
    if not INPUT_SVG.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {INPUT_SVG}")

    ET.register_namespace("", "http://www.w3.org/2000/svg")
    tree = ET.parse(INPUT_SVG)
    root = tree.getroot()

    grid = extract_grid_cells(root)
    route = build_serpentine_route(grid)
    total_steps = len(route)
    duration_sec = 36.0  # Duração total do loop em segundos

    # Constrói o path SVG para o <animateMotion> do Pac-Man e dos fantasmas
    path_coords = [f"{grid[cell]['cx']:.2f},{grid[cell]['cy'] - 2.0:.2f}" for cell in route]
    motion_path = "M " + " L ".join(path_coords)

    # Injeta CSS para fazer os blocos verdes "baixarem" quando o Pac-Man passa por cima
    style_el = ET.Element("style")
    css_rules = [
        """
        @keyframes chompTop {
          0%, 100% { transform: rotate(0deg); }
          50% { transform: rotate(-32deg); }
        }
        @keyframes chompBottom {
          0%, 100% { transform: rotate(0deg); }
          50% { transform: rotate(32deg); }
        }
        .pac-top { transform-origin: 0px 0px; animation: chompTop 0.28s infinite ease-in-out; }
        .pac-bot { transform-origin: 0px 0px; animation: chompBottom 0.28s infinite ease-in-out; }
        """
    ]

    for step_idx, cell in enumerate(route):
        info = grid[cell]
        if info["active"] and info["group"] is not None:
            cls_name = f"eat-block-{cell[0]}-{cell[1]}"
            existing_cls = info["group"].attrib.get("class", "")
            info["group"].attrib["class"] = f"{existing_cls} {cls_name}".strip()

            pct = (step_idx / total_steps) * 100.0
            pct_after = min(pct + 0.6, 99.5)
            css_rules.append(
                f"""
                @keyframes eat_{cell[0]}_{cell[1]} {{
                  0%, {pct:.2f}% {{ opacity: 1; transform: translateY(0px); }}
                  {pct_after:.2f}%, 96% {{ opacity: 0.15; transform: translateY(4px); }}
                  100% {{ opacity: 1; transform: translateY(0px); }}
                }}
                .{cls_name} {{ animation: eat_{cell[0]}_{cell[1]} {duration_sec}s linear infinite; }}
                """
            )

    style_el.text = "\n".join(css_rules)
    root.insert(0, style_el)

    # Cria a camada 3D do Pac-Man e dos 4 fantasmas
    ns = "http://www.w3.org/2000/svg"
    layer = ET.SubElement(root, f"{{{ns}}}g", {"id": "pacman-3d-overlay"})

    # Sombra isométrica + Pac-Man (duas metades articuladas)
    pac_group = ET.SubElement(layer, f"{{{ns}}}g", {"id": "pacman-actor"})
    ET.SubElement(
        pac_group,
        f"{{{ns}}}ellipse",
        {"cx": "0", "cy": "2.5", "rx": "5.5", "ry": "3.0", "fill": "rgba(0,0,0,0.45)"},
    )
    ET.SubElement(
        pac_group,
        f"{{{ns}}}path",
        {"d": "M -5.5,0 A 5.5,5.5 0 1,1 5.5,0 Z", "fill": "#FFD700", "class": "pac-top"},
    )
    ET.SubElement(
        pac_group,
        f"{{{ns}}}path",
        {"d": "M -5.5,0 A 5.5,5.5 0 1,0 5.5,0 Z", "fill": "#F5B800", "class": "pac-bot"},
    )
    ET.SubElement(
        pac_group,
        f"{{{ns}}}animateMotion",
        {
            "dur": f"{duration_sec}s",
            "repeatCount": "indefinite",
            "path": motion_path,
            "rotate": "auto",
        },
    )

    # Fantasmas perseguindo logo atrás do Pac-Man (atraso no begin)
    ghosts = [
        ("blinky", "#FF3B30", "-1.4s"),
        ("pinky", "#FF77A9", "-2.4s"),
        ("inky", "#00E5FF", "-3.4s"),
        ("clyde", "#FF9500", "-4.4s"),
    ]

    for name, color, delay in ghosts:
        g_actor = ET.SubElement(layer, f"{{{ns}}}g", {"id": f"ghost-{name}"})
        # Sombra
        ET.SubElement(
            g_actor,
            f"{{{ns}}}ellipse",
            {"cx": "0", "cy": "2.5", "rx": "4.8", "ry": "2.5", "fill": "rgba(0,0,0,0.4)"},
        )
        # Corpo do fantasma em perspectiva
        ET.SubElement(
            g_actor,
            f"{{{ns}}}path",
            {
                "d": "M -4.5,1 L -4.5,-3.5 A 4.5,4.5 0 0,1 4.5,-3.5 L 4.5,1 L 3,-0.5 L 1.5,1 L 0,-0.5 L -1.5,1 L -3,-0.5 Z",
                "fill": color,
            },
        )
        # Olhos
        ET.SubElement(g_actor, f"{{{ns}}}circle", {"cx": "-1.6", "cy": "-3.5", "r": "1.2", "fill": "#FFFFFF"})
        ET.SubElement(g_actor, f"{{{ns}}}circle", {"cx": "1.8", "cy": "-3.5", "r": "1.2", "fill": "#FFFFFF"})
        ET.SubElement(g_actor, f"{{{ns}}}circle", {"cx": "-1.2", "cy": "-3.5", "r": "0.6", "fill": "#0A192F"})
        ET.SubElement(g_actor, f"{{{ns}}}circle", {"cx": "2.2", "cy": "-3.5", "r": "0.6", "fill": "#0A192F"})

        ET.SubElement(
            g_actor,
            f"{{{ns}}}animateMotion",
            {
                "dur": f"{duration_sec}s",
                "begin": delay,
                "repeatCount": "indefinite",
                "path": motion_path,
            },
        )

    tree.write(OUTPUT_SVG, encoding="utf-8", xml_declaration=True)
    print(f"SVG 3D + Pac-Man gerado com sucesso em: {OUTPUT_SVG} ({total_steps} células mapeadas)")


if __name__ == "__main__":
    main()
