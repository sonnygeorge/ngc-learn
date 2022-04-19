import tensorflow as tf
import sys
import numpy as np
import copy
from ngclearn.utils import transform_utils
from ngclearn.engine.cables.cable import Cable

"""
Copyright (C) 2021 Alexander G. Ororbia II - All Rights Reserved
You may use, distribute and modify this code under the
terms of the GNU LGPL-3.0-or-later license.

You should have received a copy of the XYZ license with
this file. If not, please write to: ago@cs.rit.edu , or visit:
https://www.gnu.org/licenses/lgpl-3.0.en.html
"""

class SCable(Cable):

    def __init__(self, inp, out, coeff=1.0, name=None, seed=69):
        cable_type = "simple"
        super().__init__(cable_type, inp, out, name, seed, coeff=coeff)

    def propagate(self, node):
        inp_value = node.extract(self.inp_var)
        out_value = inp_value * self.coeff
        return out_value

    # def clear(self):
    #     self.cable_out = None
