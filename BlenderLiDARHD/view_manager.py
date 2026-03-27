import bpy
import numpy as np

trusted_area = None
trusted_rv3d = None
camera_pivot_position = np.array([0, 0, 0])
camera_is_moving = False

def set_trusted_rv3d_to_current(_ = None, __ = None):
    global trusted_rv3d, trusted_area
    trusted_rv3d, trusted_area = find_active_rv3d_and_area()
    trusted_area.tag_redraw()

def find_active_rv3d_and_area():
    for area in bpy.context.screen.areas:
        if area.type == 'VIEW_3D':
            rv3d = area.spaces[0].region_3d
            if rv3d is not None:
                return rv3d, area
    return None, None

def set_trusted_rv3d(area):
    global trusted_rv3d, trusted_area
    if trusted_area is not None:
        trusted_area.tag_redraw()
    trusted_area = area
    trusted_rv3d = area.spaces[0].region_3d
    trusted_area.tag_redraw()

def update_camera_pivot_position():
    global camera_pivot_position
    if trusted_rv3d is not None:
        new_position = np.array(trusted_rv3d.view_location)
        if (camera_pivot_position==new_position).all():
            camera_is_moving = False
        else:
            camera_is_moving = True
            camera_pivot_position = new_position
        #print(camera_pivot_position)