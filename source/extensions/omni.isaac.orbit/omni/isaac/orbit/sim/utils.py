# Copyright (c) 2022-2023, The ORBIT Project Developers.
# All rights reserved.
#
# SPDX-License-Identifier: BSD-3-Clause

"""Sub-module with USD-related utilities."""

from __future__ import annotations

import functools
import inspect
import re
from typing import TYPE_CHECKING, Any, Callable

import carb
import omni.isaac.core.utils.prims as prim_utils
import omni.isaac.core.utils.stage as stage_utils
import omni.kit.commands
from omni.isaac.cloner import Cloner
from omni.isaac.version import get_version
from pxr import PhysxSchema, Sdf, Semantics, Usd, UsdGeom, UsdPhysics, UsdShade

from omni.isaac.orbit.utils.string import to_camel_case

from . import schemas

if TYPE_CHECKING:
    from .spawners.spawner_cfg import SpawnerCfg

"""
Attribute - Setters.
"""


def safe_set_attribute_on_usd_schema(schema_api: Usd.APISchemaBase, name: str, value: Any, camel_case: bool):
    """Set the value of an attribute on its USD schema if it exists.

    A USD API schema serves as an interface or API for authoring and extracting a set of attributes.
    They typically derive from the :class:`pxr.Usd.SchemaBase` class. This function checks if the
    attribute exists on the schema and sets the value of the attribute if it exists.

    Args:
        schema_api: The USD schema to set the attribute on.
        name: The name of the attribute.
        value: The value to set the attribute to.
        camel_case: Whether to convert the attribute name to camel case.

    Raises:
        TypeError: When the input attribute name does not exist on the provided schema API.
    """
    # if value is None, do nothing
    if value is None:
        return
    # convert attribute name to camel case
    if camel_case:
        attr_name = to_camel_case(name, to="CC")
    else:
        attr_name = name
    # retrieve the attribute
    # reference: https://openusd.org/dev/api/_usd__page__common_idioms.html#Usd_Create_Or_Get_Property
    attr = getattr(schema_api, f"Create{attr_name}Attr", None)
    # check if attribute exists
    if attr is not None:
        attr().Set(value)
    else:
        # think: do we ever need to create the attribute if it doesn't exist?
        #   currently, we are not doing this since the schemas are already created with some defaults.
        carb.log_error(f"Attribute '{attr_name}' does not exist on prim '{schema_api.GetPath()}'.")
        raise TypeError(f"Attribute '{attr_name}' does not exist on prim '{schema_api.GetPath()}'.")


def safe_set_attribute_on_usd_prim(prim: Usd.Prim, attr_name: str, value: Any, camel_case: bool):
    """Set the value of a attribute on its USD prim.

    The function creates a new attribute if it does not exist on the prim. This is because in some cases (such
    as with shaders), their attributes are not exposed as USD prim properties that can be altered. This function
    allows us to set the value of the attributes in these cases.

    Args:
        prim: The USD prim to set the attribute on.
        attr_name: The name of the attribute.
        value: The value to set the attribute to.
        camel_case: Whether to convert the attribute name to camel case.
    """
    # if value is None, do nothing
    if value is None:
        return
    # convert attribute name to camel case
    if camel_case:
        attr_name = to_camel_case(attr_name, to="cC")
    # resolve sdf type based on value
    if isinstance(value, bool):
        sdf_type = Sdf.ValueTypeNames.Bool
    elif isinstance(value, int):
        sdf_type = Sdf.ValueTypeNames.Int
    elif isinstance(value, float):
        sdf_type = Sdf.ValueTypeNames.Float
    elif isinstance(value, (tuple, list)) and len(value) == 3 and any(isinstance(v, float) for v in value):
        sdf_type = Sdf.ValueTypeNames.Float3
    elif isinstance(value, (tuple, list)) and len(value) == 2 and any(isinstance(v, float) for v in value):
        sdf_type = Sdf.ValueTypeNames.Float2
    else:
        raise NotImplementedError(
            f"Cannot set attribute '{attr_name}' with value '{value}'. Please modify the code to support this type."
        )
    # change property
    omni.kit.commands.execute(
        "ChangePropertyCommand",
        prop_path=Sdf.Path(f"{prim.GetPath()}.{attr_name}"),
        value=value,
        prev=None,
        type_to_create_if_not_exist=sdf_type,
        usd_context_name=prim.GetStage(),
    )


