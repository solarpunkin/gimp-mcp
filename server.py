from fastmcp import FastMCP
import socket
import json
from typing import List, Dict, Any

HOST = '127.0.0.1'
PORT = 65432

def send_cmd(cmd):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(15)
            s.connect((HOST, PORT))
            # Large buffer for full state dumps
            s.sendall(json.dumps(cmd).encode('utf-8'))
            
            # Helper to read all data
            fragments = []
            while True:
                chunk = s.recv(16384)
                if not chunk: break
                fragments.append(chunk)
                if len(chunk) < 16384: break # Simple EOF check for short messages
                
            data = b''.join(fragments)
            if not data: return {}
            return json.loads(data.decode('utf-8'))
    except Exception as e:
        return {"status": "error", "message": str(e)}

mcp = FastMCP("Gimp Tools")

# --- Observability (The Eyes) ---

@mcp.tool()
def get_gimp_state() -> str:
    """
    Get the full structure of the GIMP session.
    Returns Open Images, their dimensions, and Layer Trees (names, IDs, visibility).
    Use this to 'see' what is on the canvas before acting.
    """
    return str(send_cmd({"action": "get_app_state"}))

# --- Knowledge (The Brain) ---

@mcp.tool()
def get_all_procedure_names() -> str:
    """
    Returns a list of ALL available GIMP PDB procedures.
    Use this to 'learn' what tools are available (e.g., finding filters).
    WARNING: Returns a huge list.
    """
    return str(send_cmd({"action": "dump_pdb_database"}))

@mcp.tool()
def inspect_tool(procedure_name: str) -> str:
    """
    Get detailed help/usage for a specific GIMP procedure.
    Use this after finding a tool name to learn how to use it.
    """
    return str(send_cmd({"action": "get_procedure_details", "procedure": procedure_name}))

# --- Action (The Hands) ---

@mcp.tool()
def run_gimp_command(procedure: str, arguments: Dict[str, Any]) -> str:
    """Run ANY GIMP PDB procedure."""
    return str(send_cmd({"action": "run_procedure", "procedure": procedure, "arguments": arguments}))

# --- Helpers ---

@mcp.tool()
def create_new_image(width: int = 800, height: int = 600) -> str:
    return str(send_cmd({"action": "new_image", "width": width, "height": height}))

@mcp.tool()
def set_color(r: int, g: int, b: int) -> str:
    return str(send_cmd({"action": "set_color", "r": r, "g": g, "b": b}))

@mcp.tool()
def set_opacity(opacity: float) -> str:
    return str(send_cmd({"action": "set_opacity", "opacity": opacity}))

@mcp.tool()
def draw_stroke(points: List[List[float]], thickness: float = 5.0) -> str:
    return str(send_cmd({"action": "draw_stroke", "points": points, "thickness": thickness}))

@mcp.tool()
def draw_text(text: str, x: int, y: int, size: int = 24) -> str:
    return str(send_cmd({"action": "draw_text", "text": text, "x": x, "y": y, "size": size}))

if __name__ == "__main__":
    mcp.run()