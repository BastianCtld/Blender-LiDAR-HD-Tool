import bpy
import os
import webbrowser
import psutil
import gpu
from . import view_manager
from . import tile_group3
from . import shader_setup
from . import cache_manager

ram_amount = psutil.virtual_memory().total

class StringItem(bpy.types.PropertyGroup):
    value: bpy.props.StringProperty()
    
class PointCloudClass(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty()
    visible: bpy.props.BoolProperty(default=True)
    
class LIDARHD_OT_open_cache_folder(bpy.types.Operator):
    bl_idname = "lidarhd.opencachefolder"
    bl_label = "Open Cache Folder"
    
    def execute(self, context):
        bpy.ops.wm.path_open(filepath=bpy.context.preferences.addons[__package__].preferences.cache_dir)
        return {'FINISHED'}

class LIDARHD_OT_toggle_class_visibility(bpy.types.Operator):
    bl_idname = "lidarhd.toggle_class_visibility"
    bl_label = "Toggle Class Visibility"

    class_name: bpy.props.StringProperty()

    def execute(self, context):
        visibility = context.scene.lidar_hd.class_visibility
        for cls in visibility:
            if cls.name == self.class_name:
                cls.visible = not cls.visible
                break
        
        context.scene.lidar_hd.class_visibility_bit_field = shader_setup.get_bit_field_for_visibility(visibility)
        
        redraw_all_views(self, context)
                
        return {"FINISHED"}
    
class LIDARHD_OT_toggle_all_visibility(bpy.types.Operator):
    bl_idname = "lidarhd.toggle_visibility"
    bl_label = "Toggle All visibility"
    
    def execute(self, context):
        context.scene.lidar_hd.visible = not context.scene.lidar_hd.visible
        redraw_all_views(self, context)
        return {"FINISHED"}
    
class LIDARHD_OT_create_tile_group(bpy.types.Operator):
    bl_idname = "lidarhd.createtilegroup"
    bl_label = "Reload Last Session"
    
    def execute(self, context):
        if len(bpy.context.scene.lidar_hd.class_visibility) == 0:
            populate_default_values()
        if tile_group3.test_tiles is not None:
            tile_group3.test_tiles.prepare_for_deletion()
        try:
            tile_group3.test_tiles = tile_group3.TileGroup([item.value for item in context.scene.lidar_hd.link_list])
        except Exception as e:
            print(e)
            tile_group3.test_tiles = None
            
        view_manager.set_trusted_rv3d_to_current()
        
        return {'FINISHED'}
    
class LIDARHD_OT_warn_before_create(bpy.types.Operator):
    bl_idname = "lidarhd.warnbeforecreate"
    bl_label = "Confirm"
    
    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=300)
    
    def draw(self, context):
        layout = self.layout
        column = layout.column(align=True)
        column.label(text="Blender will download these tiles into the cache folder:")
        column.label(text=str(cache_manager.get_cache_tile_dir()))
        column.label(text="This operation might freeze Blender for a few minutes.")
        column.label(text="Are you sure to go forward?")
    
    def execute(self, context):
        bpy.ops.lidarhd.createtilegroup('EXEC_DEFAULT')
        return {'FINISHED'}
    
class LIDARHD_OT_delete_tile_group(bpy.types.Operator):
    bl_idname = "lidarhd.deletetilegroup"
    bl_label = "Are you sure?"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        if tile_group3.test_tiles is not None:
            tile_group3.test_tiles.prepare_for_deletion()
            tile_group3.test_tiles = None
            redraw_all_views(self, context)
        context.scene.lidar_hd.link_list.clear()
        return {'FINISHED'}
    
class LIDARHD_OT_to_blender_point_cloud(bpy.types.Operator):
    bl_idname = "lidarhd.toblenderpointcloud"
    bl_label = "Nearest Tile to Blender Point Cloud"
    bl_description = "Converts the tile closest to the viewport's pivot point into Blender's native point cloud object."
    
    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'
    
    def execute(self, context):
        if tile_group3.test_tiles is not None:
            if tile_group3.test_tiles.export_is_available.value == 1:
                tile_group3.test_tiles.closest_tile_to_point_cloud()
            else:
                self.report({'WARNING'}, "Please wait until the point cloud is done loading.")
                return {'CANCELLED'}
        return {'FINISHED'}
    
