import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

INPUT_SVG = Path("profile-3d-contrib/profile-night-green.svg")
OUTPUT_SVG = Path("profile-3d-contrib/profile-night-pacman.svg")


SVG_NS = "http://www.w3.org/2000/svg"
TRANSLATE_RE = re.compile(r"translate\(\s*([-\d.]+)[ ,]+([-\d.]+)\s*\)")
TOP_CLASS_RE = re.compile(r"cont-top-(\d+)")

# Geometria isométrica do profile-3d-contrib: cada célula vale 20px em x
# e 11,547px (20 * tan 30°) em y por passo de coluna/linha.
STEP_X = 20.0
STEP_Y = 11.547
CELL_CENTER_DX = 18.0  # centro do losango em relação ao translate do grupo


def extract_grid_cells(root):
    """
    Lê as células do SVG do profile-3d-contrib. Cada célula é um <g
    transform="translate(x y)"> com 3 <rect> (topo, lado esquerdo, lado
    direito); a classe "cont-top-N" do topo traz o nível de contribuição (N>0
    = dia com contribuições). A ordem no documento é semana a semana (7 dias).

    Retorna {(semana, dia): {cx, cy, active, group, parent}} onde (cx, cy) é
    o centro do losango no piso (sem a altura do bloco).
    """
    parent_map = {child: parent for parent in root.iter() for child in parent}

    cells = []
    for g in root.iter(f"{{{SVG_NS}}}g"):
        m = TRANSLATE_RE.fullmatch(g.attrib.get("transform", "").strip())
        if not m:
            continue
        rects = [c for c in g if c.tag == f"{{{SVG_NS}}}rect"]
        if len(rects) != 3:
            continue
        top = TOP_CLASS_RE.fullmatch(rects[0].attrib.get("class", ""))
        if not top:
            continue
        cells.append((float(m.group(1)), float(m.group(2)), int(top.group(1)), g))

    if not cells:
        raise RuntimeError("Não foi possível localizar as células isométricas no SVG.")

    # x não depende da altura do bloco; y só é confiável nas células sem
    # contribuição (altura mínima), então ancoramos o piso nelas.
    x0 = cells[0][0]
    y0 = None
    for i, (_, y, level, _g) in enumerate(cells):
        if level == 0:
            col, row = divmod(i, 7)
            y0 = y - STEP_Y * (col + row)
            break
    if y0 is None:
        raise RuntimeError("Nenhuma célula sem contribuição para calibrar o piso do SVG.")

    grid = {}
    for i, (_, _, level, g) in enumerate(cells):
        col, row = divmod(i, 7)
        grid[(col, row)] = {
            "cx": x0 + STEP_X * (col - row) + CELL_CENTER_DX,
            "cy": y0 + STEP_Y * (col + row),
            "active": level > 0,
            "group": g,
            "parent": parent_map.get(g),
        }
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
            # O CSS "transform" sobrescreve o atributo transform="translate(...)"
            # do grupo; por isso a animação vai num <g> envoltório.
            group, parent = info["group"], info["parent"]
            wrapper = ET.Element(f"{{{SVG_NS}}}g", {"class": cls_name})
            parent.insert(list(parent).index(group), wrapper)
            parent.remove(group)
            wrapper.append(group)

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