"""
Decorators.
"""


def apply_nested(func: Callable) -> Callable:
    """Decorator to apply a function to all prims under a specified prim-path.

    The function iterates over the provided prim path and all its children to apply input function
    to all prims under the specified prim path.

    If the function succeeds to apply to a prim, it will not look at the children of that prim.
    This is based on the physics behavior that nested schemas are not allowed. For example, a parent prim
    and its child prim cannot both have a rigid-body schema applied on them, or it is not possible to
    have nested articulations.

    While traversing the prims under the specified prim path, the function will throw a warning if it
    does not succeed to apply the function to any prim. This is because the user may have intended to
    apply the function to a prim that does not have valid attributes, or the prim may be an instanced prim.

    Args:
        func: The function to apply to all prims under a specified prim-path. The function
            must take the prim-path and other arguments. It should return a boolean indicating whether
            the function succeeded or not.

    Returns:
        The wrapped function that applies the function to all prims under a specified prim-path.

    Raises:
        ValueError: If the prim-path does not exist on the stage.
    """

    @functools.wraps(func)
    def wrapper(prim_path: str, *args, **kwargs):
        # map args and kwargs to function signature so we can get the stage
        # note: we do this to check if stage is given in arg or kwarg
        sig = inspect.signature(func)
        bound_args = sig.bind(prim_path, *args, **kwargs)
        # get current stage
        stage = bound_args.arguments.get("stage")
        if stage is None:
            stage = stage_utils.get_current_stage()
        # get USD prim
        prim: Usd.Prim = stage.GetPrimAtPath(prim_path)
        # check if prim is valid
        if not prim.IsValid():
            raise ValueError(f"Prim at path '{prim_path}' is not valid.")
        # add iterable to check if property was applied on any of the prims
        count_success = 0
        instanced_prim_paths = []
        # iterate over all prims under prim-path
        all_prims = [prim]
        while len(all_prims) > 0:
            # get current prim
            child_prim = all_prims.pop(0)
            child_prim_path = child_prim.GetPath().pathString  # type: ignore
            # check if prim is a prototype
            if child_prim.IsInstance():
                instanced_prim_paths.append(child_prim_path)
                continue
            # set properties
            success = func(child_prim_path, *args, **kwargs)
            # if successful, do not look at children
            # this is based on the physics behavior that nested schemas are not allowed
            if not success:
                all_prims += child_prim.GetChildren()
            else:
                count_success += 1
        # check if we were successful in applying the function to any prim
        if count_success == 0:
            carb.log_warn(
                f"Could not perform '{func.__name__}' on any prims under: '{prim_path}'."
                " This might be because of the following reasons:"
                "\n\t(1) The desired attribute does not exist on any of the prims."
                "\n\t(2) The desired attribute exists on an instanced prim."
                f"\n\t\tDiscovered list of instanced prim paths: {instanced_prim_paths}"
            )

    return wrapper


