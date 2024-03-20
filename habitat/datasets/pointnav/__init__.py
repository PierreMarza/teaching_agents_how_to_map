#!/usr/bin/env python3

###############################################################################
# Base code from:                                                             #
# * https://github.com/facebookresearch/habitat-lab                           #
# * https://github.com/saimwani/multiON                                       #
#                                                                             #
# Adapted by Pierre Marza (pierre.marza@insa-lyon.fr)                         #
###############################################################################

from habitat.core.dataset import Dataset
from habitat.core.registry import registry


# TODO(akadian): This is a result of moving SimulatorActions away from core
# and into simulators specifically. As a result of that the connection points
# for our tasks and datasets for actions is coming from inside habitat-sim
# which makes it impossible for anyone to use habitat-api without having
# habitat-sim installed. In a future PR we will implement a base simulator
# action class which will be the connection point for tasks and datasets.
# Post that PR we would no longer need try register blocks.
def _try_register_pointnavdatasetv1():
    try:
        from habitat.datasets.pointnav.pointnav_dataset import (
            PointNavDatasetV1,
        )

        has_pointnav = True
    except ImportError as e:
        has_pointnav = False
        pointnav_import_error = e

    if has_pointnav:
        from habitat.datasets.pointnav.pointnav_dataset import (
            PointNavDatasetV1,
        )
    else:

        @registry.register_dataset(name="PointNav-v1")
        class PointnavDatasetImportError(Dataset):
            def __init__(self, *args, **kwargs):
                raise pointnav_import_error
