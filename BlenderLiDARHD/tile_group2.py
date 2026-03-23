import laspy
import numpy as np
import bpy
import gpu
import threading
from typing import Union
from . import view_manager
from . import laspy_extension
from . import shader_setup
from . import wms_downloading
from . import cache_manager

class Tile():
    
    reader: laspy.CopcReader
    
    bounds: list
    
    level_byte_sizes: list[int]
    level_point_counts: list[int]
    level_vertex_indices: list[int]
    
    batch: gpu.types.GPUBatch
    texture: Union[shader_setup.TextureHandle, np.ndarray]
    texture_is_loading: bool
    
    level: int
    
    def __init__(self, path: str):
        self.reader = laspy.CopcReader.open(path)
        self.reader.http_strategy = "thread"
        self.bounds = [self.reader.header.mins[0], self.reader.header.mins[1], self.reader.header.maxs[0], self.reader.header.maxs[1]]
        self.level_byte_sizes, self.level_point_counts = get_octree_byte_sizes_and_point_counts(self.reader.root_page)
        self.level_vertex_indices = []
        for point_count in self.level_point_counts:
            if len(self.level_vertex_indices) < 1:
                self.level_vertex_indices.append(point_count)
            else:
                self.level_vertex_indices.append(point_count + self.level_vertex_indices[-1])
        self.batch = None
        self.texture = None
        self.texture_is_loading = False
        self.level = None
        print("Created tile")
        print("point counts:")
        print(self.level_point_counts)
        print("vertex indices")
        print(self.level_vertex_indices)
        print("bounds")
        print(self.bounds)
        print(self.reader.copc_info.center)
    
    def get_level_count(self) -> int:
        return len(self.level_byte_sizes) # faster than max(entry.key.level for entry in hierarchy.entries)
    
    def load_image(self, resolution: int = 128):
        self.texture_is_loading = True
        try:
            image = wms_downloading.load_image(
                bounds=self.bounds,
                image_resolution=resolution
            )
            if image is None:
                self.texture = np.zeros([16, 16])
            else: self.texture = image
        except:
            print("Something went wrong loading an image")
        self.texture_is_loading = False
        