def clone(func: Callable) -> Callable:
    """Decorator for cloning a prim based on matching prim paths of the prim's parent.

    The decorator checks if the parent prim path matches any prim paths in the stage. If so, it clones the
    spawned prim at each matching prim path. For example, if the input prim path is: ``/World/Table_[0-9]/Bottle``,
    the decorator will clone the prim at each matching prim path of the parent prim: ``/World/Table_0/Bottle``,
    ``/World/Table_1/Bottle``, etc.

    Note:
        For matching prim paths, the decorator assumes that valid prims exist for all matching prim paths.
        In case no matching prim paths are found, the decorator raises a ``RuntimeError``.

    Args:
        func: The function to decorate.

    Returns:
        The decorated function that spawns the prim and clones it at each matching prim path.
        It returns the spawned source prim, i.e., the first prim in the list of matching prim paths.
    """

    @functools.wraps(func)
    def wrapper(prim_path: str, cfg: SpawnerCfg, *args, **kwargs):
        # resolve: {SPAWN_NS}/AssetName
        # note: this assumes that the spawn namespace already exists in the stage
        root_path, asset_path = prim_path.rsplit("/", 1)
        # check if input is a regex expression
        # note: a valid prim path can only contain alphanumeric characters, underscores, and forward slashes
        is_regex_expression = re.match(r"^[a-zA-Z0-9/_]+$", root_path) is None

        # resolve matching prims for source prim path expression
        if is_regex_expression and root_path != "":
            source_prim_paths = prim_utils.find_matching_prim_paths(root_path)
            # if no matching prims are found, raise an error
            if len(source_prim_paths) == 0:
                raise RuntimeError(
                    f"Unable to find source prim path: '{root_path}'. Please create the prim before spawning."
                )
        else:
            source_prim_paths = [root_path]

        # resolve prim paths for spawning and cloning
        prim_paths = [f"{source_prim_path}/{asset_path}" for source_prim_path in source_prim_paths]
        # spawn single instance
        prim = func(prim_paths[0], cfg, *args, **kwargs)
        # set the prim visibility
        if hasattr(cfg, "visible"):
            prim_utils.set_prim_visibility(prim, cfg.visible)
        # set the semantic annotations
        if hasattr(cfg, "semantic_tags") and cfg.semantic_tags is not None:
            # note: taken from replicator scripts.utils.utils.py
            for semantic_type, semantic_value in cfg.semantic_tags:
                # deal with spaces by replacing them with underscores
                semantic_type_sanitized = semantic_type.replace(" ", "_")
                semantic_value_sanitized = semantic_value.replace(" ", "_")
                # set the semantic API for the instance
                instance_name = f"{semantic_type_sanitized}_{semantic_value_sanitized}"
                sem = Semantics.SemanticsAPI.Apply(prim, instance_name)
                # create semantic type and data attributes
                sem.CreateSemanticTypeAttr()
                sem.CreateSemanticDataAttr()
                sem.GetSemanticTypeAttr().Set(semantic_type)
                sem.GetSemanticDataAttr().Set(semantic_value)
        # activate rigid body contact sensors
        if hasattr(cfg, "activate_contact_sensors"):
            activate_contact_sensors = cfg.activate_contact_sensors
            if isinstance(activate_contact_sensors, str):
                activate_paths = prim_utils.find_matching_prim_paths(f"{prim_paths[0]}/{activate_contact_sensors}")
            elif isinstance(activate_contact_sensors, bool):
                activate_paths = [prim_paths[0]] if activate_contact_sensors else []
            else:
                raise ValueError
            for activate_path in activate_paths:
                schemas.activate_contact_sensors(activate_path, 1.)
        # clone asset using cloner API
        if len(prim_paths) > 1:
            cloner = Cloner()
            # clone the prim based on isaac-sim version
            isaac_major_version = int(get_version()[2])
            if isaac_major_version <= 2022:
                cloner.clone(prim_paths[0], prim_paths[1:], replicate_physics=False)
            else:
                cloner.clone(
                    prim_paths[0], prim_paths[1:], replicate_physics=False, copy_from_source=cfg.copy_from_source
                )
        # return the source prim
        return prim

    return wrapper


"""
Material bindings.
"""


