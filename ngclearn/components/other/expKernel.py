from ngcsimlib.component import Component
from ngcsimlib.compartment import Compartment
from ngcsimlib.resolver import resolver
from jax import numpy as jnp, random, jit
from functools import partial
from ngclearn.utils import tensorstats
import time, sys

@partial(jit, static_argnums=[5,6])
def apply_kernel(tf_curr, s, t, tau_w, win_len, krn_start, krn_end):
    idx_sub = tf_curr.shape[0]-1
    tf_new = (s * t) ## track new spike time(s)
    tf = tf_curr.at[idx_sub,:,:].set(tf_new)
    tf = jnp.roll(tf, shift=-1, axis=0) # 1,2,3  2,3,1

    ## apply exp time kernel
    ## EPSP = sum_{tf} exp(-(t - tf)/tau_w)
    _tf = tf[krn_start:krn_end,:,:]
    mask = jnp.greater(_tf, 0.).astype(jnp.float32) # 1 for every valid tf (non-zero)
    epsp = jnp.sum( jnp.exp( -(t - _tf)/tau_w ) * mask, axis=0 )
    return tf, epsp

class ExpKernel(Component): ## exponential kernel
    """
    A spiking function based on an exponential kernel applied to
    a moving window of spike times.

    Args:
        name: the string name of this operator

        n_units: number of calculating entities or units

        dt: integration time constant (the kernel needs access to this value)

        nu: (ms, spike time interval for window)

        tau_w: spike window time constant (in micro-secs, or nano-s)

        key: PRNG key to control determinism of any underlying random values
            associated with this cell

        directory: string indicating directory on disk to save sLIF parameter
            values to (i.e., initial threshold values and any persistent adaptive
            threshold values)
    """

    # Define Functions
    def __init__(self, name, n_units, dt, tau_w=500., nu=4., key=None,
                 directory=None, **kwargs):
        super().__init__(name, **kwargs)

        self.tau_w = tau_w ## kernel window time constant
        self.nu = nu
        self.win_len = int(nu/dt) + 1 ## window length
        #tf ## window of spike times

        ## Layer Size Setup
        self.batch_size = 1
        self.n_units = n_units

        restVals = jnp.zeros((self.batch_size, self.n_units))
        self.inputs = Compartment(restVals) # input comp
        self.epsp = Compartment(restVals) ## output comp
        self.tf = Compartment(jnp.zeros((self.win_len, self.batch_size, self.n_units))) ## window comp
        #self.reset()

    @staticmethod
    def _advance_state(t, dt, tau_w, win_len, inputs, epsp, tf):
        s = inputs
        ## update spike time window and corresponding window volume
        tf, epsp = apply_kernel(tf, s, t, tau_w, win_len, krn_start=0,
                                krn_end=win_len-1) #0:win_len-1)
        return epsp, tf

    @resolver(_advance_state)
    def advance_state(self, epsp, tf):
        self.epsp.set(epsp)
        self.tf.set(tf)

    @staticmethod
    def _reset(batch_size, n_units, win_len):
        restVals = jnp.zeros((batch_size, n_units))
        restTensor = jnp.zeros([win_len, batch_size, n_units], jnp.float32) # tf
        return restVals, restVals, restTensor # inputs, epsp, tf

    @resolver(_reset)
    def reset(self, inputs, epsp, tf):
        self.inputs.set(inputs)
        self.epsp.set(epsp)
        self.tf.set(tf)

    def __repr__(self):
        comps = [varname for varname in dir(self) if Compartment.is_compartment(getattr(self, varname))]
        maxlen = max(len(c) for c in comps) + 5
        lines = f"[{self.__class__.__name__}] PATH: {self.name}\n"
        for c in comps:
            stats = tensorstats(getattr(self, c).value)
            if stats is not None:
                line = [f"{k}: {v}" for k, v in stats.items()]
                line = ", ".join(line)
            else:
                line = "None"
            lines += f"  {f'({c})'.ljust(maxlen)}{line}\n"
        return lines

if __name__ == '__main__':
    from ngcsimlib.context import Context
    with Context("Bar") as bar:
        X = VarTrace("X", 9, 0.0004, 3)
    print(X)
