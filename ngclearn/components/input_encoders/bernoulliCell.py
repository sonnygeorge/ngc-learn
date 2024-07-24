from ngclearn import resolver, Component, Compartment
from ngclearn.components.jaxComponent import JaxComponent
from jax import numpy as jnp, random, jit
from ngclearn.utils import tensorstats
from functools import partial
from ngcsimlib.deprecators import deprecate_args
from ngcsimlib.logger import info, warn

@jit
def _update_times(t, s, tols):
    """
    Updates time-of-last-spike (tols) variable.

    Args:
        t: current time (a scalar/int value)

        s: binary spike vector

        tols: current time-of-last-spike variable

    Returns:
        updated tols variable
    """
    _tols = (1. - s) * tols + (s * t)
    return _tols

@jit
def _sample_bernoulli(dkey, data):
    """
    Samples a Bernoulli spike train on-the-fly

    Args:
        dkey: JAX key to drive stochasticity/noise

        data: sensory data (vector/matrix)

    Returns:
        binary spikes
    """
    s_t = random.bernoulli(dkey, p=data).astype(jnp.float32)
    return s_t

@partial(jit, static_argnums=[3])
def _sample_constrained_bernoulli(dkey, data, dt, fmax=63.75):
    """
    Samples a Bernoulli spike train on-the-fly that is constrained to emit
    at a particular rate over a time window.

    Args:
        dkey: JAX key to drive stochasticity/noise

        data: sensory data (vector/matrix)

        dt: integration time constant

        fmax: maximum frequency (Hz)

    Returns:
        binary spikes
    """
    pspike = data * (dt/1000.) * fmax
    eps = random.uniform(dkey, data.shape, minval=0., maxval=1., dtype=jnp.float32)
    s_t = (eps < pspike).astype(jnp.float32)
    return s_t

class BernoulliCell(JaxComponent):
    """
    A Bernoulli cell that produces variations of Bernoulli-distributed spikes
    on-the-fly (including constrained-rate trains).

    | --- Cell Input Compartments: ---
    | inputs - input (takes in external signals)
    | --- Cell State Compartments: ---
    | key - JAX PRNG key
    | --- Cell Output Compartments: ---
    | outputs - output
    | tols - time-of-last-spike

    Args:
        name: the string name of this cell

        n_units: number of cellular entities (neural population size)

        target_freq: maximum frequency (in Hertz) of this Bernoulli spike train (must be > 0.)
    """

    @deprecate_args(target_freq="max_freq")
    def __init__(self, name, n_units, target_freq=63.75, batch_size=1, **kwargs):
        super().__init__(name, **kwargs)

        ## Constrained Bernoulli meta-parameters
        self.target_freq = target_freq  ## maximum frequency (in Hertz/Hz)

        ## Layer Size Setup
        self.batch_size = batch_size
        self.n_units = n_units

        # Compartments (state of the cell, parameters, will be updated through stateless calls)
        restVals = jnp.zeros((self.batch_size, self.n_units))
        self.inputs = Compartment(restVals, display_name="Input Stimulus") # input compartment
        self.outputs = Compartment(restVals, display_name="Spikes") # output compartment
        self.tols = Compartment(restVals, display_name="Time-of-Last-Spike", units="ms") # time of last spike

    def validate(self, dt, **validation_kwargs):
        ## check for unstable combinations of dt and target-frequency meta-params
        valid = super().validate(**validation_kwargs)
        events_per_timestep = (dt/1000.) * self.target_freq ## compute scaled probability
        if events_per_timestep > 1.:
            valid = False
            warn(
                f"{self.name} will be unable to make as many temporal events as "
                f"requested! ({events_per_timestep} events/timestep) Unstable "
                f"combination of dt = {dt} and target_freq = {self.target_freq} "
                f"being used!"
            )
        return valid

    @staticmethod
    def _advance_state(t, dt, target_freq, key, inputs, tols):
        key, *subkeys = random.split(key, 2)
        if target_freq > 0.:
            outputs = _sample_constrained_bernoulli( ## sample Bernoulli w/ target rate
                subkeys[0], data=inputs, dt=dt, fmax=target_freq
            )
        else:
            outputs = _sample_bernoulli(subkeys[0], data=inputs)
        tols = _update_times(t, outputs, tols)
        return outputs, tols, key

    @resolver(_advance_state)
    def advance_state(self, outputs, tols, key):
        self.outputs.set(outputs)
        self.tols.set(tols)
        self.key.set(key)

    @staticmethod
    def _reset(batch_size, n_units):
        restVals = jnp.zeros((batch_size, n_units))
        return restVals, restVals, restVals

    @resolver(_reset)
    def reset(self, inputs, outputs, tols):
        self.inputs.set(inputs)
        self.outputs.set(outputs) #None
        self.tols.set(tols)

    def save(self, directory, **kwargs):
        file_name = directory + "/" + self.name + ".npz"
        jnp.savez(file_name, key=self.key.value)

    def load(self, directory, **kwargs):
        file_name = directory + "/" + self.name + ".npz"
        data = jnp.load(file_name)
        self.key.set(data['key'])

    @classmethod
    def help(cls): ## component help function
        properties = {
            "cell_type": "BernoulliCell - samples input to produce spikes, "
                          "where dimension is a probability proportional to "
                          "the dimension's magnitude/value/intensity"
        }
        compartment_props = {
            "inputs":
                {"inputs": "Takes in external input signal values"},
            "states":
                {"key": "JAX PRNG key"},
            "outputs":
                {"tols": "Time-of-last-spike",
                 "outputs": "Binary spike values emitted at time t"},
        }
        hyperparams = {
            "n_units": "Number of neuronal cells to model in this layer",
            "batch_size": "Batch size dimension of this component"
        }
        info = {cls.__name__: properties,
                "compartments": compartment_props,
                "dynamics": "~ Bernoulli(x)",
                "hyperparameters": hyperparams}
        return info

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
        X = BernoulliCell("X", 9)
    print(X)
