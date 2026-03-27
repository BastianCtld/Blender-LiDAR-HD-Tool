import numpy as np
import bpy
import gpu
from multiprocessing import Process, shared_memory, Pipe, connection, Value
import multiprocessing
from . import view_manager
from . import shader_setup
from . import cache_manager

import sys
from pathlib import Path

# We need to load the tile_group_process and tile_group_types modules from the root of sys.path so as for them to not be bundled in bl_ext
# when we spawn and communicate with the loading process
lidarhd_ext_dir = str(Path(__file__).parent / "folder_to_expose")
sys.path.insert(0, lidarhd_ext_dir)
from lidarhd_ext.tile_group_process import loading_process
from lidarhd_ext.tile_group_types import TileDrawingData, AddonStatePack
sys.path.remove(lidarhd_ext_dir)

class TileGroup():
    
    draw_handler: any # holds the handler for the self.draw() call
    
    target_ram_usage: int # only used to check in the UI if the ram usage prop has been modified
    
    tile_paths: list[str]
    path_to_tile_drawing_data: dict[str, TileDrawingData]
    path_to_batch: dict[str, gpu.types.GPUBatch]
    path_to_texture: dict[str, shader_setup.TextureHandle]
    
    global_center: np.ndarray
    
    tile_batching_pipe: connection.Connection
    state_pipe: connection.Connection
    tile_export_pipe: connection.Connection
    image_loading_pipe: connection.Connection
    shared_memory: shared_memory.SharedMemory
    export_is_available: Value
    
    array_for_batching: np.ndarray
    
    loading_process: Process
    
    def __init__(self, tile_paths: list[str]):
        
        self.tile_paths = cache_manager.converted_to_cached_tile_paths(tile_paths)
        
        if len(self.tile_paths) < 1:
            raise RuntimeError
        
        self.target_ram_usage = bpy.context.scene.lidar_hd.target_point_ram_usage
        
        ctx = multiprocessing.get_context('spawn')
        
        self.tile_batching_pipe, loading_process_tile_batching_pipe = ctx.Pipe()
        self.state_pipe, loading_process_state_pipe = ctx.Pipe()
        self.tile_export_pipe, loading_process_tile_export_pipe = ctx.Pipe()
        self.image_loading_pipe, loading_process_image_loading_pipe = ctx.Pipe()
        self.export_is_available = ctx.Value('b', 0)
        
        sys.path.insert(0, lidarhd_ext_dir)
        self.loading_process = ctx.Process(target=loading_process, args=(
            self.target_ram_usage,
            self.tile_paths,
            loading_process_tile_batching_pipe,
            loading_process_state_pipe,
            loading_process_tile_export_pipe,
            loading_process_image_loading_pipe,
            cache_manager.get_cache_texture_dir(),
            self.export_is_available
        ))
        self.loading_process.start()
        sys.path.remove(lidarhd_ext_dir)
        
        # because the loading process holds all the COPCReaders, it also creates the TileDrawingData objects and sends them to us
        # print("Now waiting for drawing data...")
        self.path_to_tile_drawing_data = self.tile_batching_pipe.recv()
        # print(f"Received {len(self.path_to_tile_drawing_data)} tiles!")
        
        min_x = np.inf
        max_x = -np.inf
        min_y = np.inf
        max_y = -np.inf
        min_z = np.inf
        max_z = -np.inf
        for tile in self.path_to_tile_drawing_data.values():
            min_x = np.min([min_x, tile.center[0]])
            max_x = np.max([max_x, tile.center[0]])
            min_y = np.min([min_y, tile.center[1]])
            max_y = np.max([max_y, tile.center[1]])
            min_z = np.min([min_z, tile.center[2]])
            max_z = np.max([max_z, tile.center[2]])
           
        self.global_center = np.array([(min_x+max_x)*0.5, (min_y+max_y)*0.5, (min_z+max_z)*0.5])
        
        # The shared memory is created by the loading process
        # because it is the one who knows how long the buffer needs to be to hold the largest tile
        # it returns to use the name of the process to connect to, and the dtype of the points
        # which it knows by querying one of the tiles
        
        # print("Waiting to receive process name and dtype...")
        (shared_memory_name, dtype, array_size) = self.tile_batching_pipe.recv()
        # print(f"received {shared_memory_name}!")
        
        self.shared_memory = shared_memory.SharedMemory(name=shared_memory_name)
        
        self.array_for_batching = np.frombuffer(self.shared_memory.buf[:array_size], dtype=dtype)
        # print("Successfully tied the array for batching ")
        
        self.path_to_batch = {}
        self.path_to_texture = {}
        black_texture = shader_setup.load_image_to_gpu(np.full([16, 16], 0xFF8F8F8F, dtype=np.uint32))
        for path in self.tile_paths:
            self.path_to_texture[path] = black_texture
        
        self.draw_handler = bpy.types.SpaceView3D.draw_handler_add(self.draw, (), 'WINDOW', 'POST_VIEW')
        # print("Drawing handler added !")
    
    def draw(self):
        # print("drawing")
        view_manager.update_camera_pivot_position()
        if not bpy.context.scene.lidar_hd.visible:
            return
        
        if self.tile_batching_pipe.poll(): # if the loading process has sent someting in that pipe, signaling array_for_batching is ready
            # print("Starting to batch")
            if (received := self.tile_batching_pipe.recv()) is not None: # I replaced the while with an if to allow for drawing to occur in-between batches
                (tile_path, level_once_batched) = received
                end_vertex_index = self.path_to_tile_drawing_data[tile_path].level_vertex_indices[level_once_batched]
                self.path_to_batch[tile_path] = shader_setup.generate_batch(self.array_for_batching[:end_vertex_index])
                self.path_to_tile_drawing_data[tile_path].loaded_level = level_once_batched
                self.tile_batching_pipe.send(1) # we send whatever to signal to the loading process we are ready for the next tile
            # print("Done batching")
        
        if self.image_loading_pipe.poll():
            # print("Starting to load images")
            if (received := self.image_loading_pipe.recv()) is not None:
                (tile_path, resolution, image_byte_size) = received
                array = np.frombuffer(self.shared_memory.buf[:image_byte_size], dtype=np.float32)
                self.path_to_texture[tile_path] = shader_setup.load_image_to_gpu(array, resolution=resolution)
                self.image_loading_pipe.send(1)
        
        #print("Main process checks if state pipe is full")
        if self.state_pipe.poll() and not view_manager.camera_is_moving and not bpy.context.scene.lidar_hd.loading_locked: # If the loading process has signaled it wants a new state pack
            # we also check if the camera is moving so we don't ask the loading process to load when we're not done translating the camera around
            # print("it is !")
            self.state_pipe.recv()
            # print("Main process sends addonstatepack")
            self.state_pipe.send(AddonStatePack(
                view_manager.camera_pivot_position,
                list(bpy.context.scene.lidar_hd.minimum_radii),
                list(bpy.context.scene.lidar_hd.texture_resolutions),
                bpy.app.online_access
                ))
        
        matrix = bpy.context.region_data.perspective_matrix
        euler_angles = matrix.to_euler()
        display_mode = bpy.context.scene.lidar_hd.get("display_mode", 0)
        camera_position = np.array(bpy.context.region_data.view_matrix.inverted().translation)
        shader_setup.point_shader.uniform_float("viewProjectionMatrix", matrix)
        shader_setup.point_shader.uniform_int("displayMode", display_mode)
        shader_setup.point_shader.uniform_int("visibleClasses", bpy.context.scene.lidar_hd.class_visibility_bit_field)
        for path in self.tile_paths:
            if path not in self.path_to_batch:
                continue
            tile = self.path_to_tile_drawing_data[path]
            if tile.loaded_level is None:
                continue
            
            my_offset = self.global_center
            
            view_is_top_down = bpy.context.region_data.is_orthographic_side_view and abs(euler_angles.y) < 0.1 and abs(euler_angles.z) < 0.1
            if(view_is_top_down and display_mode == 0):
                shader_setup.bg_img_shader.uniform_float("viewProjectionMatrix", matrix)
                #shader_setup.bg_img_shader.uniform_float("scale", tile.reader.header.scales * bpy.context.scene.lidar_hd.size)
                shader_setup.bg_img_shader.uniform_sampler("image", self.path_to_texture[path].texture)
                shader_setup.bg_img_shader.uniform_float("offset", (my_offset*-1)+tile.center+bpy.context.scene.lidar_hd.point_cloud_offset)
                gpu.state.depth_test_set('LESS_EQUAL')
                shader_setup.background_image_batch.draw(shader_setup.bg_img_shader)
                
            shader_setup.point_shader.uniform_float("bounds", tile.bounds)
            if display_mode == 0:
                shader_setup.point_shader.uniform_sampler("image", self.path_to_texture[path].texture)
            shader_setup.point_shader.uniform_float("offset", (my_offset*-1)+bpy.context.scene.lidar_hd.point_cloud_offset)
            
            gpu.state.depth_test_set('LESS_EQUAL')
        
            distance_from_cam = tile.distance_from_position(self.global_center, camera_position, in3d=True)
            adjusted_distance = max(1, distance_from_cam-500)
            level = int(np.power(1/((adjusted_distance/(6000*bpy.context.scene.lidar_hd.lod_multiplier))**2), 1/3.8))
            bound_level = min(tile.loaded_level, max(0, level))
            point_size = bpy.context.scene.lidar_hd.point_size
            if bpy.context.region_data.is_perspective:
                if bpy.context.scene.lidar_hd.point_scaling == "perspective":
                    point_size = bpy.context.scene.lidar_hd.point_size * -1
                    point_size = point_size * 50 * np.power(tile.level_vertex_indices[bound_level] / tile.level_vertex_indices[0], -0.5)
            shader_setup.point_shader.uniform_float("pointSize", point_size)
            
            self.path_to_batch[path].draw_range(shader_setup.point_shader, elem_start=0, elem_count=tile.level_vertex_indices[bound_level])
            
    def closest_tile_to_point_cloud(self):
        closest_path = None
        closest_tile = None
        closest_distance = 100000000
        for path, tile in self.path_to_tile_drawing_data.items():
            distance = tile.distance_from_position(self.global_center, view_manager.camera_pivot_position)
            if distance < closest_distance:
                closest_path = path
                closest_tile = tile
                closest_distance = distance
                
        if closest_tile is None:
            return
        if closest_tile.loaded_level is None:
            return
        
        # print("I sent the loading process the path of the closest tile so it loads it in the shared memory")
        self.tile_export_pipe.send(closest_path)
        
        # We wait until the loading process sends whatever back to signal it's done writing in the shared memory
        self.tile_export_pipe.recv()
        
        tile_points = np.frombuffer(self.shared_memory.buf, self.array_for_batching.dtype, count=closest_tile.level_vertex_indices[closest_tile.loaded_level])

        name = f"tile-{int(closest_tile.center[0]/1000)}-{int(closest_tile.center[1]/1000)}"
        mesh = bpy.data.meshes.new(name)
        
        mesh.vertices.add(len(tile_points))
        coords = np.column_stack([
            (tile_points["X"]/100) -self.global_center[0] + bpy.context.scene.lidar_hd.point_cloud_offset[0],
            (tile_points["Y"]/100) -self.global_center[1] + bpy.context.scene.lidar_hd.point_cloud_offset[1],
            (tile_points["Z"]/100) -self.global_center[2] + bpy.context.scene.lidar_hd.point_cloud_offset[2]
            ]).astype(np.float32)
        mesh.vertices.foreach_set("co", coords.ravel())
        
        intensity_attr = mesh.attributes.new("intensity", "INT", "POINT")
        intensity_attr.data.foreach_set("value", tile_points["intensity"].astype(np.int32))
        
        classification_attr = mesh.attributes.new("classification", "INT8", "POINT")
        classification_attr.data.foreach_set("value", tile_points["classification"])
        
        return_number_attr = mesh.attributes.new("return_number", "INT8", "POINT")
        return_number_attr.data.foreach_set("value", (tile_points["bit_fields"] & 0b00001111).astype(np.int8))
        
        number_of_returns_attr = mesh.attributes.new("number_of_return", "INT8", "POINT")
        number_of_returns_attr.data.foreach_set("value", ((tile_points["bit_fields"] >> 4) & 0b00001111).astype(np.int8))
        
        scan_angle_attr = mesh.attributes.new("scan_angle", "INT", "POINT")
        scan_angle_attr.data.foreach_set("value", tile_points["scan_angle"].astype(np.int32))
        
        point_source_id_attr = mesh.attributes.new("point_source_id", "INT", "POINT")
        point_source_id_attr.data.foreach_set("value", tile_points["point_source_id"].astype(np.int32))
        
        gps_time_attr = mesh.attributes.new("gps_time", "FLOAT", "POINT")
        gps_time_attr.data.foreach_set("value", tile_points["gps_time"].astype(np.float32))
        
        level_attr = mesh.attributes.new("level", "INT8", "POINT")
        level_attr.data.foreach_set("value", tile_points["user_data"])
        
        mesh.update()
        
        obj = bpy.data.objects.new(name, mesh)
        collection = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(collection)
        collection.objects.link(obj)
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        
        bpy.ops.object.convert(target='POINTCLOUD')
        
        point_cloud = obj.data
        rad_attr = point_cloud.attributes.new("radius", "FLOAT", "POINT")
        rad_attr.data.foreach_set("value", np.full(len(tile_points), 0.3, dtype=np.float32))
        

    def prepare_for_deletion(self):
        bpy.types.SpaceView3D.draw_handler_remove(self.draw_handler, 'WINDOW')
        del self.array_for_batching
        self.shared_memory.close()
        self.loading_process.kill()
        
        
test_tiles = None