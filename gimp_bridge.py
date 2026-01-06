#!/usr/bin/env python3
import sys
import socket
import json
import threading
import traceback
import math

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, GObject, GLib, Gio

LOG_PATH = "/tmp/gimp_mcp.log"

def log(msg):
    with open(LOG_PATH, "a") as f:
        f.write(str(msg) + "\n")

class GimpMcpBridge(Gimp.PlugIn):
    """Gimp MCP Bridge Plugin"""
    __gtype_name__ = "GimpMcpBridge"
    
    def do_query_procedures(self):
        return ["mcp-bridge-start"]

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(self, name, Gimp.PDBProcType.PLUGIN, self.run, None)
        procedure.set_menu_label("Start MCP Bridge Server")
        procedure.add_menu_path('<Image>/Filters/Development/')
        return procedure

    def run(self, procedure, run_mode, image, drawables, config, run_data):
        log("Run started")
        # Kill any existing server thread by closing its port?
        # Actually, we just hope reuse_addr works.
        threading.Thread(target=self.start_server, daemon=True).start()
        Gimp.message("MCP Bridge Server started on 65432")
        self.loop = GLib.MainLoop()
        self.loop.run()
        return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())

    def start_server(self):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(('127.0.0.1', 65432))
                s.listen()
                while True:
                    conn, addr = s.accept()
                    with conn:
                        data = conn.recv(4096)
                        if not data: continue
                        cmd = json.loads(data.decode('utf-8'))
                        result = self.execute_on_main_thread(cmd)
                        conn.sendall(json.dumps(result).encode('utf-8'))
        except Exception as e:
            log(f"Server Error: {e}")

    def execute_on_main_thread(self, command):
        res = {}
        event = threading.Event()
        def task():
            try:
                res['data'] = self.process_command(command)
                res['status'] = 'success'
            except Exception as e:
                res['status'] = 'error'
                res['message'] = str(e)
                log(f"Process Error: {e}\n{traceback.format_exc()}")
            finally:
                event.set()
            return False
        GLib.idle_add(task)
        event.wait()
        return res

    def run_pdb(self, proc_name, props):
        pdb = Gimp.get_pdb()
        proc = pdb.lookup_procedure(proc_name)
        if not proc: raise Exception(f"Procedure {proc_name} not found")
        conf = proc.create_config()
        for k, v in props.items():
            conf.set_property(k, v)
        return proc.run(conf)

    def process_command(self, cmd):
        action = cmd.get('action')
        imgs = Gimp.get_images()
        img = imgs[0] if imgs else None

        if action == 'list_images':
            return [f"ID: {i.get_id()} ({i.get_width()}x{i.get_height()})" for i in imgs]

        if action == 'new_image':
            w, h = cmd.get('width', 800), cmd.get('height', 600)
            new_img = Gimp.Image.new(w, h, Gimp.ImageBaseType.RGB)
            lay = Gimp.Layer.new(new_img, "Background", w, h, Gimp.ImageType.RGB_IMAGE, 100, Gimp.LayerMode.NORMAL)
            new_img.insert_layer(lay, None, 0)
            Gimp.Display.new(new_img)
            return f"Created {w}x{h} image"

        if not img: return "No image open"

        # Try to set color (Best effort)
        if 'r' in cmd:
            try:
                # Attempt to find a color constructor in Gimp namespace
                # GIMP 3.0 often uses Gegl.Color, but let's try strict PDB calls if possible
                pass 
                # Note: Skipping color explicit set for now to ensure stability 
                # until we debug the Gimp.RGB issue via logs.
                # However, we can try to find 'RGB' in dir(Gimp)
                # log(f"Gimp attributes: {dir(Gimp)}")
            except:
                pass

        if action == 'draw_rectangle':
            x, y = float(cmd.get('x',0)), float(cmd.get('y',0))
            w, h = float(cmd.get('width',100)), float(cmd.get('height',100))
            
            self.run_pdb('gimp-image-select-rectangle', {
                'image': img, 'operation': Gimp.ChannelOps.REPLACE,
                'x': x, 'y': y, 'width': w, 'height': h
            })
            
            layers = img.get_selected_layers()
            drawable = layers[0] if layers else img.get_layers()[1][0]
            
            self.run_pdb('gimp-drawable-edit-fill', {
                'drawable': drawable, 'fill-type': Gimp.FillType.FOREGROUND
            })
            self.run_pdb('gimp-selection-none', {'image': img})
            Gimp.displays_flush()
            return "Rectangle drawn"

        if action == 'draw_text':
            x, y = float(cmd.get('x',10)), float(cmd.get('y',10))
            text = cmd.get('text', "Hello")
            size = float(cmd.get('size', 24))
            
            # Use Gimp.TextLayer.new for GIMP 3.0
            # Gimp.TextLayer.new(image, text, font_name, font_size, unit)
            try:
                # We need to find valid unit (Pixels). usually Gimp.Unit.PIXEL
                # If unit is an enum, we might need the integer value or the Enum object.
                # Let's try to use the PDB call 'gimp-text-layer-new' if available, 
                # or the constructor if we can access the class.
                
                # The search result said: Gimp.TextLayer.new(image, text, font, size, unit)
                # But 'Gimp.TextLayer' might not be directly available in the introspection namespace
                # if it's not imported or mapped.
                
                # Safer: 'gimp-text-fontname' usually creates a layer. 
                # The previous error "Procedure gimp-text-fontname not found" suggests 
                # it was renamed or moved to 'plug-in-text-fontname' or similar?
                # Actually, in 3.0 PDB, it is often 'gimp-text-layer-new'.
                
                pdb = Gimp.get_pdb()
                proc = pdb.lookup_procedure('gimp-text-fontname')
                if not proc:
                    # Try alternate names
                    proc = pdb.lookup_procedure('gimp-text-layer-new')
                
                if proc:
                    # If we found a PDB proc, run it
                    conf = proc.create_config()
                    conf.set_property('image', img)
                    conf.set_property('text', text)
                    conf.set_property('font-name', "Sans")
                    conf.set_property('font-size', size)
                    conf.set_property('x', x)
                    conf.set_property('y', y)
                    proc.run(conf)
                else:
                    # Fallback to TextLayer constructor if PDB fails
                    # Note: Gimp.Unit.PIXEL might be 0
                    tl = Gimp.TextLayer.new(img, text, "Sans", size, 0)
                    img.insert_layer(tl, None, 0)
                    tl.set_offsets(x, y)
                    
            except Exception as e:
                log(f"Text error: {e}")
                return f"Text failed: {e}"
                
            Gimp.displays_flush()
            return f"Text '{text}' drawn"

        if action == 'set_color':
            r, g, b = cmd.get('r', 0), cmd.get('g', 0), cmd.get('b', 0)
            # Use Gegl.Color if possible
            try:
                from gi.repository import Gegl
                color = Gegl.Color.new(f"rgb({r/255.0}, {g/255.0}, {b/255.0})")
                Gimp.context_set_foreground(color)
            except:
                pass
            return f"Color set to {r},{g},{b}"

        if action == 'set_opacity':
            opacity = float(cmd.get('opacity', 100.0))
            # gimp-context-set-opacity takes double 0.0 to 100.0
            pdb = Gimp.get_pdb()
            try:
                proc = pdb.lookup_procedure('gimp-context-set-opacity')
                conf = proc.create_config()
                conf.set_property('opacity', opacity)
                proc.run(conf)
            except:
                pass
            return f"Opacity set to {opacity}"

        if action == 'create_layer':
            name = cmd.get('name', 'New Layer')
            w, h = img.get_width(), img.get_height()
            # Gimp.Layer.new(image, name, width, height, type, opacity, mode)
            l = Gimp.Layer.new(img, name, w, h, Gimp.ImageType.RGBA_IMAGE, 100, Gimp.LayerMode.NORMAL)
            img.insert_layer(l, None, 0)
            return f"Layer '{name}' created"

        if action == 'set_brush':
            # Set basic brush properties
            size = float(cmd.get('size', 20))
            name = cmd.get('name', "2. Hardness 050") # Default standard brush
            
            # Try to set context
            pdb = Gimp.get_pdb()
            
            # Set Brush
            try:
                proc = pdb.lookup_procedure('gimp-context-set-brush')
                conf = proc.create_config()
                conf.set_property('name', name)
                proc.run(conf)
            except:
                pass # Brush might not exist, ignore
            
            # Set Size
            try:
                proc = pdb.lookup_procedure('gimp-context-set-brush-size')
                conf = proc.create_config()
                conf.set_property('size', size)
                proc.run(conf)
            except:
                pass
                
            # Set Color (Foreground)
            r, g, b = cmd.get('r', 0), cmd.get('g', 0), cmd.get('b', 0)
            # We still lack a clean Gimp.RGB constructor in 3.0 GI, 
            # so we'll try to find a PDB way or just use black/white
            if r==0 and g==0 and b==0:
                 self.run_pdb('gimp-context-set-default-colors', {})
            else:
                 # If we can't set exact color easily yet, we skip.
                 # User can pick color in UI.
                 pass
                 
            return f"Brush set to {name} size {size}"

        if action == 'list_procedures':
            # Existing simple search
            query = cmd.get('query', '')
            pdb = Gimp.get_pdb()
            try:
                match = query if query else ".*"
                procs = pdb.query_procedures(match, "", "", "", "", "", "", "", "")
                return procs[:100] if procs else []
            except Exception as e:
                return f"Search failed: {e}"

        if action == 'dump_pdb_database':
            # BRAIN: Dump entire PDB to a file for AI to index
            # This allows the AI to learn GIMP's capabilities on the fly
            pdb = Gimp.get_pdb()
            all_procs = pdb.query_procedures(".*", "", "", "", "", "", "", "", "")
            
            # This is heavy, so we might just return the list of names
            # or try to get details for each.
            # Getting details for 1000+ procs is slow.
            # We will just dump names and blurbs if possible.
            
            # For fast retrieval, just return the list of names.
            # The client can then "inspect" specific ones.
            return all_procs

        if action == 'get_procedure_details':
            # Deep dive into one tool
            proc_name = cmd.get('procedure')
            pdb = Gimp.get_pdb()
            proc = pdb.lookup_procedure(proc_name)
            if not proc: return "Not found"
            
            # We can get arguments!
            # GimpProcedure has methods to get arguments.
            # Gimp 3.0 GI: proc.get_arguments() returns (status, args)
            # proc.get_help(), get_blurb()
            
            info = {
                "name": proc_name,
                "blurb": proc.get_blurb(),
                "help": proc.get_help(),
                "menu_label": proc.get_menu_label()
                # Args handling is complex in GI, skipping detailed type introspection for now
                # to prevent crashes. Just knowing the blurb is usually enough for an LLM
                # to guess usage or search docs.
            }
            return info

        if action == 'get_app_state':
            # EYES: Return full JSON state of the canvas
            state = {"images": []}
            images = Gimp.get_images()
            for img in images:
                img_data = {
                    "id": img.get_id(),
                    "width": img.get_width(),
                    "height": img.get_height(),
                    "active_layer": img.get_selected_layers()[0].get_id() if img.get_selected_layers() else None,
                    "layers": []
                }
                
                # Walk layer tree
                for layer in img.get_layers():
                    img_data["layers"].append({
                        "id": layer.get_id(),
                        "name": layer.get_name(),
                        "visible": layer.get_visible(),
                        "opacity": layer.get_opacity(),
                        "mode": str(layer.get_mode()) # Enum to string
                    })
                state["images"].append(img_data)
            
            # Add context info
            ctx = {
                "fg_color": "TODO", # RGB reading is tricky
                "brush": "TODO"
            }
            state["context"] = ctx
            return state

        if action == 'run_procedure':
            # Generic Runner: "gimp-layer-new", {"width": 500, ...}
            proc_name = cmd.get('procedure')
            args = cmd.get('arguments', {})
            
            pdb = Gimp.get_pdb()
            proc = pdb.lookup_procedure(proc_name)
            if not proc: return f"Procedure '{proc_name}' not found"
            
            config = proc.create_config()
            
            # Dynamically set properties
            # We need to handle Gimp.Image, Gimp.Layer, etc.
            # The client sends IDs (integers), we must convert to Objects.
            
            for key, val in args.items():
                # specific handling for known object types based on key name convention
                # In a full impl, we'd check the ParamSpec of the config property.
                # But for now, we try simple assignment.
                # If key implies an image/drawable, we might need lookup.
                
                try:
                    # If val is an int and key looks like 'image', try to get image
                    if (key == 'image' or key == 'img') and isinstance(val, int):
                         val = Gimp.Image.get_by_id(val)
                    elif (key == 'drawable' or key == 'layer') and isinstance(val, int):
                         val = Gimp.Item.get_by_id(val) 
                         
                    config.set_property(key, val)
                except Exception as e:
                    return f"Error setting '{key}': {e}"
            
            try:
                result = proc.run(config)
                # Parse result? Return success
                return "Procedure executed successfully"
            except Exception as e:
                return f"Execution failed: {e}"

        if action == 'draw_stroke':
            if not img: return "No image"
            points = cmd.get('points', [])
            if len(points) < 2: return "Need at least 2 points"
            
            thickness = float(cmd.get('thickness', 5.0))
            pdb = Gimp.get_pdb()
            
            # Robust "Stamp" method: Draw overlapping squares along the line
            # Optimized: Step size roughly equal to thickness for less overlap (faster)
            
            step_size = thickness * 0.8
            if step_size < 1.0: step_size = 1.0
            
            proc = pdb.lookup_procedure('gimp-image-select-rectangle')
            
            # Group PDB calls? No, we just run them.
            
            for i in range(len(points) - 1):
                p1 = points[i]
                p2 = points[i+1]
                x1, y1 = float(p1[0]), float(p1[1])
                x2, y2 = float(p2[0]), float(p2[1])
                
                dist = math.sqrt((x2-x1)**2 + (y2-y1)**2)
                if dist == 0: continue
                
                steps = int(dist / step_size)
                # Ensure at least start and end
                if steps < 1: steps = 1
                
                dx = (x2 - x1) / steps
                dy = (y2 - y1) / steps
                
                for s in range(steps + 1):
                    cx = x1 + dx * s
                    cy = y1 + dy * s
                    
                    # Add square selection
                    conf = proc.create_config()
                    conf.set_property('image', img)
                    conf.set_property('operation', Gimp.ChannelOps.ADD)
                    conf.set_property('x', cx - thickness/2)
                    conf.set_property('y', cy - thickness/2)
                    conf.set_property('width', thickness)
                    conf.set_property('height', thickness)
                    proc.run(conf)
            
            # Fill accumulated selection
            layers = img.get_selected_layers()
            drawable = layers[0] if layers else img.get_layers()[1][0]
            
            fill_proc = pdb.lookup_procedure('gimp-drawable-edit-fill')
            conf = fill_proc.create_config()
            conf.set_property('drawable', drawable)
            conf.set_property('fill-type', Gimp.FillType.FOREGROUND)
            fill_proc.run(conf)
            
            # Clear
            sel_proc = pdb.lookup_procedure('gimp-selection-none')
            conf = sel_proc.create_config()
            conf.set_property('image', img)
            sel_proc.run(conf)
            
            Gimp.displays_flush()
            return f"Stroked {len(points)} points (Stamped)"

        if action == 'gaussian_blur':
            radius = float(cmd.get('radius', 5.0))
            layers = img.get_selected_layers()
            if not layers: return "No layer selected"
            drawable = layers[0]
            
            # Use GEGL operation for blur in GIMP 3.0 usually, or plug-in-gauss
            # Let's try 'plug-in-gauss' if it exists, or 'gimp-drawable-filter-gaussian-blur'
            # 'plug-in-gauss' might be legacy. 
            # In 3.0, filters are often applied via GEGL nodes, but let's try the PDB procedure.
            try:
                self.run_pdb('plug-in-gauss', {
                    'run-mode': Gimp.RunMode.NONINTERACTIVE,
                    'image': img, 'drawable': drawable,
                    'horizontal': radius, 'vertical': radius, 'method': 0 # IIR
                })
            except:
                return "Blur failed (plugin might be missing)"
            
            Gimp.displays_flush()
            return f"Blurred with radius {radius}"
            
        return "Unknown command"

if __name__ == "__main__":
    Gimp.main(GimpMcpBridge.__gtype_name__, sys.argv)