class LIDARHD_OT_open_lidarhd_browser(bpy.types.Operator):
    bl_idname = "lidarhd.openbrowser"
    bl_label = "Open the Dowload Interface..."
    bl_description = "Opens the official Downloading Interface in a new browser tab."
    
    def execute(self, context):
        webbrowser.open("https://cartes.gouv.fr/telechargement/IGNF_NUAGES-DE-POINTS-LIDAR-HD", 2)
        return {'FINISHED'}

class LIDARHD_OT_pick_file(bpy.types.Operator):
    bl_idname = "lidarhd.openlist"
    bl_label = "Load a dalle.txt..."
    bl_description = "Point to the dalle.txt file you obtained from the LiDAR HD Downloading Interface"

    filepath: bpy.props.StringProperty(
        subtype="FILE_PATH"
    )

    filter_glob: bpy.props.StringProperty(
        default="*dalles*.txt",
        options={'HIDDEN'}
    )

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        print("Selected file:", self.filepath)
        context.scene.lidar_hd.link_list.clear()
        with open(self.filepath) as f:
            for line in f.readlines():
                item = context.scene.lidar_hd.link_list.add()
                item.value = line.strip()
        print(f"the link list is {context.scene.lidar_hd.link_list}")
        contains_download = False
        for path in cache_manager.converted_to_cached_tile_paths([item.value for item in context.scene.lidar_hd.link_list], caching=False):
            if "http" in path:
                contains_download = True
        
        if contains_download:
            if bpy.app.online_access:
                bpy.ops.lidarhd.warnbeforecreate('INVOKE_DEFAULT') # Warns the user blender will freeze, and downloads
            else:
                # We don't outright cancel the operation, because some tiles might be available in cache without necessitating a download
                bpy.ops.lidarhd.createtilegroup('EXEC_DEFAULT') # Creates the tile group. cache_manager.py will ignore downloads by itself if online_access is false
                self.report({"WARNING"}, "Allow online access to download the missing tiles")
        else:
            bpy.ops.lidarhd.createtilegroup('EXEC_DEFAULT')
        
        return {'FINISHED'}
    
class LIDARHD_OT_pick_folder(bpy.types.Operator):
    bl_idname = "lidarhd.openfolder"
    bl_label = "Select a folder..."
    bl_description = "Point to a folder containing already downloaded COPC LAZ files."
    
    directory: bpy.props.StringProperty(
        name="Folder Path",
        description="Selected folder path",
        default="",
        subtype='DIR_PATH',
    )
    
    filter_folder: bpy.props.BoolProperty(default=True, options={'HIDDEN'})
    
    def execute(self, context):
        if not self.directory:
            self.report({'WARNING'}, "No folder selected.")
            return {'CANCELLED'}

        print(f"Selected folder: {self.directory}")
        
        context.scene.lidar_hd.link_list.clear()
        for file in os.listdir(self.directory):
            if file.endswith(".copc.laz"):
                item = context.scene.lidar_hd.link_list.add()
                item.value = self.directory + "/" + file
        
        bpy.ops.lidarhd.createtilegroup('EXEC_DEFAULT')
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}
    
class LIDARHD_OT_test(bpy.types.Operator):
    bl_idname = "my.test"
    bl_label = "Test"

    def execute(self, context):
        return {'FINISHED'}
    
class LIDARHD_OT_set_trusted_area(bpy.types.Operator):
    bl_idname = "lidarhd.settrustedarea"
    bl_label = "Load tiles based on this view"
    
    def execute(self, context):
        view_manager.set_trusted_rv3d(context.area)
        return {'FINISHED'}


def link_list_update(self, context):
    self.link_list_amount = len(self.link_list.split("laz"))-1
    
def set_area_as_trusted(area):
    view_manager.set_trusted_rv3d(area)
    
def redraw_all_views(self, context):
    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            area.tag_redraw()
    
