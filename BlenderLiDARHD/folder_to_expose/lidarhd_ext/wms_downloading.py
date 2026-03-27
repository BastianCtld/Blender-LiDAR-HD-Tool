from owslib.wms import WebMapService
from owslib.util import ResponseWrapper
from PIL import Image
import numpy as np
import io
import os

wms = WebMapService("https://data.geopf.fr/wms-r/wms", version='1.3.0')

def load_image(cache_dir, bounds: list, image_resolution = 4096, online_access: bool = True):
    try:
        path = cache_dir+f"/{int(bounds[0]/1000)}-{int(bounds[1]/1000)}-res{image_resolution}.png"
        if not os.path.exists(path):
            if online_access:
                print(f"image not cached, downloading...")
                image: ResponseWrapper = wms.getmap(
                    layers=["HR.ORTHOIMAGERY.ORTHOPHOTOS"],
                    size=[image_resolution, image_resolution],
                    srs="EPSG:2154",
                    bbox=bounds,
                    format="image/jpeg"
                )
                image: Image = Image.open(io.BytesIO(image.read())).convert('RGBA')
                image.save(path)
            else:
                return None
        else:
            image = Image.open(path).convert('RGBA')
    except:
        return None

    array = np.array(image)
    return array