class TileGroup():
    
    draw_handler: any # holds the handler for the self.draw() call
    
    tile_ram_target_gb: int
    
    tiles: list[Tile]
    pools: list[np.array]
    pool_block_sizes: list[int] # number of points in each block of a pool
    loaded_tiles = list[list[Tile]] # at each level, the tiles loaded in the pool in order. None if block is empty
    
    array_for_batching: np.array # used to regroup points of a tile in a contiguous array in order to call generate_batch
    
    global_center: np.ndarray
    
    loading_thread: threading.Thread
    stop_event: threading.Event
    
    def __init__(self, tile_paths: list[str]):
        if len(tile_paths) < 1:
            self.tiles = []
            raise RuntimeError
        
        tile_paths = cache_manager.converted_to_cached_tile_paths(tile_paths)
        
        # create the tiles
        self.tiles = []
        for path in tile_paths:
            try:
                self.tiles.append(Tile(path))
            except:
                print(f"The tile {path} failed to initialize !")
                continue
        
        if len(self.tiles) == 0:
            raise RuntimeError
        
        largest_point_count = 0
        # find the largest tile point count and allocate array_for_batching at that size
        for tile in self.tiles:
            largest_point_count = max(largest_point_count, tile.reader.header.point_count)
        
        # find the largest tile point count at each level
        self.pool_block_sizes = []
        for tile in self.tiles:
            for level in range(tile.get_level_count()):
                if len(self.pool_block_sizes)-1 < level:
                    self.pool_block_sizes.append(0)
                if self.pool_block_sizes[level] < tile.level_point_counts[level]:
                    self.pool_block_sizes[level] = tile.level_point_counts[level]
        
        # create the pools using the largest point count as the size of a block
        dtype = get_tile_dtype(self.tiles[0])
        self.tile_ram_target_gb = bpy.context.scene.lidar_hd.target_point_ram_usage
        pool_block_counts = self.compute_pool_sizes_for_target_ram(self.tile_ram_target_gb*1000000000, dtype)
        self.pools = []
        self.loaded_tiles = []
        total_space = 0
        for i in range(len(self.pool_block_sizes)):
            pool = np.zeros(self.pool_block_sizes[i]*pool_block_counts[i], dtype=dtype)
            self.pools.append(pool)
            self.loaded_tiles.append([None] * pool_block_counts[i])
            total_space += pool.nbytes
            
        # print(f"my pools occupy {total_space/1000000000} GB")
        
        # allocate the array_for_batching array at the size of the largest point count
        self.array_for_batching = np.zeros(largest_point_count, dtype=dtype)
        
        min_x = np.inf
        max_x = -np.inf
        min_y = np.inf
        max_y = -np.inf
        min_z = np.inf
        max_z = -np.inf
        for tile in self.tiles:
            min_x = np.min([min_x, tile.reader.copc_info.center[0]])
            max_x = np.max([max_x, tile.reader.copc_info.center[0]])
            min_y = np.min([min_y, tile.reader.copc_info.center[1]])
            max_y = np.max([max_y, tile.reader.copc_info.center[1]])
            min_z = np.min([min_z, tile.reader.copc_info.center[2]])
            max_z = np.max([max_z, tile.reader.copc_info.center[2]])
            
        self.global_center = np.array([(min_x+max_x)*0.5, (min_y+max_y)*0.5, (min_z+max_z)*0.5])
        
        # for now, just load every tile's image at 128 res
        total_image_space = 0
        for tile in self.tiles:
            tile.texture = shader_setup.load_image_to_gpu(np.zeros([16, 16]))
            total_image_space += tile.texture.nbytes
            
        self.stop_event = threading.Event()
        self.loading_thread = threading.Thread(target=self.load_unload_routine)
        self.loading_thread.daemon = True
        self.loading_thread.start()
        
        self.draw_handler = bpy.types.SpaceView3D.draw_handler_add(self.draw, (), 'WINDOW', 'POST_VIEW')
        
    
    def load_unload_points(self):
        # print("Load unload points routine started")
        if self.loading_needed():
            # print("Need to load points")
            tiles_to_load: list[list[Tile]] = self.get_all_tiles_to_load() # the tiles which need to load in points
            
            tile_indices_to_load: dict[Tile, dict[int, int]] = {} # for each tile, for each pool level its index in the pool
            
            tiles_to_batch: list[Tile] = [] # the tiles that need a new GPUBatch batch.
            # This includes tiles which need to load points in, and tiles which are getting "loaded out"/overwritten
            
            # Keep in mind that self.loaded_tiles is mutated during this loop.
            # It's a safe not the source of truth for what tile is loaded where until the points are queried.
            
            # print("Finding tiles to load and batch...")
            for level in range(len(self.pools)):
                # unload tiles that should not be loaded
                for i in range(len(self.loaded_tiles[level])):
                    if self.loaded_tiles[level][i] is None:
                        continue
                    if self.loaded_tiles[level][i] not in tiles_to_load[level]:
                        if self.loaded_tiles[level][i] not in tiles_to_batch:
                            tiles_to_batch.append(self.loaded_tiles[level][i])
                        self.loaded_tiles[level][i] = None
                
                # assign tiles to be loaded to blocks, updates self.loaded_tiles
                for tile in tiles_to_load[level]:
                    if tile in self.loaded_tiles[level]:
                        continue
                    for i in range(len(self.loaded_tiles[level])):
                        if self.loaded_tiles[level][i] is None:
                            self.loaded_tiles[level][i] = tile
                            # the following line is the one that populates the tile_indices dict
                            tile_indices_to_load.setdefault(tile, {})[level] = i*self.pool_block_sizes[level]
                            break
            
            # we add all the tiles that need loading to 
            for tile in tile_indices_to_load.keys():
                tiles_to_batch.append(tile)
    
            # for tile in tiles_to_batch:
            #     level_of_tile = 0
            #     for level in range(len(self.loaded_tiles)):
            #         if tile in self.loaded_tiles[level]:
            #             if level < tile.level:
            #                 level_of_tile = level
            #     tile.level = level_of_tile
            
            # print("Done !")
            # print("Querying...")
            for tile, index_per_level in tile_indices_to_load.items():
                # print(f"Query for tile {tile.level_point_counts[0]}")
                try:
                    laspy_extension.query_levels_into(tile.reader, self.pools, index_per_level)
                except:
                    print("Query failed !")
                    for level, index in index_per_level:
                        self.loaded_tiles[level][index] = None # mark the tiles from tile that failed to load as None to save the situation somewhat
            
            # we compute the level the tiles will be on once batched in advance, and we set that level exactly when the batch is created
            # setting the level before or after would pose problems because of the async running of this function and the time each batch takes to get created, I think
            # in the same loop, we trigger image loads if the image resolution doesn't match the required res at the tile's level.
            image_res_by_level = bpy.context.scene.lidar_hd.texture_resolutions
            levels_once_batched: dict[Tile, int] = {}
            for tile in tiles_to_batch:
                level_of_tile = 0
                for level in range(len(self.loaded_tiles)):
                    if tile in self.loaded_tiles[level]:
                        level_of_tile = level
                levels_once_batched[tile] = level_of_tile
                
                # if the tile is loaded at its max level but its max level isn't high enough to require max texture res, we force highest texture res
                if len(tile.level_point_counts)-1 == level_of_tile:
                    level_of_tile = len(image_res_by_level)-1
                
                # if the texture is already loading, we don't do anything to it
                if tile.texture_is_loading:
                    continue
                
                if isinstance(tile.texture, np.ndarray):
                    new_thread = threading.Thread(target=tile.load_image, args=(image_res_by_level[level_of_tile],))
                    new_thread.start()
                    # image_loading_threads.append(new_thread)
                elif tile.texture.resolution != image_res_by_level[level_of_tile]:
                    new_thread = threading.Thread(target=tile.load_image, args=(image_res_by_level[level_of_tile],))
                    new_thread.start()
                    # image_loading_threads.append(new_thread)
               
            # print("Done !")
            # print("Batching...")
            for tile in tiles_to_batch:
                tile.batch = self.batch_for_tile(tile)
                tile.level = levels_once_batched[tile]
                # print(f"Set to level {tile.level}")
            # print("Done !")
            
        
    def loading_needed(self) -> bool:
        minimum_radii = bpy.context.scene.lidar_hd.minimum_radii
        
        for tile in self.tiles:
            distance_from_camera = tile_distance_from_position(tile, self.global_center, view_manager.camera_pivot_position)
            required_level = None
            for level in range(min(len(minimum_radii), len(tile.level_point_counts))):
                if distance_from_camera < minimum_radii[level]:
                    required_level = level
            
            # print(f"distance to camera {distance_from_camera}")
            # print(f"required level {required_level}")
            
            if required_level is None:
                continue
            
            if tile not in self.loaded_tiles[required_level]:
                return True
            
        return False
        
    
    def get_all_tiles_to_load(self) -> list[list[Tile]]: # for each level, all the tiles to load, not caring about what is already loaded or not
        
        distances: list[(Tile, float)] = []
        for tile in self.tiles:
            distance_from_camera = tile_distance_from_position(tile, self.global_center, view_manager.camera_pivot_position)
            distances.append((tile,distance_from_camera))
        distances.sort(key=lambda t:t[1])
        
        tiles_to_load_per_level: list[list[Tile]] = []
        for level in range(len(self.pool_block_sizes)):
            pool_size = len(self.pools[level])//self.pool_block_sizes[level]
            tiles_to_load = []
            for i in range(min(len(distances),pool_size)):
                if len(distances[i][0].level_point_counts) > level:
                    tiles_to_load.append(distances[i][0])
            tiles_to_load_per_level.append(tiles_to_load)
        
        return tiles_to_load_per_level
    
    # the target function started by the loading thread of the tile group
    # responsible for calling load_unload_points()
    def load_unload_routine(self):
        while not self.stop_event.is_set():
            try:
                if not bpy.context.scene.lidar_hd.loading_locked and bpy.context.scene.lidar_hd.visible:
                    self.load_unload_points()
            except:
                pass
            self.stop_event.wait(timeout=2)


    def draw(self):
        if not bpy.context.scene.lidar_hd.visible:
            return
        matrix = bpy.context.region_data.perspective_matrix
        euler_angles = matrix.to_euler()
        display_mode = bpy.context.scene.lidar_hd.get("display_mode", 0)
        camera_position = np.array(bpy.context.region_data.view_matrix.inverted().translation)
        shader_setup.point_shader.uniform_float("viewProjectionMatrix", matrix)
        shader_setup.point_shader.uniform_int("displayMode", display_mode)
        shader_setup.point_shader.uniform_int("visibleClasses", bpy.context.scene.lidar_hd.class_visibility_bit_field)
        # gpu.state.program_point_size_set(True)
        for tile in self.tiles:
            if tile.batch is None:
                continue
            if tile.level is None:
                continue
            if isinstance(tile.texture, np.ndarray):
                tile.texture = shader_setup.load_image_to_gpu(tile.texture)
            
            my_offset = self.global_center
            
            view_is_top_down = bpy.context.region_data.is_orthographic_side_view and abs(euler_angles.y) < 0.1 and abs(euler_angles.z) < 0.1
            if(view_is_top_down and display_mode == 0):
                shader_setup.bg_img_shader.uniform_float("viewProjectionMatrix", matrix)
                #shader_setup.bg_img_shader.uniform_float("scale", tile.reader.header.scales * bpy.context.scene.lidar_hd.size)
                shader_setup.bg_img_shader.uniform_sampler("image", tile.texture.texture)
                shader_setup.bg_img_shader.uniform_float("offset", (my_offset*-1)+tile.reader.copc_info.center+bpy.context.scene.lidar_hd.point_cloud_offset)
                gpu.state.depth_test_set('LESS_EQUAL')
                shader_setup.background_image_batch.draw(shader_setup.bg_img_shader)
                
            shader_setup.point_shader.uniform_float("bounds", tile.bounds)
            if display_mode == 0:
                shader_setup.point_shader.uniform_sampler("image", tile.texture.texture)
            shader_setup.point_shader.uniform_float("offset", (my_offset*-1)+bpy.context.scene.lidar_hd.point_cloud_offset)
            
            gpu.state.depth_test_set('LESS_EQUAL')
        
            distance_from_cam = tile_distance_from_position(tile, self.global_center, camera_position, in3d=True)
            adjusted_distance = max(1, distance_from_cam-500)
            level = int(np.power(1/((adjusted_distance/(6000*bpy.context.scene.lidar_hd.lod_multiplier))**2), 1/3.8))
            bound_level = min(tile.level, max(0, level))
            point_size = bpy.context.scene.lidar_hd.point_size
            if bpy.context.region_data.is_perspective:
                if bpy.context.scene.lidar_hd.point_scaling == "perspective":
                    point_size = bpy.context.scene.lidar_hd.point_size * -1
                    point_size = point_size * 50 * np.power(tile.level_vertex_indices[bound_level] / tile.level_vertex_indices[0], -0.5)
            shader_setup.point_shader.uniform_float("pointSize", point_size)
            
            tile.batch.draw_range(shader_setup.point_shader, elem_start=0, elem_count=tile.level_vertex_indices[bound_level])

    
    def batch_for_tile(self, tile: Tile) -> gpu.types.GPUBatch:
        # We check if the tile is loaded at all. I forgot why I do this but it doesn't hurt
        if(tile not in self.loaded_tiles[0]):
            return None
        
        cursor = 0
        print(f"batching tile {tile.level_point_counts[0]}")
        for level in range(len(tile.level_point_counts)):
            for i in range(len(self.loaded_tiles[level])):
                if self.loaded_tiles[level][i] == tile:
                    index = i*self.pool_block_sizes[level]
                    self.array_for_batching[cursor:cursor+tile.level_point_counts[level]] = self.pools[level][index:index+tile.level_point_counts[level]]
                    cursor += tile.level_point_counts[level]
                    
        # for level, index in sorted(index_per_level.items()): # sorted so as to have the levels in order, for batch.draw_range
        #     print(f"for level {level}, the start_index is {index}")
        #     print(f"the length of the write is of {tile.level_point_counts[level]}")
        #     print(f"the cursor is at position {cursor}")
        #     print(self.array_for_batching[cursor:cursor+tile.level_point_counts[level]])
        #     self.array_for_batching[cursor:cursor+tile.level_point_counts[level]] = self.pools[level][index:index+tile.level_point_counts[level]]
        #     print(self.array_for_batching[cursor:cursor+tile.level_point_counts[level]])
        #     cursor += tile.level_point_counts[level]
        return shader_setup.generate_batch(self.array_for_batching[:cursor])
    
    # called in __init__ to define the size of the pools depending on how much RAM it's permitted to use
    def compute_pool_sizes_for_target_ram(self, target_ram: int, dtype: np.dtype):
        target_ram = target_ram/2
        block_counts = [0]*len(self.pool_block_sizes)
        byte_size_at_level = []
        for level in range(len(self.pool_block_sizes)):
            byte_size_at_level.append(sum(self.pool_block_sizes[:level+1])*dtype.itemsize)
        remaining_ram = target_ram
        levels_to_check = [0, (len(self.pool_block_sizes)-1)//2, len(self.pool_block_sizes)-1]
        #levels_to_check = range(len(self.pool_block_sizes))
        number_of_tiles = len(self.tiles)
        for level in reversed(levels_to_check):#range(len(self.pool_block_sizes))):
            print(f"I'm adding largest tile of level {level}")
            while remaining_ram > byte_size_at_level[level] and number_of_tiles > 0:
                print(f"A tile at this level is {byte_size_at_level[level]/1000000000} GB in size so it's fine")
                for lvl in range(level+1):
                    block_counts[lvl] += 1
                    remaining_ram -= self.pool_block_sizes[lvl] * dtype.itemsize
                print(f"I added one and have {remaining_ram/1000000000} GB remaining")
                number_of_tiles -= 1
            if number_of_tiles == 0:
                print(f"I need to stop because I have no tiles left to allocate for")
            else:
                print(f"I need to stop because I have {remaining_ram/1000000000} GB remaining")
        
        print("Computed block counts")
        print(dtype.fields)
        return block_counts
    
    def closest_tile_to_point_cloud(self):
        closest_tile = None
        closest_distance = 100000000
        for tile in self.tiles:
            distance = tile_distance_from_position(tile, self.global_center, view_manager.camera_pivot_position)
            if distance < closest_distance:
                closest_tile = tile
                closest_distance = distance
                
        if closest_tile is None:
            return
        
        tile_points = np.zeros(closest_tile.level_vertex_indices[-1], dtype=self.pools[0].dtype)
        cursor = 0
        for level in range(len(closest_tile.level_point_counts)):
            for i in range(len(self.loaded_tiles[level])):
                if self.loaded_tiles[level][i] == closest_tile:
                    index = i*self.pool_block_sizes[level]
                    tile_points[cursor:cursor+closest_tile.level_point_counts[level]] = self.pools[level][index:index+closest_tile.level_point_counts[level]]
                    tile_points[cursor:cursor+closest_tile.level_point_counts[level]]["user_data"] = level
                    cursor += closest_tile.level_point_counts[level]
              
        for dim in closest_tile.reader.header.point_format.dimensions:
            print(dim.name, dim.dtype, dim.num_bits)

        name = f"tile-{int(closest_tile.reader.copc_info.center[0]/1000)}-{int(closest_tile.reader.copc_info.center[1]/1000)}"
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
        self.stop_event.set()
        self.loading_thread.join()
        
        

def tile_distance_from_position(tile: Tile, global_center: np.ndarray, position: np.ndarray, in3d: bool=False):
    tile_scene_center = tile.reader.copc_info.center - global_center
    if in3d:
        distance = np.linalg.norm(position-tile_scene_center)
    else:
        distance = np.linalg.norm(position[:2]-tile_scene_center[:2])
    return distance

# returns a list with the size in bytes and point count at each level of the point cloud.
# The index in the list corresponds to the level
def get_octree_byte_sizes_and_point_counts(root_page: laspy.copc.HierarchyPage) -> (list[int], list[int]):
    root_key: laspy.copc.VoxelKey = laspy.copc.VoxelKey()
    root_key.level = 0
    byte_size_list: list[int] = []
    point_count_list: list[int] = []
    walk_tree(root_key, root_page, byte_size_list, point_count_list)
    return byte_size_list, point_count_list

# does the walking of the octree, add the byte size of each node to the corresponding index in the byte_size_list described above, same for point count
def walk_tree(key: laspy.copc.VoxelKey, root_page: laspy.copc.HierarchyPage, byte_size_list: list[int], point_count_list: list[int]) -> int:
    if(key in root_page.entries):
        entry: laspy.copc.Entry = root_page.entries[key]
        if(len(byte_size_list) <= key.level):
            byte_size_list.append(0)
            point_count_list.append(0)
        byte_size_list[key.level] += entry.byte_size
        point_count_list[key.level] += entry.point_count
        for child in key.childs():
            walk_tree(child, root_page, byte_size_list, point_count_list)
    return

def get_tile_dtype(tile: Tile) -> np.dtype:
    points = tile.reader.query(resolution=1)
    return points.array.dtype

def get_rv3d(old_reference):
    # Fast path: check the cached reference is still alive
    if old_reference is not None:
        try:
            # Accessing any attribute will raise ReferenceError if the
            # underlying struct was freed
            _ = old_reference.view_matrix
            return old_reference
        except ReferenceError:
            old_reference = None

    # Slow path: walk areas once and cache
    for area in bpy.context.screen.areas:
        if area.type == 'VIEW_3D':
            rv3d = area.spaces[0].region_3d
            if rv3d is not None:
                old_reference = rv3d
                return rv3d
    return None


test_tiles = None
