import json

def add_links_to_link_list_from_metadonnees(context, file_path):
    with open(file=file_path) as f:
        parsed_content = json.load(f)
        for tile_name, tile_info in parsed_content.items():
            if tile_info['url'] is not None:
                item = context.scene.lidar_hd.link_list.add()
                item.value = tile_info['url']