@apply_nested
def bind_visual_material(
    prim_path: str, material_path: str, stage: Usd.Stage | None = None, stronger_than_descendants: bool = True
):
    """Bind a visual material to a prim.

    This function is a wrapper around the USD command `BindMaterialCommand`_.

    .. note::
        The function is decorated with :meth:`apply_nested` to allow applying the function to a prim path
        and all its descendants.

    .. _BindMaterialCommand: https://docs.omniverse.nvidia.com/kit/docs/omni.usd/latest/omni.usd.commands/omni.usd.commands.BindMaterialCommand.html

    Args:
        prim_path: The prim path where to apply the material.
        material_path: The prim path of the material to apply.
        stage: The stage where the prim and material exist.
            Defaults to None, in which case the current stage is used.
        stronger_than_descendants: Whether the material should override the material of its descendants.
            Defaults to True.

    Raises:
        ValueError: If the provided prim paths do not exist on stage.
    """
    # resolve stage
    if stage is None:
        stage = stage_utils.get_current_stage()
    # check if prim and material exists
    if not stage.GetPrimAtPath(prim_path).IsValid():
        raise ValueError(f"Target prim '{material_path}' does not exist.")
    if not stage.GetPrimAtPath(material_path).IsValid():
        raise ValueError(f"Visual material '{material_path}' does not exist.")

    # resolve token for weaker than descendants
    if stronger_than_descendants:
        binding_strength = "strongerThanDescendants"
    else:
        binding_strength = "weakerThanDescendants"
    # obtain material binding API
    # note: we prefer using the command here as it is more robust than the USD API
    success, _ = omni.kit.commands.execute(
        "BindMaterialCommand",
        prim_path=prim_path,
        material_path=material_path,
        strength=binding_strength,
        stage=stage,
    )
    # return success
    return success


@apply_nested
def bind_physics_material(
    prim_path: str, material_path: str, stage: Usd.Stage | None = None, stronger_than_descendants: bool = True
):
    """Bind a physics material to a prim.

    `Physics material`_ can be applied only to a prim with physics-enabled on them. This includes having
    collision APIs, or deformable body APIs, or being a particle system. In case the prim does not have
    any of these APIs, the function will not apply the material and return False.

    .. note::
        The function is decorated with :meth:`apply_nested` to allow applying the function to a prim path
        and all its descendants.

    .. _Physics material: https://docs.omniverse.nvidia.com/extensions/latest/ext_physics/simulation-control/physics-settings.html#physics-materials

    Args:
        prim_path: The prim path where to apply the material.
        material_path: The prim path of the material to apply.
        stage: The stage where the prim and material exist.
            Defaults to None, in which case the current stage is used.
        stronger_than_descendants: Whether the material should override the material of its descendants.
            Defaults to True.

    Raises:
        ValueError: If the provided prim paths do not exist on stage.
    """
    # resolve stage
    if stage is None:
        stage = stage_utils.get_current_stage()
    # check if prim and material exists
    if not stage.GetPrimAtPath(prim_path).IsValid():
        raise ValueError(f"Target prim '{material_path}' does not exist.")
    if not stage.GetPrimAtPath(material_path).IsValid():
        raise ValueError(f"Physics material '{material_path}' does not exist.")
    # get USD prim
    prim = stage.GetPrimAtPath(prim_path)
    # check if prim has collision applied on it
    has_physics_scene_api = prim.HasAPI(PhysxSchema.PhysxSceneAPI)
    has_collider = prim.HasAPI(UsdPhysics.CollisionAPI)
    has_deformable_body = prim.HasAPI(PhysxSchema.PhysxDeformableBodyAPI)
    has_particle_system = prim.IsA(PhysxSchema.PhysxParticleSystem)
    if not (has_physics_scene_api or has_collider or has_deformable_body or has_particle_system):
        carb.log_verbose(
            f"Cannot apply physics material '{material_path}' on prim '{prim_path}'. It is neither a"
            " PhysX scene, collider, a deformable body, nor a particle system."
        )
        return False

    # obtain material binding API
    if prim.HasAPI(UsdShade.MaterialBindingAPI):
        material_binding_api = UsdShade.MaterialBindingAPI(prim)
    else:
        material_binding_api = UsdShade.MaterialBindingAPI.Apply(prim)
    # obtain the material prim
    material = UsdShade.Material(stage.GetPrimAtPath(material_path))
    # resolve token for weaker than descendants
    if stronger_than_descendants:
        binding_strength = UsdShade.Tokens.strongerThanDescendants
    else:
        binding_strength = UsdShade.Tokens.weakerThanDescendants
    # apply the material
    material_binding_api.Bind(material, bindingStrength=binding_strength, materialPurpose="physics")  # type: ignore
    # return success
    return True


