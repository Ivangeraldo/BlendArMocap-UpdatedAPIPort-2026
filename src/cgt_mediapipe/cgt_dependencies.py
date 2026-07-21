import os
import sys

import importlib
import platform

import subprocess
import logging

import bpy
import warnings
import site

from typing import Tuple
from collections import namedtuple
from pathlib import Path


Dependency = namedtuple("Dependency", ["module", "name", "pkg", "args"])


# region get internal python paths
def get_python_exe():
    """ Get path of blender internal python executable. """
    if bpy.app.version < (2, 91, 0):
        executable = bpy.app.binary_path_python
    else:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            executable = sys.executable

    # some version the path points to the binary path instead of the py executable
    if executable == bpy.app.binary_path or executable == None:
        py_path = Path(sys.prefix) / "bin"
        py_exec = next(py_path.glob("python*"))  # first file that starts with "python" in "bin" dir
        executable = str(py_exec)

    print(f"{bpy.app.version} Python Executable: {executable}.")
    return executable


def get_site_packages_path():
    """ Get path of blender internal site packages. """
    # get path to site packages using site
    site_package_path = site.getsitepackages()
    if isinstance(site_package_path, str):
        if Path(site_package_path).is_dir():
            return site_package_path
    elif isinstance(site_package_path, list):
        if len(site_package_path) >= 1 and (Path(site_package_path[0]).is_dir()):
            return site.getsitepackages()[0]

    # recv search for site packages
    if bpy.app.version >= (3, 0, 0):
        python_directory = Path(bpy.utils.system_resource('PYTHON'))
        site_package_path = [path for path in python_directory.rglob('site-packages')]
        if len(site_package_path) >= 1:
            return str(site_package_path[0])

    # return script path and hope for the best
    return bpy.utils.script_paths()


def clear_user_site():
    """ Clear python site packages to avoid user site packages. """
    # Depreciated: --target flag seems to deliver better results
    # Disallow pip from checking the user site-package
    environ_copy = dict(os.environ)
    environ_copy["PYTHONNOUSERSITE"] = "-1"
    return environ_copy
# endregion


# region commands
def run_command(*args: str, module: str) -> bool:
    """ Run command. Return True on successful execution. """
    cmds = [cmd for cmd in args if cmd is not None]
    cmd = [python_binary, "-m", module, *cmds]
    print(*cmd, sep=' ')
    # environ_copy = clear_user_site()
    return subprocess.call(cmd) == 0  # , env=environ_copy) == 0


def install_dependency(self: bpy.types.Operator, dependency: Dependency, local_user: bool) -> bool:
    """ Install a dependency using pip. """
    import socket

    # expect socket to time out due to bad connection or vpn usage
    try:
        sub_cmds = []
        if dependency.args is not None:
            sub_cmds = [cmd for cmd in dependency.args if isinstance(cmd, str)]

        if local_user:
            successfully_installed = run_command('install', dependency.module, '--user', *sub_cmds, module='pip')
        else:
            successfully_installed = run_command('install', dependency.module, '--target', site_packages, *sub_cmds, module='pip')

        if successfully_installed:
            import_module(dependency)
            return True
        else:
            self.report({'ERROR'}, f"Installation of {dependency.pkg} failed. Check system console output.")
            return False

    except socket.timeout:
        self.report({'ERROR'}, "Ensure you are connected to the internet and no VPN is running.")
        return False
# endregion


# region delete
def uninstall_dependency(self: bpy.types.Operator, dependency: Dependency) -> bool:
    """ Moves dependency to custom trash location to remove it on start up.
        Removing dependencies via pip leaves random artifacts.
        https://developer.blender.org/T7783 """
    # run_command('uninstall', dependency.pkg, '-y', module='pip')
    import re
    logging.info(f"Moving package to custom trash folder for removal upon restart. {dependency}")

    def canonize_path(name):
        # pip/src/pip/_vendor/packaging/utils.py
        _canonicalize_regex = re.compile(r"[-_.]+")
        value = _canonicalize_regex.sub("-", name).lower()
        return value

    # find package dist
    import importlib.metadata as importlib_metadata
    try:
        dist_info = importlib_metadata.distribution(dependency.pkg)
    except importlib_metadata.PackageNotFoundError:
        return False

    # path to dist info
    location = dist_info.locate_file("")
    if location is None:
        logging.warning(f"No se pudo ubicar dist-info de {dependency.pkg} (metadata incompleta); "
                         f"se omite ese paso de la limpieza.")
        dist_location = None
    else:
        dist_location = Path(str(location))
    # dist_info.metadata["Name"] puede devolver None (ver nota en get_package_info);
    # usamos dependency.pkg como fuente confiable en su lugar.
    dist_name = dist_info.metadata["Name"] or dependency.pkg
    if dist_location is not None:
        tmp_dist_path = dist_location / f"{dist_name}-{dist_info.version}.dist-info"
        canonize_dist = canonize_path(str(tmp_dist_path))
    else:
        canonize_dist = None

    # path to package
    other_package_path = None
    try:
        package_init = importlib.import_module(dependency.name).__file__
        package_path = Path(package_init).parent

        # don't delete site packages by accident
        if str(package_path.stem).startswith('site'):
            package_path = Path(package_init)

        # customs as weird packaging
        if dependency.pkg == 'protobuf':
            package_path = package_path.parent
        if dependency.pkg == 'attrs':
            other_package_init = importlib.import_module('attr').__file__
            other_package_path = Path(other_package_init).parent

    except Exception as e:
        # trying to create name based on module name (might fail)
        package_path = Path(site_packages) / dependency.name

    # compare to dists in site packages
    dist_path = None
    for dist in Path(site_packages).iterdir():
        tmp_canonize_dist = canonize_path(str(dist))
        if canonize_dist == tmp_canonize_dist:
            dist_path = dist
            break

    # check if .pth file in site packages
    pth_file = None
    for path in Path(site_packages).iterdir():
        if not path.suffix == '.pth':
            continue
        if canonize_path(path.stem).startswith(canonize_path(dependency.pkg)):
            pth_file = path

    # path to custom trash
    file = Path(__file__).parent.parent
    trash = file / "trash"
    trash.mkdir(parents=True, exist_ok=True)

    # move directories to custom trash folder to delete on restart
    import shutil
    successfully_moved = []
    for r_path in [dist_path, package_path, pth_file, other_package_path]:
        if r_path is None:
            continue
        shutil.move(str(r_path), str(trash))
        logging.info(f"Successfully moved package for further removal:\nFrom: {str(r_path)}\nTo: {str(trash)}")
        successfully_moved.append(True)
    # return if moving dirs was successful
    return all(successfully_moved)