@bpy.app.handlers.persistent
def populate_default_values(_=None):
    if tile_group3.test_tiles is not None:
        tile_group3.test_tiles.prepare_for_deletion()
        tile_group3.test_tiles = None
    view_manager.set_trusted_rv3d_to_current()
    bpy.context.scene.lidar_hd.class_visibility.clear()
    for name in ["Unclassified",
                 "Ground",
                 "Low Vegetation",
                 "Medium Vegetation",
                 "High Vegetation",
                 "Building",
                 "Water",
                 "Bridge Deck",
                 "Permanent Infrastructure",
                 "Virtual Points",
                 "Building-like features"]:
        item = bpy.context.scene.lidar_hd.class_visibility.add()
        item.name = name
    # print("ram ?")
    if bpy.context.scene.lidar_hd.target_point_ram_usage == 0:
        bpy.context.scene.lidar_hd.target_point_ram_usage = get_default_ram_usage()
    if not bpy.app.online_access:
        bpy.context.scene.lidar_hd.display_mode = "classification"

def get_default_ram_usage() -> int:
    return int(psutil.virtual_memory().total / 1000000000 / 4)

def update_target_ram(self, context):
    if self.target_point_ram_usage == 0:
        self.target_point_ram_usage = get_default_ram_usage()


class LiDAR_HD_Tool(bpy.types.PropertyGroup):
    loading_mode: bpy.props.EnumProperty(items=[
        ("link_list", "List of links", "Load point clouds from a list of download links obtainable at: https://cartes.gouv.fr/telechargement/IGNF_NUAGES-DE-POINTS-LIDAR-HD"),
        ("folder", "Folder", "Load point clouds from a folder on your computer.")
    ])
    # texture_resolution: bpy.props.IntProperty("Image Resolution", min=0, soft_min=5, max=12, default=11)
    link_list: bpy.props.CollectionProperty(name="List of Links", type=StringItem)
    point_cloud_offset: bpy.props.IntVectorProperty(name="Offset", default=(0, 0, 400))
    point_size: bpy.props.FloatProperty(name="Point Size", min=0, soft_min=0.1, soft_max=20, default=3)
    point_scaling: bpy.props.EnumProperty(name="Scaling", items=[
        ('perspective', "Perspective", "Scale points with camera distance.", 0),
        ('constant',    "Constant",    "Make every point the same size on screen regardless of distance.", 1),
    ], translation_context="lidarhd")
    display_mode: bpy.props.EnumProperty(name="Color", items=[
        ("aerial", "Projected Aerial Photos", "BD ORTHO aerial photography vertically projected.", 0),
        ("intensity", "LiDAR Intensity", "Return strength of the laser pulse that generated the point.", 1),
        ("classification", "Point Class", "Class of the point.", 2),
        ("tinted_class", "Class x Intensity", "Intensity of the point tinted depending on its classification.", 3),
    ])
    class_visibility: bpy.props.CollectionProperty(name="Class Visibility", type=PointCloudClass)
    class_visibility_bit_field: bpy.props.IntProperty(name="Visibility Bit Field", default=shader_setup.get_bit_field_for_full_visibility())
    visible: bpy.props.BoolProperty(name="Visible", default=True, update=redraw_all_views)
    loading_locked: bpy.props.BoolProperty(name="Loading Locked", default=False)
    lod_multiplier: bpy.props.FloatProperty(name="Drawing Distance", default=1.0, min=0.01, soft_max=3, description="Scales the display radius of each LOD level. Higher values draw finer detail further from the camera. Does not affect tile loading or memory usage.")
    texture_resolutions: bpy.props.IntVectorProperty(size=7, name="Texture Resolutions", default=[512, 512, 512, 4096, 4096, 4096, 4096], description="The resolution of the aerial image loaded for every level. Avoid many different resolutions.")
    minimum_radii: bpy.props.IntVectorProperty(size=7, name="Minimum Radii", default=[710, 710, 710, 710, 710, 710, 710], description="When a tile gets this close without being loaded at that level, point loading occurs.")
    target_point_ram_usage: bpy.props.IntProperty(name="Target RAM usage (GB):", default=0, min=0, soft_min=1, soft_max=100, update=update_target_ram, description="Approximately how much memory is dedicated to storing point tiles.")



