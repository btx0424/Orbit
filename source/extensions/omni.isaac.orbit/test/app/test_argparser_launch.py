# Copyright (c) 2022-2023, The ORBIT Project Developers.
# All rights reserved.
#
# SPDX-License-Identifier: BSD-3-Clause

from __future__ import annotations

import argparse
import unittest
from unittest import mock

from omni.isaac.orbit.app import AppLauncher


class TestAppLauncher(unittest.TestCase):
    """Test launching of the simulation app using AppLauncher."""

    @mock.patch("argparse.ArgumentParser.parse_args", return_value=argparse.Namespace(livestream=1))
    def test_livestream_launch_with_argparser(self, mock_args):
        """Test launching with argparser arguments."""
        # create argparser
        parser = argparse.ArgumentParser()
        # add app launcher arguments
        AppLauncher.add_app_launcher_args(parser)
        # check that argparser has the mandatory arguments
        for name in AppLauncher._APPLAUNCHER_CONFIG_TYPES:
            self.assertTrue(parser._option_string_actions[f"--{name}"])
        # parse args
        mock_args = parser.parse_args()
        # everything defaults to None
        app = AppLauncher(mock_args).app

        # import settings
        import carb

        # acquire settings interface
        carb_settings_iface = carb.settings.get_settings()
        # check settings
        # -- no-gui mode
        self.assertEqual(carb_settings_iface.get("/app/window/enabled"), False)
        # -- livestream
        self.assertEqual(carb_settings_iface.get("/app/livestream/enabled"), True)

        # close the app on exit
        app.close()


if __name__ == "__main__":
    unittest.main()
