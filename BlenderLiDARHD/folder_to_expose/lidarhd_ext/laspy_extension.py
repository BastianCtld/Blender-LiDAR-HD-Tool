from laspy.copc import *
import lazrs

# This is a modified version of a laspy function that does the same thing but allocates a new array to receive the points.
# This function writes directly into the TileGroup pools
def query_levels_into(
    reader: CopcReader,
    pools: list[np.array],
    index_per_level: dict[int, int]
    ):
    
    level_to_query = max(index_per_level)
    # print(f"loading up to level {level_to_query}")
    range_to_query = range(0, level_to_query + 1)
    
    all_nodes: List[OctreeNode] = load_octree_for_query(
        reader.source,
        reader.copc_info,
        reader.root_page,
        query_bounds=None,
        level_range=range_to_query,
    )
    
    nodes_by_level: Dict[int, List[OctreeNode]] = {}
    for node in all_nodes:
        nodes_by_level.setdefault(node.key.level, []).append(node)

    for level, level_nodes in nodes_by_level.items():
        if len(pools) < level:
            continue
        if level not in index_per_level:
            continue
        
        pool = pools[level]
        start_index = index_per_level[level]
        level_nodes = sorted(level_nodes, key=attrgetter("offset"))
        print(f"Fetching chunks for level {level}...")
        compressed_bytes, num_points, chunk_table = reader._fetch_all_chunks([[node] for node in level_nodes])
        print(f"Done !")
        
        dest_slice = pool[start_index : start_index + num_points]
        dest_view = dest_slice.view(np.uint8).ravel()
        
        # print(f"Querying for level {level}")
        # print(f"writing data at index {start_index} for a length of {num_points}")

        print(f"Decompressing points for level {level}...")
        lazrs.decompress_points_with_chunk_table(
            compressed_bytes,
            reader.laszip_vlr.record_data,
            dest_view,
            chunk_table,
            reader.decompression_selection,
        )
        print("Done !")
        