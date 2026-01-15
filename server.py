from fastmcp import FastMCP
import socket
import json
from typing import List, Dict, Any

HOST = '127.0.0.1'
PORT = 65432

def send_cmd(cmd):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(30) # Increased timeout for snapshots
            s.connect((HOST, PORT))
            s.sendall(json.dumps(cmd).encode('utf-8'))
            
            fragments = []
            while True:
                chunk = s.recv(65536)
                if not chunk: break
                fragments.append(chunk)
                if len(chunk) < 65536: break 
            
            data = b''.join(fragments)
            if not data: return {}
            return json.loads(data.decode('utf-8'))
    except Exception as e:
        return {"status": "error", "message": str(e)}

mcp = FastMCP("Gimp Tools")

@mcp.tool()
def get_gimp_state() -> str:
    """
    Get the semantic structure of the GIMP session.
    Returns Open Images, IDs, and Layer trees.
    """
    return str(send_cmd({"action": "get_app_state"}))

@mcp.tool()
def snapshot_canvas() -> str:
    """
    Take a visual snapshot of the current canvas.
    Returns the file path to a temporary PNG file.
    Use this to SEE what you have drawn and correct mistakes.
    """
    result = send_cmd({"action": "snapshot"})
    if isinstance(result, dict) and result.get('status') == 'success':
        return result.get('data')
    return str(result)

@mcp.tool()
def get_all_procedure_names() -> str:
    """Returns a list of ALL available GIMP PDB procedures."""
    return str(send_cmd({"action": "dump_pdb_database"}))

@mcp.tool()
def run_gimp_command(procedure: str, arguments: Dict[str, Any]) -> str:
    """Run ANY GIMP PDB procedure."""
    return str(send_cmd({"action": "run_procedure", "procedure": procedure, "arguments": arguments}))

@mcp.tool()
def create_new_image(width: int = 800, height: int = 600) -> str:
    return str(send_cmd({"action": "new_image", "width": width, "height": height}))

@mcp.tool()
def set_color(r: int, g: int, b: int) -> str:
    return str(send_cmd({"action": "set_color", "r": r, "g": g, "b": b}))

@mcp.tool()
def draw_stroke(points: List[List[float]], thickness: float = 5.0) -> str:
    """
    Draw a stroke using the current brush and color.
    points: List of [x, y] coordinates.
    thickness: Brush size.
    """
    return str(send_cmd({"action": "draw_stroke", "points": points, "thickness": thickness}))

@mcp.tool()
def draw_text(text: str, x: int, y: int, size: int = 24) -> str:
    return str(send_cmd({"action": "draw_text", "text": text, "x": x, "y": y, "size": size}))

if __name__ == "__main__":
    mcp.run()
