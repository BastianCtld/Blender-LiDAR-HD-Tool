import gpu
from gpu_extras.batch import batch_for_shader
import laspy
import numpy as np
from pathlib import Path

_dir = Path(__file__).parent

point_vertex_shader    = (_dir / "shaders/point.vert").read_text()
point_fragment_shader  = (_dir / "shaders/point.frag").read_text()
bg_img_vertex_shader   = (_dir / "shaders/bgimage.vert").read_text()
bg_img_fragment_shader = (_dir / "shaders/bgimage.frag").read_text()


#
#   POINT SHADER
#

point_format = gpu.types.GPUVertFormat()
point_format.attr_add(id="X", comp_type='I32', len=1, fetch_mode='INT')
point_format.attr_add(id="Y", comp_type='I32', len=1, fetch_mode='INT')
point_format.attr_add(id="Z", comp_type='I32', len=1, fetch_mode='INT')
# pack1 contains
# intensity (16 bits) - classification (8 bits) - bit_fields (8 bits)
point_format.attr_add(id="pack1", comp_type='U32', len=1, fetch_mode='INT')
# pack2 contains
# scan_angle (16 bits) - point_source_id (16 bits)
#point_format.attr_add(id="pack2", comp_type='U32', len=1, fetch_mode='INT')
#format.attr_add(id="intensity", comp_type='U16', len=1, fetch_mode='INT')
#format.attr_add(id="bit_fields", comp_type='U8', len=1, fetch_mode='INT')
#format.attr_add(id="classification_flags", comp_type='U8', len=1, fetch_mode='INT')
#format.attr_add(id="classification", comp_type='U8', len=1, fetch_mode='INT')
#format.attr_add(id="user_data", comp_type='U8', len=1, fetch_mode='INT')
# format.attr_add(id="scan_angle", comp_type='I16', len=1, fetch_mode='INT')
# format.attr_add(id="point_source_id", comp_type='U16', len=1, fetch_mode='INT')
#point_format.attr_add(id="gps_time", comp_type='F32', len=1, fetch_mode='FLOAT')

vertex_out = gpu.types.GPUStageInterfaceInfo("my_interface")
vertex_out.flat('UINT', "payload")
vertex_out.flat('VEC2', "uv")

shader_info = gpu.types.GPUShaderCreateInfo()
shader_info.push_constant('FLOAT', "pointSize")
shader_info.push_constant('UINT', "displayMode")
shader_info.push_constant('MAT4', "viewProjectionMatrix")
shader_info.push_constant('VEC3', 'offset')
shader_info.push_constant('VEC4', 'bounds')
shader_info.push_constant('UINT', "visibleClasses")
shader_info.vertex_in(0, 'INT', "X")
shader_info.vertex_in(1, 'INT', "Y")
shader_info.vertex_in(2, 'INT', "Z")
shader_info.vertex_in(3, 'UINT',  "pack1")
#shader_info.vertex_in(4, 'UINT',  "pack2")
#shader_info.vertex_in(5,'FLOAT',"gps_time")
shader_info.vertex_out(vertex_out)
shader_info.sampler(0, 'FLOAT_2D', "image")
shader_info.fragment_out(0, 'VEC4', "FragColor")
shader_info.vertex_source(point_vertex_shader)
shader_info.fragment_source(point_fragment_shader)

point_shader = gpu.shader.create_from_info(shader_info)

#
# TOP VIEW IMAGE SHADER
#

bg_image_format = gpu.types.GPUVertFormat()
bg_image_format.attr_add(id="vert", comp_type='F32', len=3, fetch_mode='FLOAT')
bg_image_format.attr_add(id="vertuv", comp_type="F32", len=2, fetch_mode='FLOAT')

vertex_out = gpu.types.GPUStageInterfaceInfo("bg_interface")
vertex_out.smooth('VEC2', "uv")

shader_info = gpu.types.GPUShaderCreateInfo()
shader_info.push_constant('MAT4', "viewProjectionMatrix")
shader_info.push_constant('VEC3', 'scale')
shader_info.push_constant('VEC3', 'offset')
shader_info.vertex_in(0, 'VEC3', "vert")
shader_info.vertex_in(1, 'VEC2', "vertuv")
shader_info.vertex_out(vertex_out)
shader_info.sampler(0, 'FLOAT_2D', "image")
shader_info.fragment_out(0, 'VEC4', "FragColor")
shader_info.vertex_source(bg_img_vertex_shader)
shader_info.fragment_source(bg_img_fragment_shader)

bg_img_shader = gpu.shader.create_from_info(shader_info)