def remove_dependency_remains():
    """ Removing dependencies via pip leaves random artifacts.
        Deleting dependency remains in custom trash.
        https://developer.blender.org/T7783 """
    m_dir = Path(__file__).parent.parent
    trash = m_dir / "trash"
    trash.mkdir(parents=True, exist_ok=True)
    import shutil
    for file in trash.iterdir():
        try:
            if file.is_dir():
                shutil.rmtree(file)
            else:
                file.unlink()

        except (PermissionError, NotADirectoryError) as e:
            print(e)
            print("\n\nRestart Blender to remove files")
# endregion


# region pip
def ensure_pip(self: bpy.types.Operator) -> bool:
    """ Runs ensure pip bootstrap if pip is not installed. Returns True if pip is available. """
    if is_installed(Dependency("pip", "pip", "pip", "pip")):
        return True

    logging.info(f"Attempt to install pip.")
    try:
        # https://github.com/robertguetzkow/blender-python-examples/blob/master/add-ons/install-dependencies/install-dependencies.py
        import ensurepip
        ensurepip.bootstrap()
        os.environ.pop("PIP_REQ_TRACKER", None)
        return True

    except Exception as e:
        logging.warning(f"Bootstrap failed: {e}\n\nManual call ensure pip.")
        if run_command('--default-pip', module='ensurepip'):
            return True

    self.report({'ERROR'}, "Installation of pip failed.")
    return False


def update_pip(self: bpy.types.Operator) -> bool:
    """ Updates pip - depreciated. """
    # https://github.com/pypa/pip/issues/5599
    if run_command("install", "--upgrade", "pip", module='pip'):
        return True

    self.report({'ERROR'}, "Update failed")
    return False
# endregion


# region package import and info
def import_module(dependency: Dependency) -> bool:
    """ Attempt to import module and assign it to the globals dictionary.
        May only be used with properly installed dependencies. """
    if not is_installed(dependency):
        return False

    try:
        # reload dependency if it's in globals
        if dependency.name in globals():
            importlib.reload(globals()[dependency.name])
            return True

        # import dependency and add it to globals
        module = importlib.import_module(dependency.name)
        globals()[dependency.name] = module
        return True

    except ModuleNotFoundError as e:
        logging.error(e)
        return False


def get_package_info(dependency: Dependency) -> Tuple[str, str]:
    """ Get info of installed package in Blender.

    NOTA (Blender 4.5): se usaba `pkg_resources` (parte de setuptools) para esto,
    pero el Python embebido de Blender ya no trae setuptools instalado por
    defecto, así que `import pkg_resources` fallaba con ModuleNotFoundError —
    y como fallaba DENTRO del try, la referencia a `pkg_resources.DistributionNotFound`
    en el except de abajo tronaba con UnboundLocalError (¡incluso al fallar
    de la forma que se esperaba manejar!). `importlib.metadata` es stdlib
    puro (desde Python 3.8) y no depende de setuptools en absoluto. """
    import importlib.metadata as importlib_metadata

    try:
        dist_info = importlib_metadata.distribution(dependency.pkg)
        version = dist_info.version
        location = dist_info.locate_file("")
        # dist_info.metadata["Name"] a veces devuelve None (quirk conocido de
        # importlib.metadata, sobre todo en Windows) — usamos el nombre de
        # paquete que ya conocemos (dependency.pkg) en vez de confiar en eso.
        # `location` también puede venir None en instalaciones con metadata
        # incompleta/corrupta (típico tras varias reinstalaciones manuales) —
        # sin este chequeo, "Path(None) / algo" tronaba con TypeError y
        # rompía el registro de TODO el addon, porque este código corre al
        # importar el módulo.
        if location is None:
            return version, None
        path = str(Path(str(location)) / dependency.pkg)
        return version, path
    except importlib_metadata.PackageNotFoundError as e:
        logging.warning(e)
        return None, None
    except Exception as e:
        logging.warning(f"get_package_info fallo inesperado para {dependency.pkg}: {e}")
        return None, None