"""
Exporting.
"""


def export_prim_to_file(path: str, source_prim_path: str, target_prim_path: str = None, stage: Usd.Stage | None = None):
    """Exports a prim from a given stage to a USD file.

    The function creates a new layer at the provided path and copies the prim to the layer.
    It sets the copied prim as the default prim in the target layer. Additionally, it updates
    the stage up-axis and meters-per-unit to match the current stage.

    Args:
        path: The filepath path to export the prim to.
        source_prim_path: The prim path to export.
        target_prim_path: The prim path to set as the default prim in the target layer.
            Defaults to None, in which case the source prim path is used.
        stage: The stage where the prim exists. Defaults to None, in which case the
            current stage is used.
    """
    # get current stage
    if stage is None:
        stage: Usd.Stage = omni.usd.get_context().get_stage()
    # get root layer
    source_layer = stage.GetRootLayer()

    # only create a new layer if it doesn't exist already
    target_layer = Sdf.Find(path)
    if target_layer is None:
        target_layer = Sdf.Layer.CreateNew(path)
    # open the target stage
    target_stage = Usd.Stage.Open(target_layer)

    # update stage data
    UsdGeom.SetStageUpAxis(target_stage, UsdGeom.GetStageUpAxis(stage))
    UsdGeom.SetStageMetersPerUnit(target_stage, UsdGeom.GetStageMetersPerUnit(stage))

    # specify the prim to copy
    source_prim_path = Sdf.Path(source_prim_path)
    if target_prim_path is None:
        target_prim_path = source_prim_path

    # copy the prim
    Sdf.CreatePrimInLayer(target_layer, target_prim_path)
    Sdf.CopySpec(source_layer, source_prim_path, target_layer, target_prim_path)
    # set the default prim
    target_layer.defaultPrim = Sdf.Path(target_prim_path).name
    # resolve all paths relative to layer path
    omni.usd.resolve_paths(source_layer.identifier, target_layer.identifier)
    # save the stage
    target_layer.Save()


"""
USD Prim properties.
"""


def make_uninstanceable(prim_path: str, stage: Usd.Stage | None = None):
    """Check if a prim and its descendants are instanced and make them uninstanceable.

    This function checks if the prim at the specified prim path and its descendants are instanced.
    If so, it makes the respective prim uninstanceable by disabling instancing on the prim.

    This is useful when we want to modify the properties of a prim that is instanced. For example, if we
    want to apply a different material on an instanced prim, we need to make the prim uninstanceable first.

    Args:
        prim_path: The prim path to check.
        stage: The stage where the prim exists.
            Defaults to None, in which case the current stage is used.
    """
    # get current stage
    if stage is None:
        stage = stage_utils.get_current_stage()
    # get prim
    prim: Usd.Prim = stage.GetPrimAtPath(prim_path)
    # check if prim is valid
    if not prim.IsValid():
        raise ValueError(f"Prim at path '{prim_path}' is not valid.")
    # iterate over all prims under prim-path
    all_prims = [prim]
    while len(all_prims) > 0:
        # get current prim
        child_prim = all_prims.pop(0)
        # check if prim is instanced
        if child_prim.IsInstance():
            # make the prim uninstanceable
            child_prim.SetInstanceable(False)
        # add children to list
        all_prims += child_prim.GetChildren()