def generate_batch(points: np.array):
    vertex_buffer = gpu.types.GPUVertBuf(len=len(points), format=point_format)
    vertex_buffer.attr_fill(id="X", data=points["X"])
    vertex_buffer.attr_fill(id="Y", data=points["Y"])
    vertex_buffer.attr_fill(id="Z", data=points["Z"])

    pack1 = (points["intensity"].astype(np.uint32) |
             points["classification"].astype(np.uint32) << 16 |
             points["bit_fields"].astype(np.uint32) << 24
    )
    # pack2 = (points["scan_angle"].astype(np.uint32) |
    #          points["point_source_id"].astype(np.uint32) << 16
    # )

    vertex_buffer.attr_fill(id="pack1", data=pack1)
    #vertex_buffer.attr_fill(id="pack2", data=pack2)

    #vertex_buffer.attr_fill(id="gps_time", data=points["gps_time"].astype(np.float32))
    
    batch = gpu.types.GPUBatch(type="POINTS", buf=vertex_buffer)

    return batch

def generate_bg_img_batch():
    vertices = [
        (-500, 500, 0),
        (500, -500, 0),
        (-500, -500, 0),
        
        (-500, 500, 0),
        (500, 500, 0),
        (500, -500, 0),
    ]
    uvs = [
        (0, 0),
        (1, 1),
        (0, 1),

        (0, 0),
        (1, 0),
        (1, 1),
    ]

    bg_img_batch = batch_for_shader(bg_img_shader, "TRIS", {"vert":vertices, "vertuv":uvs})

    return bg_img_batch

background_image_batch = generate_bg_img_batch()

class TextureHandle:
    def __init__(self, texture: gpu.types.GPUTexture, resolution: int, nbytes: int):
        self.texture = texture
        self.resolution = resolution
        self.nbytes = nbytes

def load_image_to_gpu(image: np.array) -> TextureHandle:
    # the RGBA8 format channel bytes are packed into a R32F channel because Blender only supports uploading FLOAT Buffers
    # the RGBA8 channels are unpacked in the fragment shader
    texture = gpu.types.GPUTexture(
        size=(image.shape[1], image.shape[0]),
        format="R32F",
        data=gpu.types.Buffer('FLOAT', image.size, image)
    )

    print("DONE LOADING IMAGE TO GPU")

    return TextureHandle(texture, image.shape[0], image.nbytes)

def get_bit_field_for_visibility(visibility):
    result = 0
    for i in range(len(visibility)):
        if visibility[i].visible:
            result |= (1 << i)
    return result

def get_bit_field_for_full_visibility():
    result = 0
    for i in range(11):
        result |= (1 << i)
    return result
    


# compute_shader_info = gpu.types.GPUShaderCreateInfo()
# compute_shader_info.image(0, 'R32UI', "INT_2D", "depthImage", qualifiers={"READ", "WRITE"})
# compute_shader_info.compute_source(compute_zpass)
# compute_shader_info.push_constant('MAT4', "viewProjectionMatrix")
# compute_shader_info.push_constant('VEC3', 'scale')
# compute_shader_info.push_constant('VEC3', 'offset')
# compute_shader_info.push_constant('UINT', 'pointCount')
# compute_shader_info.local_group_size(128, 1)

# compute_vertex_out = gpu.types.GPUStageInterfaceInfo("compute_interface")
# compute_vertex_out.smooth('VEC2', "uvInterp")

# cshader_info = gpu.types.GPUShaderCreateInfo()
# cshader_info.sampler(0, "INT_2D", "img_input")
# cshader_info.vertex_in(0, 'VEC2', "position")
# cshader_info.vertex_in(1, 'VEC2', "uv")
# cshader_info.vertex_out(compute_vertex_out)
# cshader_info.fragment_out(0, 'VEC4', "FragColor")
# cshader_info.vertex_source(compute_vertex)
# cshader_info.fragment_source(compute_fragment)

# def generate_compute_batch(points: laspy.ScaleAwarePointRecord):
#     texture_height = 4096
#     texture_width = int(np.ceil((len(points.array))/texture_height))
#     xyza = np.zeros((texture_height*texture_width, 4), dtype=np.int32)
#     xyza[:len(points.array),0] = points.array['X']
#     xyza[:len(points.array),1] = points.array['Y']
#     xyza[:len(points.array),2] = points.array['Z']

#     buffer = gpu.types.Buffer('FLOAT', (texture_width, texture_height, 4), xyza)
#     texture = gpu.types.GPUTexture(
#         size = (texture_width, texture_height),
#         format = "RGBA32F",
#         data=buffer
#     )

#     compute_shader_info.image(1, 'RGBA32F', "FLOAT_2D", "points", qualifiers={"READ"})

#     compute_shader = gpu.shader.create_from_info(compute_shader_info)
#     compute_shader.image("points", texture)
#     compute_shader.uniform_int("pointCount", len(points.array))
#     shader = gpu.shader.create_from_info(cshader_info)
#     batch = batch_for_shader(
#         shader, 'TRI_FAN',
#         {
#             "position": ((0, 0), (1, 0), (1, 1), (0, 1)),
#             "uv": ((0, 0), (1, 0), (1, 1), (0, 1)),
#         },
#     )
#     shader, compute_shader, batch


# def generate_compute_batch(points: laspy.ScaleAwarePointRecord, viewport_res: (int, int)):
#     texture = gpu.types.GPUTexture(viewport_res, format='RGBA64F')
