import numpy as np
import laspy
from multiprocessing import shared_memory, connection, Value
import time

def loading_process(target_ram_usage: int,
                    converted_paths: list[str],
                    tile_batching_pipe: connection.Connection,
                    state_pipe: connection.Connection,
                    tile_export_pipe: connection.Connection,
                    image_loading_pipe: connection.Connection,
                    image_cache_dir: str,
                    export_is_availabe: Value):
    
    import threading
    from lidarhd_ext.tile_group_types import TileLoadingData, TileDrawingData, AddonStatePack
    import lidarhd_ext.laspy_extension as laspy_extension
    import lidarhd_ext.wms_downloading
    
    def loading_needed(addon_state: AddonStatePack, tiles: list[TileLoadingData], global_center: np.ndarray, pool_occupancy_list: list) -> bool:
        for tile in tiles:
            distance_from_camera = tile.distance_from_position(global_center, addon_state.camera_pivot_position)
            required_level = None
            for level in range(min(len(addon_state.minimum_radii), len(tile.level_point_counts))):
                if distance_from_camera < addon_state.minimum_radii[level]:
                    required_level = level
            
            # print(f"distance to camera {distance_from_camera}")
            # print(f"required level {required_level}")
            
            if required_level is None:
                continue
            
            if tile not in pool_occupancy_list[required_level]:
                return True
            
        return False
    
    def get_all_tiles_to_load(addon_state: AddonStatePack, tiles: list[TileLoadingData], pools: list[np.ndarray], pool_block_sizes: list[int], global_center: np.ndarray) -> list[list[TileLoadingData]]:
    
        distances: list[(TileLoadingData, float)] = []
        for tile in tiles:
            distance_from_camera = tile.distance_from_position(global_center, addon_state.camera_pivot_position)
            distances.append((tile,distance_from_camera))
        distances.sort(key=lambda t:t[1])
    
        tiles_to_load_per_level: list[list[TileLoadingData]] = []
        for level in range(len(pool_block_sizes)):
            pool_size = len(pools[level])//pool_block_sizes[level]
            tiles_to_load = []
            for i in range(min(len(distances),pool_size)):
                if len(distances[i][0].level_point_counts) > level:
                    tiles_to_load.append(distances[i][0])
            tiles_to_load_per_level.append(tiles_to_load)
    
        return tiles_to_load_per_level
    
    def write_points_for_batch(tile: TileLoadingData,
                               pools: list[np.ndarray],
                               pool_occupancy_list: list,
                               pool_block_sizes: list[int],
                               array_for_batching: np.ndarray):
        # We check if the tile is loaded at all. I forgot why I do this but it doesn't hurt
        if(tile not in pool_occupancy_list[0]):
            return None
        
        cursor = 0
        print(f"setting shared memory for tile {tile.level_point_counts[0]}")
        for level in range(len(tile.level_point_counts)):
            for i in range(len(pool_occupancy_list[level])):
                if pool_occupancy_list[level][i] == tile:
                    index = i*pool_block_sizes[level]
                    array_for_batching[cursor:cursor+tile.level_point_counts[level]] = pools[level][index:index+tile.level_point_counts[level]]
                    cursor += tile.level_point_counts[level]
                    
    def compute_pool_sizes_for_target_ram(number_of_tiles: int, pool_block_sizes: int, target_ram: int, dtype: np.dtype):
        target_ram = target_ram/2
        block_counts = [0]*len(pool_block_sizes)
        byte_size_at_level = []
        for level in range(len(pool_block_sizes)):
            byte_size_at_level.append(sum(pool_block_sizes[:level+1])*dtype.itemsize)
        remaining_ram = target_ram
        levels_to_check = [0, (len(pool_block_sizes)-1)//2, len(pool_block_sizes)-1]
        #levels_to_check = range(len(self.pool_block_sizes))
        for level in reversed(levels_to_check):#range(len(self.pool_block_sizes))):
            # print(f"I'm adding largest tile of level {level}")
            while remaining_ram > byte_size_at_level[level] and number_of_tiles > 0:
                # print(f"A tile at this level is {byte_size_at_level[level]/1000000000} GB in size so it's fine")
                for lvl in range(level+1):
                    block_counts[lvl] += 1
                    remaining_ram -= pool_block_sizes[lvl] * dtype.itemsize
                # print(f"I added one and have {remaining_ram/1000000000} GB remaining")
                number_of_tiles -= 1
            if number_of_tiles == 0:
                pass
                # print(f"I need to stop because I have no tiles left to allocate for")
            else:
                pass
                # print(f"I need to stop because I have {remaining_ram/1000000000} GB remaining")
        
        print("Computed block counts")
        # print(dtype.fields)
        return block_counts
    
    def get_tile_dtype(tile: TileLoadingData) -> np.dtype:
        points = tile.reader.query(resolution=1)
        return points.array.dtype
    
    def load_tile_image(tile: TileLoadingData, resolution: int, online_access: bool):
        tile.array_is_loading = True
        tile.image_array = lidarhd_ext.wms_downloading.load_image(image_cache_dir, tile.bounds, resolution, online_access)
        if tile.image_array is not None:
            tile.loaded_image_res = resolution
        tile.array_is_loading = False
    
    print("LOADING PROCESS STARTED SUCCESSFULLY")
    
    if len(converted_paths) < 1:
        raise RuntimeError
    
    # create the tiles
    tiles: list[TileLoadingData] = []
    path_dict: dict[TileLoadingData, str] = {}
    drawing_data_to_send: dict[str, TileDrawingData] = {}
    
    for path in converted_paths:
        try:
            new_tile = TileLoadingData(path=path)
        except Exception as e:
            print("Tile failed to initialize !")
            print(path)
            print(e)
            raise e
            
        tiles.append(new_tile)
        path_dict[new_tile] = path
        drawing_data_to_send[path] = TileDrawingData(
            new_tile.reader.copc_info.center,
            new_tile.bounds,
            new_tile.level_vertex_indices,
            None
        )
    
    if len(tiles) == 0:
        raise RuntimeError
    
    # we send the drawing data to the main process, which uses this data to draw the tiles correctly
    tile_batching_pipe.send(drawing_data_to_send)
    del drawing_data_to_send # not necessary but I won't need them afterwards and they shouldn't be here so it's cleaner this way
    
    
    largest_point_count = 0
    # find the largest tile point count and allocate array_for_batching at that size
    for tile in tiles:
        largest_point_count = max(largest_point_count, tile.reader.header.point_count)
        
    dtype = get_tile_dtype(tile=tiles[0])
    
    byte_size_of_largest_texture = 4*4096*4096
    
    shm = shared_memory.SharedMemory(create=True, size=max(dtype.itemsize*largest_point_count, byte_size_of_largest_texture), track=True)
    # the shared memory block is at minimum the size of a 4096 texture, so we can still write texture in it even if no tile is that big for some reason
    print("Loading process created the shared memory. It sends the name and dtype through the tile batching pip")
    tile_batching_pipe.send((shm.name, dtype, dtype.itemsize*largest_point_count)) # shared mem name, dtype of points, byte size of array_for_batching
    
    # find the largest tile point count at each level
    pool_block_sizes: list[int] = []
    for tile in tiles:
        for level in range(tile.get_level_count()):
            if len(pool_block_sizes)-1 < level:
                pool_block_sizes.append(0)
            if pool_block_sizes[level] < tile.level_point_counts[level]:
                pool_block_sizes[level] = tile.level_point_counts[level]
    
    pool_block_counts = compute_pool_sizes_for_target_ram(
        number_of_tiles=len(tiles),
        pool_block_sizes=pool_block_sizes,
        target_ram=target_ram_usage*1000000000,
        dtype=dtype)
    
    # allocate the pools
    pools = []
    pool_occupancy_list = []
    total_space = 0
    for i in range(len(pool_block_sizes)):
        pool = np.zeros(pool_block_sizes[i]*pool_block_counts[i], dtype=dtype)
        pools.append(pool)
        pool_occupancy_list.append([None] * pool_block_counts[i])
        total_space += pool.nbytes
    
    print(f"my pools occupy {total_space/1000000000} GB")
    
    array_for_batching = np.frombuffer(shm.buf[:dtype.itemsize*largest_point_count], dtype=dtype)
    
    min_x = np.inf
    max_x = -np.inf
    min_y = np.inf
    max_y = -np.inf
    min_z = np.inf
    max_z = -np.inf
    for tile in tiles:
        min_x = np.min([min_x, tile.reader.copc_info.center[0]])
        max_x = np.max([max_x, tile.reader.copc_info.center[0]])
        min_y = np.min([min_y, tile.reader.copc_info.center[1]])
        max_y = np.max([max_y, tile.reader.copc_info.center[1]])
        min_z = np.min([min_z, tile.reader.copc_info.center[2]])
        max_z = np.max([max_z, tile.reader.copc_info.center[2]])
            
    global_center = np.array([(min_x+max_x)*0.5, (min_y+max_y)*0.5, (min_z+max_z)*0.5])
    
    while True:
        print("Loading process sends that it's ready")
        state_pipe.send(1) # We signal we are ready to receive a new state pack
        export_is_availabe.value = 1
        
        print("Loading process waits for response")
        while not (state_pipe.poll() or tile_export_pipe.poll()):
            time.sleep(0.1)
            
        if tile_export_pipe.poll(): # If the main process wants to export a tile
            closest_path = tile_export_pipe.recv()
            closest_tile: TileLoadingData = [key for key, val in path_dict.items() if val == closest_path][0]
            cursor = 0
            for level in range(len(closest_tile.level_point_counts)):
                for i in range(len(pool_occupancy_list[level])):
                    if pool_occupancy_list[level][i] == closest_tile:
                        index = i*pool_block_sizes[level]
                        array_for_batching[cursor:cursor+closest_tile.level_point_counts[level]] = pools[level][index:index+closest_tile.level_point_counts[level]]
                        array_for_batching[cursor:cursor+closest_tile.level_point_counts[level]]["user_data"] = level
                        cursor += closest_tile.level_point_counts[level]
            
            tile_export_pipe.send(1) # We send back a value to signal to the main process we're done loading the points into the shared memory
            continue
        
        
        addon_state: AddonStatePack = state_pipe.recv() # blocks until we receive a new state
        print("Loading process got response")
        
        if not loading_needed(addon_state, tiles, global_center, pool_occupancy_list):
            print("Loading not needed")
        else:
            print("loading needed")
            export_is_availabe.value = 0
            tiles_to_load: list[list[TileLoadingData]] = get_all_tiles_to_load(addon_state, tiles, pools, pool_block_sizes, global_center)
            tile_indices_to_load: dict[TileLoadingData, dict[int, int]] = {}
            tiles_to_batch: list[TileLoadingData] = []
            
            for level in range(len(pools)):
                # unload tiles that should not be loaded
                for i in range(len(pool_occupancy_list[level])):
                    if pool_occupancy_list[level][i] is None:
                        continue
                    if pool_occupancy_list[level][i] not in tiles_to_load[level]:
                        if pool_occupancy_list[level][i] not in tiles_to_batch:
                            tiles_to_batch.append(pool_occupancy_list[level][i])
                        pool_occupancy_list[level][i] = None
                
                # assign tiles to be loaded to blocks, updates pool_occupancy_list
                for tile in tiles_to_load[level]:
                    if tile in pool_occupancy_list[level]:
                        continue
                    for i in range(len(pool_occupancy_list[level])):
                        if pool_occupancy_list[level][i] is None:
                            pool_occupancy_list[level][i] = tile
                            # the following line is the one that populates the tile_indices dict
                            tile_indices_to_load.setdefault(tile, {})[level] = i*pool_block_sizes[level]
                            break
                
            for tile in tile_indices_to_load.keys():
                tiles_to_batch.append(tile)
            
            for tile, index_per_level in tile_indices_to_load.items():
                # print(f"Query for tile {tile.level_point_counts[0]}")
                try:
                    laspy_extension.query_levels_into(tile.reader, pools, index_per_level)
                except:
                    print("Query failed !")
                    for level, index in index_per_level:
                        pool_occupancy_list[level][index] = None
            
            levels_once_batched: dict[TileLoadingData, int] = {}
            for tile in tiles_to_batch:
                level_of_tile = 0
                for level in range(len(pool_occupancy_list)):
                    if tile in pool_occupancy_list[level]:
                        level_of_tile = level
                levels_once_batched[tile] = level_of_tile
            
                
            for tile in tiles_to_batch:
                write_points_for_batch(
                    tile,
                    pools,
                    pool_occupancy_list,
                    pool_block_sizes,
                    array_for_batching
                )
                tile_batching_pipe.send((path_dict[tile], levels_once_batched[tile]))
                # wait for the main process to tell us it's done batching the tile by sending whatever
                tile_batching_pipe.recv()
                
                tile.loaded_level = levels_once_batched[tile]
            # at the end of the for loop, we send None to signal we're done
            # but only if the for loop did something, if there were tiles to batch
            if len(tiles_to_batch) > 0:
                tile_batching_pipe.send(None)

        
        images_sent = 0
        for tile in tiles:
            if tile.array_is_loading:
                continue
            if tile.loaded_image_res != addon_state.texture_resolutions[tile.loaded_level]:
                new_thread = threading.Thread(target=load_tile_image, args=(tile, addon_state.texture_resolutions[tile.loaded_level], addon_state.online_access))
                new_thread.start()
                
            if tile.array_ready_for_sending() and not tile_export_pipe.poll():
                export_is_availabe.value = 0
                shm.buf[:tile.image_array.nbytes] = tile.image_array.tobytes()
                image_loading_pipe.send((path_dict[tile], tile.loaded_image_res, tile.image_array.nbytes))
                image_loading_pipe.recv()
                tile.image_array = None
                images_sent += 1
        if images_sent > 0:
            image_loading_pipe.send(None)