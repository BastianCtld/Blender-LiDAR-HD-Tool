# from owslib.wfs import WebFeatureService
# import json

# wfs = WebFeatureService("https://data.geopf.fr/wfs", version= '2.0.0')

# def get_names_and_urls(bbox: list[float]) -> [(str, str)]:
#     '''Returns a list of (file_name, url) tuples of all the tiles in the specified bounding box in MGS84 coordinates.'''
#     response = wfs.getfeature(
#     typename="IGNF_NUAGES-DE-POINTS-LIDAR-HD:dalle",
#     bbox=bbox,
#     #maxfeatures=4,
#     outputFormat="application/json",
#     )
#     data = json.loads(response.read())
#     all_tiles = []
#     for feature in data['features']:
#         all_tiles.append((feature["properties"]["name"], feature["properties"]["url"]))
#     return all_tiles