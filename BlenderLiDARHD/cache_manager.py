import os
import bpy
import requests
import threading
import time

headers = {
    "User-Agent": "LiDARHDTool/1.1.1 (Blender add-on; https://github.com/BastianCtld/Blender-LiDAR-HD-Tool)"
}

def get_cache_tile_dir():
    return bpy.context.preferences.addons[__package__].preferences.cache_dir + "/copc_cache"
def get_cache_texture_dir():
    return bpy.context.preferences.addons[__package__].preferences.cache_dir + "/bd_ortho"

def converted_to_cached_tile_paths(paths: list[str], caching = True) -> list[str]:
    converted_paths = []
    threads: list[threading.Thread] = []
    for path in paths:
        # print(f"handling {path}")
        if "http" in path:
            filename = path.split("/")[-1]
            potentially_cached_file_name = get_cache_tile_dir() + "/" + filename
            if(os.path.exists(potentially_cached_file_name)):
                # print(f"Found cached version of {path}")
                converted_paths.append(potentially_cached_file_name)
            else:
                # the point cloud is not cached
                print(f"{path} is not cached")
                if caching:
                    if not bpy.app.online_access:
                        continue # If internet acces is not allowed and I'm about to download that tile, don't
                    new_thread = threading.Thread(target=point_cloud_get_thread, args=(path, potentially_cached_file_name, converted_paths))
                    new_thread.start()
                    threads.append(new_thread)
                    time.sleep(0.2)
                else:
                    converted_paths.append(path)
        else:
            converted_paths.append(path)
            
    for thread in threads:
        thread.join()
    
    return converted_paths

def point_cloud_get_thread(path, cached_file_name, converted_paths):
    print(f"Downloading {path}...")
    try:
        with open(cached_file_name, 'wb') as file:
            file.write(requests.get(path, timeout=30, headers=headers).content)
        converted_paths.append(cached_file_name)
    except:
        print("Download of {path} failed !")
        try:
            os.remove(cached_file_name)
        except OSError:
            pass
        pass
    print(f"Saved as {cached_file_name}")
    
def how_many_tiles_not_cached(paths) -> int:
    cached_counter = 0
    for path in paths:
        path_string = path.value
        if "http" in path_string:
            filename = path.split("/")[-1]
            potentially_cached_file_name = get_cache_tile_dir() + "/" + filename
            if(os.path.exists(potentially_cached_file_name)):
                cached_counter += 1
    
    return cached_counter