class LIDARHD_PT_sidebar(bpy.types.Panel):
    bl_label = "LiDAR HD"
    bl_idname = "MY_PT_sidebar"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "LiDAR HD"

    def draw(self, context):
        layout = self.layout
        lidarctx = context.scene.lidar_hd
        
        if gpu.platform.backend_type_get() == "OPENGL":
            box = layout.box()
            box.alert = True
            box.label(text="OpenGL is not supported !", icon="WARNING_LARGE")
            box.label(text="Switch to the Vulkan backend if possible.")
        
        if view_manager.trusted_area != context.area:
            layout.label(text="This view does not update the point cloud", icon="WARNING_LARGE")
            layout.operator(operator="lidarhd.settrustedarea")
            layout.separator()
            
        if tile_group3.test_tiles is None and len(lidarctx.link_list) > 0:
            layout.operator(operator="lidarhd.createtilegroup", icon="FILE_REFRESH")

        point_loading_header, point_loading_body = layout.panel("point_loading")
        point_loading_header.label(text="Point Loading")
        if(point_loading_body):
            row = point_loading_body.row(align=True)
            row.prop(lidarctx, "loading_mode", expand=True)
            column = point_loading_body.column(align=True)
            if(lidarctx.loading_mode == "link_list"):
                column.operator(operator="lidarhd.openbrowser", icon="URL")
                column.operator(operator="lidarhd.openlist")
                # if(len(lidarctx.link_list) > 0):
                #     for item in lidarctx.link_list:
                #         layout.prop(item, "value", text="jsp")
                #     point_loading_body.operator(operator="my.test", text=f"Download {lidarctx.link_list_amount} tiles")
            if(lidarctx.loading_mode == "folder"):
                column.operator(operator="lidarhd.openfolder", icon="FILEBROWSER")
            # if tile_group3.test_tiles is None and len(lidarctx.link_list) > 0:
            #     point_loading_body.operator("lidarhd.createtilegroup", f"Load ")
            # point_loading_body.prop(lidarctx, "texture_resolution", text='Image Resolution: '+str(2**lidarctx.texture_resolution))
            point_loading_body.prop(lidarctx, "target_point_ram_usage")
            if (lidarctx.target_point_ram_usage+2)*1000000000 > psutil.virtual_memory().total:
                point_loading_body.label(text="Expect extreme slowdowns", icon="WARNING_LARGE")
            if tile_group3.test_tiles is not None:
                if tile_group3.test_tiles.target_ram_usage != lidarctx.target_point_ram_usage:
                    column = point_loading_body.column(align=True)
                    column.label(text="Ram usage changes need reloading.")
                    column.operator("lidarhd.createtilegroup", text="Reload", icon="FILE_REFRESH")
                # if len(tile_group3.test_tiles.pools[-1]) == 0:
                #     point_loading_body.label(text="RAM target too small for top LOD", icon="WARNING_LARGE")
                    
        storage_header, storage_body = layout.panel("storage", default_closed=True)
        storage_header.label(text="Storage")
        
        if storage_body:
            storage_body.operator("lidarhd.opencachefolder", icon="FILE_FOLDER")
        
        loading_header, loading_body = layout.panel("loading", default_closed=True)
        loading_header.label(text="Performance")
        
        if(loading_body):
            loading_body.prop(lidarctx, "lod_multiplier")
            advanced_header, advanced_body = loading_body.panel("advanced", default_closed=True)
            advanced_header.label(text="Advanced")
            if(advanced_body):
                column = advanced_body.column(align=True)
                column.label(text="Image resolutions per level:")
                for i in range(len(lidarctx.texture_resolutions)):
                    column.prop(lidarctx, "texture_resolutions", index=i, text=f"Level {i}")
                
                column = advanced_body.column(align=True)
                column.label(text="Minimum radius per level:")
                for i in range(len(lidarctx.minimum_radii)):
                    column.prop(lidarctx, "minimum_radii", index=i, text=f"Level {i}")
            
        position_header, position_body = layout.panel("cloud_options", default_closed=True)
        position_header.label(text="Position")

        if(position_body):
            position_body.prop(lidarctx, "point_cloud_offset")

        display_header, display_body = layout.panel("display", default_closed=True)
        display_header.label(text="Display")

        if(display_body):
            display_body.prop(lidarctx, "point_scaling")
            display_body.prop(lidarctx, "point_size")
            display_body.prop(lidarctx, "display_mode")
            visibility_box = display_body.box()
            for item in lidarctx.class_visibility:
                row = visibility_box.row(align=True)
                eye_icon = "HIDE_OFF" if item.visible else "HIDE_ON"
                op = row.operator(
                    "lidarhd.toggle_class_visibility",
                    text="",
                    icon=eye_icon,
                    emboss=False,
                )
                op.class_name = item.name
                row.label(text=item.name)
                
        layout.separator()
        if view_manager.trusted_area == context.area and tile_group3.test_tiles is not None:
            layout.operator("lidarhd.toblenderpointcloud")
            layout.separator()
        if tile_group3.test_tiles is not None:
            layout.prop(lidarctx, "loading_locked", text="Lock Tile Loading", icon="LOCKED")
            eye_icon = "HIDE_OFF" if lidarctx.visible else "HIDE_ON"
            vis_text = "Hide Point Cloud" if lidarctx.visible else "Show Point Cloud"
            layout.operator("lidarhd.toggle_visibility", text=bpy.app.translations.pgettext(vis_text), icon=eye_icon)
            layout.operator("lidarhd.deletetilegroup", text=bpy.app.translations.pgettext("Unload Point Cloud"), icon="PANEL_CLOSE")


        # info_box = layout.box()
        # info_box.label(text="Point cloud info", icon="INFO_LARGE")
        # info_box.label(text="29 822 291 points")
        # info_box.label(text="521 MB in memory")


