#!/usr/bin/env python3

###############################################################################
# Base code from:                                                             #
# * https://github.com/facebookresearch/habitat-lab                           #
# * https://github.com/saimwani/multiON                                       #
#                                                                             #
# Adapted by Pierre Marza (pierre.marza@insa-lyon.fr)                         #
###############################################################################

import json
from typing import List

import numpy as np
import quaternion

from habitat.utils.geometry_utils import quaternion_to_list

# Internals from inner json library needed for patching functionality in
# DatasetFloatJSONEncoder.
try:
    from _json import encode_basestring_ascii
except ImportError:
    encode_basestring_ascii = None
try:
    from _json import encode_basestring
except ImportError:
    encode_basestring = None


def tile_images(images: List[np.ndarray]) -> np.ndarray:
    r"""Tile multiple images into single image

    Args:
        images: list of images where each image has dimension
            (height x width x channels)

    Returns:
        tiled image (new_height x width x channels)
    """
    assert len(images) > 0, "empty list of images"
    np_images = np.asarray(images)
    n_images, height, width, n_channels = np_images.shape
    new_height = int(np.ceil(np.sqrt(n_images)))
    new_width = int(np.ceil(float(n_images) / new_height))
    # pad with empty images to complete the rectangle
    np_images = np.array(
        images + [images[0] * 0 for _ in range(n_images, new_height * new_width)]
    )
    # img_HWhwc
    out_image = np_images.reshape(new_height, new_width, height, width, n_channels)
    # img_HhWwc
    out_image = out_image.transpose(0, 2, 1, 3, 4)
    # img_Hh_Ww_c
    out_image = out_image.reshape(new_height * height, new_width * width, n_channels)
    return out_image


def not_none_validator(self, attribute, value):
    if value is None:
        raise ValueError(f"Argument '{attribute.name}' must be set")


def try_cv2_import():
    r"""The PyRobot python3 version which is a dependency of Habitat-PyRobot integration
    relies on ROS running in python2.7. In order to import cv2 in python3 we need to remove
    the python2.7 path from sys.path. To use the Habitat-PyRobot integration the user
    needs to export environment variable ROS_PATH which will look something like:
    /opt/ros/kinetic/lib/python2.7/dist-packages
    """
    import sys
    import os

    ros_path = os.environ.get("ROS_PATH")
    if ros_path is not None and ros_path in sys.path:
        sys.path.remove(ros_path)
        import cv2

        sys.path.append(ros_path)
    else:
        import cv2

    return cv2


class Singleton(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]


def center_crop(obs, new_shape):
    top_left = (
        (obs.shape[0] // 2) - (new_shape[0] // 2),
        (obs.shape[1] // 2) - (new_shape[1] // 2),
    )
    bottom_right = (
        (obs.shape[0] // 2) + (new_shape[0] // 2),
        (obs.shape[1] // 2) + (new_shape[1] // 2),
    )
    obs = obs[top_left[0] : bottom_right[0], top_left[1] : bottom_right[1], :]

    return obs


class DatasetFloatJSONEncoder(json.JSONEncoder):
    r"""JSON Encoder that sets a float precision for a space saving purpose and
    encodes ndarray and quaternion. The encoder is compatible with JSON
    version 2.0.9.
    """

    def default(self, object):
        # JSON doesn't support numpy ndarray and quaternion
        if isinstance(object, np.ndarray):
            return object.tolist()
        if isinstance(object, np.quaternion):
            return quaternion_to_list(object)
        quaternion
        return object.__dict__

    # Overriding method to inject own `_repr` function for floats with needed
    # precision.
    def iterencode(self, o, _one_shot=False):

        if self.check_circular:
            markers = {}
        else:
            markers = None
        if self.ensure_ascii:
            _encoder = encode_basestring_ascii
        else:
            _encoder = encode_basestring

        def floatstr(
            o,
            allow_nan=self.allow_nan,
            _repr=lambda x: format(x, ".5f"),
            _inf=float("inf"),
            _neginf=-float("inf"),
        ):
            if o != o:
                text = "NaN"
            elif o == _inf:
                text = "Infinity"
            elif o == _neginf:
                text = "-Infinity"
            else:
                return _repr(o)

            if not allow_nan:
                raise ValueError(
                    "Out of range float values are not JSON compliant: " + repr(o)
                )

            return text

        _iterencode = json.encoder._make_iterencode(
            markers,
            self.default,
            _encoder,
            self.indent,
            floatstr,
            self.key_separator,
            self.item_separator,
            self.sort_keys,
            self.skipkeys,
            _one_shot,
        )
        return _iterencode(o, 0)
