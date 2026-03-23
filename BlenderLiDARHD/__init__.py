# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTIBILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

bl_info = {
    "name": "LiDAR HD Tool",
    "author": "Bastian Cataldi",
    "description": "Visualize and import IGN LiDAR HD point clouds.",
    "blender": (2, 80, 0),
    "version": (0, 0, 1),
    "location": "View3D > Sidebar > LiDAR HD",
    "warning": "",
    "category": "Generic",
}

# from . import auto_load
from . import interface
from . import tile_group2
from . import view_manager
from . import cache_manager
import bpy
from pathlib import Path


def create_cache_directories():
    Path(cache_manager.get_cache_tile_dir()).mkdir(exist_ok=True, parents=True)
    Path(cache_manager.get_cache_texture_dir()).mkdir(exist_ok=True, parents=True)
    print("created cache dirs")


class LidarHDToolPreferences(bpy.types.AddonPreferences):
    bl_idname = __name__

    cache_dir: bpy.props.StringProperty(
        name="Cache Folder",
        subtype='DIR_PATH',
        default=str(Path.home()/"Documents/LiDAR HD")
    )

    def draw(self, context):
        self.layout.prop(self, "cache_dir")


translation_dict = {
    "fr_FR": {
        ("Operator", "Reload Last Session"):                    "Recharger la dernière session",
        ("Operator", "Confirm"):                                "Confirmer",
        ("Operator", "Are you sure?"):                          "Êtes-vous sûr ?",
        ("Operator", "Nearest Tile to Blender Point Cloud"):    "Tuile → Nuage de Points Blender",
        ("Operator", "Open the Dowload Interface..."):          "Interface de Téléchargement",
        ("Operator", "Load a dalle.txt..."):                    "Charger un dalle.txt...",
        ("Operator", "Select a folder..."):                     "Choisir un dossier...",
        ("Operator", "Load tiles based on this view"):          "Charger les tuiles selon cette vue",
        ("Operator", "Open Cache Folder"):                      "Ouvrir le Dossier de Cache",

        ("*", "This view does not update the point cloud"):     "Cette vue ne charge pas les tuiles",
        ("*", "Point Loading"):                                 "Chargement des points",
        ("*", "List of links"):                                 "Liste de liens",
        ("*", "Folder"):                                        "Dossier",
        ("*", "Storage"):                                       "Stockage",
        ("*", "Performance"):                                   "Performances",
        ("*", "Advanced"):                                      "Avancé",
        ("*", "Image resolutions per level:"):                  "Résolutions d'image par niveau :",
        ("*", "Minimum radius per level:"):                     "Rayon minimum par niveau :",
        ("*", "Position"):                                      "Position",
        ("*", "Display"):                                       "Affichage",
        ("*", "Point Size"):                                    "Taille des points",
        ("lidarhd", "Scaling"):                                 "Taille",
        ("lidarhd", "Perspective"):                             "Perspective",
        ("lidarhd", "Constant"):                                "Constante",
        ("*", "Scale points with camera distance."):      "La taille des points est régie par la perspective.",
        ("*", "Make every point the same size on screen regardless of distance."): "Tous les points ont la même taille à l'écran, peu importe leur distance.",
        ("*", "Color"):                                         "Couleur",
        ("*", "Projected Aerial Photos"):                       "Photos aériennes projetées",
        ("*", "BD ORTHO aerial photography vertically projected."): "Photographie aérienne BD ORTHO projetée verticalement.",
        ("*", "LiDAR Intensity"):                               "Intensité LiDAR",
        ("*", "Return strength of the laser pulse that generated the point."): "Intensité du signal retour ayant généré le point.",
        ("*", "Point Class"):                                   "Classe du point",
        ("*", "Class of the point."):                           "Classe du point.",
        ("*", "Class x Intensity"):                             "Classe x Intensité",
        ("*", "Intensity of the point tinted depending on its classification."): "Intensité du point teintée selon sa classe.",
        ("*", "Lock Tile Loading"):                             "Verr. le Chargement des Tuiles",
        ("*", "Hide Point Cloud"):                              "Cacher le Nuage de Points",
        ("*", "Show Point Cloud"):                              "Montrer le Nuage de Points",
        ("*", "Unload Point Cloud"):                            "Décharger le nuage de points",
        ("*", "Ram usage changes need reloading."):             "Rechargement nécéssaire.",
        ("*", "Reload"):                                        "Recharger",
        ("*", "RAM target too small for top LOD"):              "Cible RAM insuff. pour LOD maxi",
        ("*", "Expect extreme slowdowns"):                      "Ralentissement extrême attendu",
        ("*", "Target RAM usage (GB):"):                        "Utilisation RAM cible (Go) :",
        ("*", "Drawing Distance"):                              "Distance d'Affichage",
        ("*", "Offset"):                                        "Décalage",

        ("*", "Blender will download these tiles into the cache folder:"): "Blender va télécharger ces tuiles dans le dossier de cache :",
        ("*", "This operation might freeze Blender for a few minutes."): "Cette opération peut bloquer Blender pendant quelques minutes.",
        ("*", "Are you sure to go forward?"):                   "Êtes-vous sûr de vouloir continuer ?",

        ("*", "Converts the tile closest to the viewport's pivot point into Blender's native point cloud object."): 
            "Convertit la tuile la plus proche du pivot de la vue en nuage de points natif Blender.",
        ("*", "Opens the official Downloading Interface in a new browser tab."):
            "Ouvre l'interface de téléchargement officielle de l'IGN dans un nouvel onglet de votre navigateur.",
        ("*", "Point to the dalle.txt file you obtained from the LiDAR HD Downloading Interface"):
            "Sélectionner le fichier dalle.txt obtenu depuis l'interface de téléchargement LiDAR HD.",
        ("*", "Point to a folder containing already downloaded COPC LAZ files."):
            "Sélectionner un dossier contenant des fichiers COPC LAZ déjà téléchargés.",
            
        ("*", "Load point clouds from a list of download links obtainable at: https://cartes.gouv.fr/telechargement/IGNF_NUAGES-DE-POINTS-LIDAR-HD"):
            "Charger des nuage de points depuis une liste obtenue sur https://cartes.gouv.fr/telechargement/IGNF_NUAGES-DE-POINTS-LIDAR-HD",
        ("*", "Load point clouds from a folder on your computer."): "Charger des nuages de points depuis un dossier de votre ordinateur.",
        ("*", "The resolution of the aerial image loaded for every level. Avoid many different resolutions."):
            "La résolution de l'image aérienne chargée à chaque niveau de détail. Minimisez le nombre de résolutions différentes",
        ("*", "When a tile gets this close without being loaded at that level, point loading occurs."):
            "Le chargement de points est déclenché lorsqu'une tuile entre dans ce rayon mais n'est pas chargée à ce niveau de détail.",
        ("*", "Approximately how much memory is dedicated to storing point tiles."):
            "La quantité approximative de mémoire vive dédiée au stockage des tuiles.",
        ("*", "Scales the display radius of each LOD level. Higher values draw finer detail further from the camera. Does not affect tile loading or memory usage."):
            "Multiplie le rayon d'affichage de chaque niveau de détail. Des valeurs plus élevées affichent les détails fins à plus grande distance de la caméra. N'affecte pas le chargement des tuiles ni l'utilisation de la mémoire.",
        ("*", "Allow online access to download the missing tiles"): "L'accès en ligne doit être autorisé pour télécharger les tuiles manquantes",

        ("*", "Unclassified"):                                  "Non classé",
        ("*", "Ground"):                                        "Sol",
        ("*", "Low Vegetation"):                                "Végétation basse",
        ("*", "Medium Vegetation"):                             "Végétation moyenne",
        ("*", "High Vegetation"):                               "Végétation haute",
        ("*", "Building"):                                      "Bâtiment",
        ("*", "Water"):                                         "Eau",
        ("*", "Bridge Deck"):                                   "Tablier de pont",
        ("*", "Permanent Infrastructure"):                      "Sursol pérenne",
        ("*", "Virtual Points"):                                "Points virtuels",
        ("*", "Building-like features"):                        "Divers - bâtis",
    }
}


def register():
    bpy.utils.register_class(LidarHDToolPreferences)
    bpy.app.translations.register(__name__, translation_dict)
    create_cache_directories()
    interface.register()
    bpy.types.SpaceView3D.draw_handler_add(view_manager.update_camera_pivot_position, (), 'WINDOW', 'POST_VIEW')
    bpy.app.handlers.load_post.append(view_manager.set_trusted_rv3d_to_current)
    bpy.app.timers.register(interface.populate_default_values, first_interval=1.0)
 

def unregister():
    bpy.utils.unregister_class(LidarHDToolPreferences)
    bpy.app.translations.unregister(__name__)
    if tile_group2.test_tiles is not None:
        tile_group2.test_tiles.prepare_for_deletion()
        tile_group2.test_tiles = None
    interface.unregister()