def register():
    bpy.utils.register_class(StringItem)
    bpy.utils.register_class(PointCloudClass)
    bpy.utils.register_class(LIDARHD_OT_open_cache_folder)
    bpy.utils.register_class(LIDARHD_OT_toggle_class_visibility)
    bpy.utils.register_class(LIDARHD_OT_toggle_all_visibility)
    bpy.utils.register_class(LIDARHD_OT_create_tile_group)
    bpy.utils.register_class(LIDARHD_OT_warn_before_create)
    bpy.utils.register_class(LIDARHD_OT_delete_tile_group)
    bpy.utils.register_class(LIDARHD_OT_to_blender_point_cloud)
    bpy.utils.register_class(LiDAR_HD_Tool)
    bpy.utils.register_class(LIDARHD_OT_open_lidarhd_browser)
    bpy.utils.register_class(LIDARHD_OT_test)
    bpy.utils.register_class(LIDARHD_OT_pick_file)
    bpy.utils.register_class(LIDARHD_OT_pick_folder)
    bpy.utils.register_class(LIDARHD_OT_set_trusted_area)
    bpy.utils.register_class(LIDARHD_PT_sidebar)
    bpy.types.Scene.lidar_hd = bpy.props.PointerProperty(type=LiDAR_HD_Tool)
    bpy.app.handlers.load_post.append(populate_default_values)

def unregister():
    bpy.utils.unregister_class(StringItem)
    bpy.utils.unregister_class(PointCloudClass)
    bpy.utils.unregister_class(LIDARHD_OT_open_cache_folder)
    bpy.utils.unregister_class(LIDARHD_OT_toggle_class_visibility)
    bpy.utils.unregister_class(LIDARHD_OT_toggle_all_visibility)
    bpy.utils.unregister_class(LIDARHD_OT_create_tile_group)
    bpy.utils.unregister_class(LIDARHD_OT_warn_before_create)
    bpy.utils.unregister_class(LIDARHD_OT_delete_tile_group)
    bpy.utils.unregister_class(LIDARHD_OT_to_blender_point_cloud)
    bpy.utils.unregister_class(LiDAR_HD_Tool)
    bpy.utils.unregister_class(LIDARHD_OT_open_lidarhd_browser)
    bpy.utils.unregister_class(LIDARHD_OT_test)
    bpy.utils.unregister_class(LIDARHD_OT_pick_file)
    bpy.utils.unregister_class(LIDARHD_OT_pick_folder)
    bpy.utils.unregister_class(LIDARHD_OT_set_trusted_area)
    bpy.utils.unregister_class(LIDARHD_PT_sidebar)
    del bpy.types.Scene.lidar_hd
    bpy.app.handlers.load_post.remove(populate_default_values)