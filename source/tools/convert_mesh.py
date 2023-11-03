# Copyright (c) 2022-2023, The ORBIT Project Developers.
# All rights reserved.
#
# SPDX-License-Identifier: BSD-3-Clause

"""
Utility to convert a OBJ/STL/FBX into USD format.

The OBJ file format is a simple data-format that represents 3D geometry alone — namely, the position
of each vertex, the UV position of each texture coordinate vertex, vertex normals, and the faces that
make each polygon defined as a list of vertices, and texture vertices.

An STL file describes a raw, unstructured triangulated surface by the unit normal and vertices (ordered
by the right-hand rule) of the triangles using a three-dimensional Cartesian coordinate system.

FBX files are a type of 3D model file created using the Autodesk FBX software. They can be designed and
modified in various modeling applications, such as Maya, 3ds Max, and Blender. Moreover, FBX files typically
contain mesh, material, texture, and skeletal animation data.
Link: https://www.autodesk.com/products/fbx/overview


This script uses the asset converter extension from Isaac Sim (``omni.kit.asset_converter``) to convert a
OBJ/STL/FBX asset into USD format. It is designed as a convenience script for command-line use.


positional arguments:
  input               The path to the input mesh (.OBJ/.STL/.FBX) file.
  output              The path to store the USD file.

optional arguments:
  -h, --help                    Show this help message and exit
  --headless                    Force display off at all times. (default: False)
  --make_instanceable,       -i Make the asset instanceable for efficient cloning. (default: False)
  --force_usd_conversion     -f Convert the input file to USD even if the output file already exists.
  --collision_approximation  -c The method used for approximating collision mesh. Defaults to convexDecomposition. Set to \"none\" "
                                to not add a collision mesh to the converted mesh.
  --mass                     -m The mass (in kg) to assign to the converted asset.

"""

"""Launch Isaac Sim Simulator first."""


import argparse
import contextlib

from omni.isaac.orbit.app import AppLauncher

# add argparse arguments
parser = argparse.ArgumentParser(description="Utility to convert a mesh file into USD format.")
parser.add_argument("input", type=str, help="The path to the input mesh file.")
parser.add_argument("output", type=str, help="The path to store the USD file.")
parser.add_argument("--headless", action="store_true", default=False, help="Force display off at all times.")
parser.add_argument(
    "--make_instanceable",
    "-i",
    action="store_true",
    default=False,
    help="Make the asset instanceable for efficient cloning.",
)
parser.add_argument(
    "--force_usd_conversion",
    "-f",
    action="store_true",
    default=False,
    help="Convert the input file to USD even if the output file already exists.",
)
parser.add_argument(
    "--collision_approximation",
    "-c",
    type=str,
    default="convexDecomposition",
    choices=["convexDecomposition", "convexHull", "none"],
    help=(
        'The method used for approximating collision mesh. Set to "none" '
        "to not add a collision mesh to the converted mesh."
    ),
)
parser.add_argument(
    "--mass",
    "-m",
    type=float,
    default=None,
    help="The mass (in kg) to assign to the converted asset. If not provided, then no mass is added.",
)
args_cli = parser.parse_args()

# launch omniverse app
simulation_app = AppLauncher(headless=args_cli.headless).app


"""Rest everything follows."""

import os

import omni.isaac.core.utils.stage as stage_utils
import omni.kit.app

from omni.isaac.orbit.sim.converters import MeshConverter, MeshConverterCfg
from omni.isaac.orbit.sim.schemas import schemas_cfg
from omni.isaac.orbit.utils.assets import check_file_path
from omni.isaac.orbit.utils.dict import print_dict


def main():
    # check valid file path
    mesh_path = args_cli.input
    if not os.path.isabs(mesh_path):
        mesh_path = os.path.abspath(mesh_path)
    if not check_file_path(mesh_path):
        raise ValueError(f"Invalid mesh file path: {mesh_path}")

    # create destination path
    dest_path = args_cli.output
    if not os.path.isabs(dest_path):
        dest_path = os.path.abspath(dest_path)

    print(dest_path)
    print(os.path.dirname(dest_path))
    print(os.path.basename(dest_path))

    # Mass properties
    if args_cli.mass is not None:
        mass_props = schemas_cfg.MassPropertiesCfg(mass=args_cli.mass)
        rigid_props = schemas_cfg.RigidBodyPropertiesCfg()
    else:
        mass_props = None
        rigid_props = None

    # Collision properties
    collision_props = schemas_cfg.CollisionPropertiesCfg(collision_enabled=args_cli.collision_approximation != "none")

    # Create Mesh converter config
    mesh_converter_cfg = MeshConverterCfg(
        mass_props=mass_props,
        rigid_props=rigid_props,
        collision_props=collision_props,
        asset_path=mesh_path,
        force_usd_conversion=args_cli.force_usd_conversion,
        usd_dir=os.path.dirname(dest_path),
        usd_file_name=os.path.basename(dest_path),
        make_instanceable=args_cli.make_instanceable,
        collision_approximation=args_cli.collision_approximation,
    )

    # Print info
    print("-" * 80)
    print("-" * 80)
    print(f"Input Mesh file: {mesh_path}")
    print("Mesh importer config:")
    print_dict(mesh_converter_cfg.to_dict(), nesting=0)
    print("-" * 80)
    print("-" * 80)

    # Create Mesh converter and import the file
    mesh_converter = MeshConverter(mesh_converter_cfg)
    # print output
    print("Mesh importer output:")
    print(f"Generated USD file: {mesh_converter.usd_path}")
    print("-" * 80)
    print("-" * 80)

    # Simulate scene (if not headless)
    if not args_cli.headless:
        # Open the stage with USD
        stage_utils.open_stage(mesh_converter.usd_path)
        # Reinitialize the simulation
        app = omni.kit.app.get_app_interface()
        # Run simulation
        with contextlib.suppress(KeyboardInterrupt):
            while True:
                # perform step
                app.update()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback

        import carb

        carb.log_error(traceback.format_exc())
        carb.log_error(e)
    finally:
        simulation_app.close()