def is_installed(dependency: Dependency) -> bool:
    """ Checks if dependency is installed. """
    try:
        spec = importlib.util.find_spec(dependency.name)
    except (ModuleNotFoundError, ValueError, AttributeError):
        return False

    # only accept it as valid if there is a source file for the module - not bytecode only.
    if issubclass(type(spec), importlib.machinery.ModuleSpec):
        return True
    return False
# endregion


if sys.platform == 'darwin' and platform.processor() == 'arm':
    required_dependencies = [
        Dependency(module="mediapipe==0.10.33", name="mediapipe", pkg="mediapipe", args=None),
    ]

elif sys.platform == 'win32':
    required_dependencies = [
        Dependency(module="mediapipe==0.10.33", name="mediapipe", pkg="mediapipe", args=None),
    ]

elif sys.platform == 'linux':
    required_dependencies = [
        Dependency(module="mediapipe==0.10.33", name="mediapipe", pkg="mediapipe", args=None),
    ]

# legacy mac
else:
    required_dependencies = [
        Dependency(module="mediapipe==0.10.33", name="mediapipe", pkg="mediapipe", args=None),
    ]

# NOTA (port a mediapipe moderno / Blender 4.5, Python 3.11):
# El addon original pineaba versiones viejas de mediapipe (0.8.x-0.10.11) y de
# protobuf/opencv por separado, porque la API vieja (mediapipe.solutions.*)
# era frágil con esas dependencias. La Tasks API moderna (PoseLandmarker/
# HandLandmarker/FaceLandmarker, usada ahora en cgt_mp_core/*) viene en
# wheels de mediapipe recientes que resuelven sus propias dependencias
# (protobuf, etc.) sin necesitar pines manuales. Los modelos .task (que la
# Tasks API SÍ necesita descargar aparte, a diferencia de la vieja API que
# los traía embebidos) se descargan solos la primera vez que se usa un
# detector — ver cgt_mp_core/mp_models.py.
#
# IMPORTANTE: ya NO se instala "opencv-python" como dependencia separada.
# mediapipe declara "opencv-contrib-python" como su propia dependencia y lo
# instala solo. Tener las dos variantes de opencv instaladas a la vez
# (opencv-python + opencv-contrib-python) corrompe el paquete "cv2" en
# Windows -ambas comparten el mismo nombre de import ("cv2") y pip no sabe
# que son mutuamente excluyentes-, produciendo el error
# "module 'cv2' has no attribute 'VideoCapture'" incluso con una instalación
# fresca. La versión de mediapipe queda fijada (==0.10.33) en vez de "la
# última disponible" para que la instalación sea reproducible.


from ..cgt_core.cgt_utils import cgt_user_prefs

# TODO ESTE BLOQUE CORRE AL IMPORTAR EL MÓDULO (o sea, durante el registro del
# addon). Antes, si CUALQUIER paso fallaba (p.ej. metadata de un paquete
# corrupta tras varias reinstalaciones manuales), la excepción tumbaba el
# registro de TODO el addon con un RuntimeError genérico y sin traceback útil.
# Ahora cada paso está blindado con valores por defecto seguros.
try:
    stored_prefs = cgt_user_prefs.get_prefs(local_user=False)
except Exception as e:
    logging.warning(f"No se pudieron leer las preferencias guardadas: {e}")
    stored_prefs = {}

try:
    user_site = site.getusersitepackages()
    if user_site not in sys.path and stored_prefs.get("local_user", False):
        logging.info("Adding user site packages.")
        sys.path.append(user_site)
except Exception as e:
    logging.warning(f"No se pudo resolver user site-packages: {e}")

try:
    site_packages = get_site_packages_path()
except Exception as e:
    logging.warning(f"No se pudo resolver site-packages: {e}")
    site_packages = None

try:
    python_binary = get_python_exe()
except Exception as e:
    logging.warning(f"No se pudo resolver el ejecutable de Python: {e}")
    python_binary = sys.executable

print(site_packages, python_binary)
# remove_dependency_remains()

for dep in required_dependencies:
    try:
        info = get_package_info(dep)
        logging.debug(str(info))
    except Exception as e:
        logging.warning(f"get_package_info falló para {dep.pkg}, se ignora: {e}")

try:
    dependencies_installed = [is_installed(dependency) for dependency in required_dependencies]
except Exception as e:
    logging.warning(f"No se pudo verificar dependencias instaladas: {e}")
    dependencies_installed = [False for _ in required_dependencies]
