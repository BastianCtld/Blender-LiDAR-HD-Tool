import numpy as np
import laspy

# some state from the addon bundled in a format sendable to other processes
class AddonStatePack():
    camera_pivot_position: np.ndarray
    point_cloud_offset: np.ndarray
    minimum_radii: list[int]
    texture_resolutions: list[int]
    online_access: bool
    
    def __init__(self, camera_pivot_position, point_cloud_offset, minimum_radii, texture_resolutions, online_access):
        self.camera_pivot_position = camera_pivot_position
        self.point_cloud_offset = point_cloud_offset
        self.minimum_radii = minimum_radii
        self.texture_resolutions = texture_resolutions
        self.online_access = online_access
    
# these are the representations of the tiles designed to live in the main process, to be used for drawing only
class TileDrawingData():
    center: np.ndarray
    bounds: list
    level_vertex_indices: list[int]
    # batches and textures will be stored as dictionaries in the tile group to make this class picklable
    # batch: gpu.types.GPUBatch
    # texture: shader_setup.TextureHandle
    loaded_level: int
    
    def __init__(self, center, bounds, level_vertex_indices, loaded_level):
        self.center = center
        self.bounds = bounds
        self.level_vertex_indices = level_vertex_indices
        self.loaded_level = loaded_level
        
    def distance_from_position(self, global_center: np.ndarray, tile_offset: np.ndarray, position: np.ndarray, in3d: bool=False):
        tile_scene_center = self.center - global_center + tile_offset
        if in3d:
            distance = np.linalg.norm(position-tile_scene_center)
        else:
            distance = np.linalg.norm(position[:2]-tile_scene_center[:2])
        return distance
    
class TileLoadingData():
    reader: laspy.CopcReader
    
    bounds: list
    
    level_point_counts: list[int]
    level_vertex_indices: list[int]
    
    loaded_image_res: int
    image_array: np.ndarray
    array_is_loading: bool
    
    loaded_level: int
    
    def __init__(self, path: str):
        print(f"Trying desperatly to load {path}")
        self.reader = laspy.CopcReader.open(path)
        print("Done !!!")
        self.bounds = [self.reader.header.mins[0], self.reader.header.mins[1], self.reader.header.maxs[0], self.reader.header.maxs[1]]
        self.level_vertex_indices = []
        _, self.level_point_counts = get_octree_byte_sizes_and_point_counts(self.reader.root_page)
        for point_count in self.level_point_counts:
            if len(self.level_vertex_indices) < 1:
                self.level_vertex_indices.append(point_count)
            else:
                self.level_vertex_indices.append(point_count + self.level_vertex_indices[-1])
        self.loaded_level = None
        self.image_array = None
        self.loaded_image_res = 0
        self.array_is_loading = False
    
    def get_level_count(self) -> int:
        return len(self.level_point_counts) # faster than max(entry.key.level for entry in hierarchy.entries)
    
    def distance_from_position(self, global_center: np.ndarray, tile_offset: np.ndarray, position: np.ndarray, in3d: bool=False):
        tile_scene_center = self.reader.copc_info.center - global_center + tile_offset
        if in3d:
            distance = np.linalg.norm(position-tile_scene_center)
        else:
            distance = np.linalg.norm(position[:2]-tile_scene_center[:2])
        return distance
    
    def array_ready_for_sending(self):
        return self.image_array is not None and not self.array_is_loading
    
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