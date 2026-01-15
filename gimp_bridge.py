#!/usr/bin/env python3
import sys
import socket
import json
import threading
import traceback
import math
import os
import tempfile

import gi
gi.require_version('Gimp', '3.0')
gi.require_version('GimpUi', '3.0')
gi.require_version('Gegl', '0.4')
from gi.repository import Gimp, GObject, GLib, Gio, Gegl

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
        log("Run started v6 (Fixed Indentation)")
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
                        # Read potentially large data (pixel buffers)
                        data = b""
                        while True:
                            chunk = conn.recv(1048576) # 1MB chunks
                            if not chunk: break
                            data += chunk
                            # Simple heuristic: valid JSON ends with '}'
                            # A real protocol would use headers, but this works for our single-request usage
                            if data.strip().endswith(b'}'):
                                try:
                                    json.loads(data)
                                    break
                                except:
                                    pass # Keep reading if not valid yet
                        
                        if not data: continue
                        
                        try:
                            cmd = json.loads(data.decode('utf-8'))
                            result = self.execute_on_main_thread(cmd)
                            conn.sendall(json.dumps(result).encode('utf-8'))
                        except Exception as e:
                            log(f"JSON Error: {e}")
                            conn.sendall(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
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

    def process_command(self, cmd):
        action = cmd.get('action')
        imgs = Gimp.get_images()
        img = imgs[0] if imgs else None
        pdb = Gimp.get_pdb()

        if action == 'introspection':
            # GROUND TRUTH: Dump the API surface to a file
            dump_path = "/tmp/gimp_introspection.txt"
            with open(dump_path, "w") as f:
                f.write("=== Gimp Module Attributes ===\n")
                f.write(str(dir(Gimp)) + "\n\n")

                f.write("=== Gimp.paintbrush Docstring ===\n")
                if hasattr(Gimp, 'paintbrush'):
                    f.write(str(Gimp.paintbrush.__doc__) + "\n")
                else:
                    f.write("NOT FOUND\n")

                f.write("\n=== PDB: file-png-save ===\n")
                try:
                    # Robust search
                    proc_name = "file-png-save"
                    proc = pdb.lookup_procedure(proc_name)
                    if not proc:
                        # Try regex search with robust args
                        matches = pdb.query_procedures(".*file-png-save", "", "", "", "", "", "", "")
                        if matches:
                             # Check if string or object
                             if isinstance(matches[0], str):
                                 proc_name = matches[0]
                                 proc = pdb.lookup_procedure(proc_name)
                             else:
                                 proc = matches[0]
                    
                    if proc:
                        f.write(f"Name: {proc.get_name()}\n")
                        f.write("Arguments:\n")
                        for arg in proc.get_arguments():
                            f.write(f"  - {arg.name} ({arg.value_type.name})\n")
                    else:
                        f.write("Procedure not found.\n")
                except Exception as e:
                    f.write(f"Error inspecting PNG: {e}\n")

            return dump_path

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

        if action == 'snapshot':
             # Save current view to temp file
             dup = img.duplicate()
             try:
                 merged = dup.merge_visible_layers(Gimp.MergeType.CLIP_TO_IMAGE)
                 fd, path = tempfile.mkstemp(suffix=".png")
                 os.close(fd)
                 gfile = Gio.File.new_for_path(path)
                 
                 # GIMP 3.0 file_save: (run_mode, image, file, options)
                 try:
                     Gimp.file_save(run_mode=Gimp.RunMode.NONINTERACTIVE, 
                                    image=dup, 
                                    file=gfile,
                                    options=None)
                 except Exception as e:
                     log(f"Gimp.file_save kwarg failed: {e}")
                     # Fallback to PDB if GI call fails
                 
                 return path
             except Exception as e:
                 log(f"Snapshot failed: {e}\n{traceback.format_exc()}")
                 return f"Error: {e}"
             finally:
                 dup.delete()

        if action == 'set_color':
            r, g, b = cmd.get('r', 0), cmd.get('g', 0), cmd.get('b', 0)
            try:
                c = Gegl.Color.new(f"rgb({r/255.0}, {g/255.0}, {b/255.0})")
                Gimp.context_set_foreground(c)
                return f"Color set to {r},{g},{b}"
            except Exception as e:
                return f"Color set failed: {e}"

        if action == 'draw_stroke':
            points = cmd.get('points', [])
            if not points or len(points) < 2: return "Need at least 2 points"
            thickness = float(cmd.get('thickness', 5.0))
            
            try:
                proc = pdb.lookup_procedure('gimp-context-set-brush-size')
                conf = proc.create_config()
                conf.set_property('size', thickness)
                proc.run(conf)
            except: pass
            
            flat_points = [float(c) for p in points for c in p]
            num_pairs = len(flat_points) // 2
            
            layers = img.get_selected_layers()
            if not layers: return "No layer selected"
            drawable = layers[0]
            
            try:
                # GIMP 3.0 Signature confirmed: (drawable, fade_out, strokes, method, gradient_length)
                Gimp.paintbrush(drawable, 0.0, flat_points, Gimp.PaintApplicationMode.CONSTANT, 0.0)
                Gimp.displays_flush()
                return f"Stroked {num_pairs} points"
            except Exception as e:
                log(f"Paintbrush error: {e}")
                return f"Paintbrush error: {e}"

        if action == 'get_app_state':
             state = {"images": []}
             for i in imgs:
                 state["images"].append({
                     "id": i.get_id(),
                     "width": i.get_width(),
                     "height": i.get_height(),
                     "layers": [{"name": l.get_name(), "id": l.get_id(), "visible": l.get_visible()} for l in i.get_layers()]
                 })
             return state

        if action == 'debug_pdb':
            query = cmd.get('query', '.*')
            results = []
            # 3.0 PDB query_procedures takes exactly 8 strings + self
            procs = pdb.query_procedures(query, "", "", "", "", "", "", "")
            for p in procs:
                if isinstance(p, str):
                    p_obj = pdb.lookup_procedure(p)
                else:
                    p_obj = p
                
                if not p_obj: continue
                    
                args = []
                for pspec in p_obj.get_arguments():
                    args.append({"name": pspec.name, "type": pspec.value_type.name})
                results.append({"name": p_obj.get_name(), "args": args})
            return results

        if action == 'dump_pdb_database':
             try:
                 return [p.get_name() for p in pdb.query_procedures(".*", "", "", "", "", "", "", "")]
             except:
                 return "Failed to dump"

        if action == 'get_pixels':
            x, y, w, h = int(cmd.get('x', 0)), int(cmd.get('y', 0)), int(cmd.get('width', 100)), int(cmd.get('height', 100))
            layers = img.get_selected_layers()
            if not layers: return "No layer selected"
            drawable = layers[0]
            try:
                buffer = drawable.get_buffer()
                rect = Gegl.Rectangle.new(x, y, w, h)
                format_str = "R'G'B'A u8"
                # GI requires the format string, not the object
                pixel_data = buffer.get(rect, 1.0, format_str, Gegl.AbyssPolicy.NONE)
                import base64
                return {"width": w, "height": h, "format": format_str, "data": base64.b64encode(pixel_data).decode('utf-8')}
            except Exception as e:
                log(f"Get pixels failed: {e}\n{traceback.format_exc()}")
                return f"Error: {e}"

        if action == 'set_pixels':
            x, y, w, h = int(cmd.get('x', 0)), int(cmd.get('y', 0)), int(cmd.get('width', 100)), int(cmd.get('height', 100))
            b64_data = cmd.get('data')
            layers = img.get_selected_layers()
            if not layers: return "No layer selected"
            drawable = layers[0]
            try:
                import base64
                pixel_data = base64.b64decode(b64_data)
                buffer = drawable.get_buffer()
                rect = Gegl.Rectangle.new(x, y, w, h)
                format_str = "R'G'B'A u8"
                log(f"SetPixels: Drawable={drawable.get_name()}, Bytes={len(pixel_data)}")
                buffer.set(rect, format_str, pixel_data)
                drawable.update(x, y, w, h)
                Gimp.displays_flush()
                return f"Wrote {len(pixel_data)} bytes"
            except Exception as e:
                log(f"Set pixels failed: {e}\n{traceback.format_exc()}")
                return f"Error: {e}"

        if action == 'set_brush':
            name = cmd.get('name', '2. Hardness 050')
            size = float(cmd.get('size', 20.0))
            try:
                # Set Brush
                proc = pdb.lookup_procedure('gimp-context-set-brush')
                conf = proc.create_config()
                conf.set_property('name', name)
                proc.run(conf)
                
                # Set Size
                proc = pdb.lookup_procedure('gimp-context-set-brush-size')
                conf = proc.create_config()
                conf.set_property('size', size)
                proc.run(conf)
                
                return f"Brush set to {name} (Size: {size})"
            except Exception as e:
                return f"Set brush failed: {e}"

        if action == 'run_procedure':
            proc_name = cmd.get('procedure')
            args = cmd.get('arguments', {})
            proc = pdb.lookup_procedure(proc_name)
            if not proc: return f"Procedure '{proc_name}' not found"
            
            config = proc.create_config()
            for key, val in args.items():
                try:
                    # Conversion for GI mapping
                    if (key == 'image' or key == 'img') and isinstance(val, int):
                         val = Gimp.Image.get_by_id(val)
                    elif (key == 'drawable' or key == 'layer' or key == 'item') and isinstance(val, int):
                         val = Gimp.Item.get_by_id(val)
                    config.set_property(key, val)
                except: pass
            proc.run(config)
            return "Executed"

        if action == 'create_layer':
            name = cmd.get('name', 'New Layer')
            w, h = img.get_width(), img.get_height()
            l = Gimp.Layer.new(img, name, w, h, Gimp.ImageType.RGBA_IMAGE, 100, Gimp.LayerMode.NORMAL)
            img.insert_layer(l, None, 0)
            return f"Layer '{name}' created"

        return "Unknown command"

if __name__ == "__main__":
    Gimp.main(GimpMcpBridge.__gtype_name__, sys.argv)
