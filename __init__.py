'''
Copyright (C) Denys Hsu, cgtinker, cgtinker.com, hello@cgtinker.com

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
'''


bl_info = {
    "name":        "BlendArMocap NX",
    "description": "Fork/port de BlendArMocap (cgtinker) a la MediaPipe Tasks API moderna, "
                    "para Blender 4.2+ (probado en 4.5). Mediapipe and Freemocap animation "
                    "transfer implementation.",
    "author":      "cgtinker (autor original) — port a Tasks API: Ivan / Claude",
    "version":     (1, 7, 3),
    "blender":     (4, 2, 0),
    "location":    "3D View > Tool",
    "doc_url":    "https://cgtinker.github.io/BlendArMocap/",
    "tracker_url": "https://github.com/cgtinker/BlendArMocap/issues",
    "support":     "COMMUNITY",
    "category":    "Animation"
}


def reload_modules():
    from .src import cgt_imports
    cgt_imports.manage_imports()


def register():
    from .src import cgt_registration
    cgt_registration.register()


def unregister():
    from .src import cgt_registration
    cgt_registration.unregister()


if __name__ == '__main__':
    from src.cgt_core.cgt_utils import cgt_logging
    # cgt_logging.init('')
    register()
