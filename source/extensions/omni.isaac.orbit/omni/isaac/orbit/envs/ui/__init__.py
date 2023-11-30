# Copyright (c) 2022-2023, The ORBIT Project Developers.
# All rights reserved.
#
# SPDX-License-Identifier: BSD-3-Clause

"""Sub-module providing UI window implementation for environments.

The UI elements are used to control the environment and visualize the state of the environment.
This includes functionalities such as tracking a robot in the simulation,
toggling different debug visualization tools, and other user-defined functionalities.
"""

# enable the extension for UI elements
# this only needs to be done once
from omni.isaac.core.utils.extensions import enable_extension

enable_extension("omni.isaac.ui")

# import all UI elements here
from .base_env_window import BaseEnvWindow
from .rl_task_env_window import RLTaskEnvWindow
