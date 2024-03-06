from ngclib.component import Component
from jax import numpy as jnp, random, jit, nn
from functools import partial
import time, sys

@jit
def update_times(t, s, tols):
    _tols = (1. - s) * tols + (s * t)
    return _tols

@partial(jit, static_argnums=[7,8,9,10,11])
def run_cell(dt, j, v, v_thr, v_theta, rfr, skey, tau_m, R_m, v_rest, v_reset, refract_T):
    """
    Runs leaky integrator neuronal dynamics
    """
    _v_thr = v_theta + v_thr ## calc present voltage threshold
    mask = (rfr >= refract_T).astype(jnp.float32) # get refractory mask
    ## update voltage / membrane potential
    _v = v + (v_rest - v) * (dt/tau_m) + (j * mask)
    ## obtain action potentials
    s = (_v > _v_thr).astype(jnp.float32)
    ## update refractory variables
    _rfr = (rfr + dt) * (1. - s)
    ## perform hyper-polarization of neuronal cells
    _v = _v * (1. - s) + s * v_reset

    raw_s = s + 0 ## preserve un-altered spikes
    ############################################################################
    ## this is a spike post-processing step
    if skey is not None: ## FIXME: this would not work for mini-batches!!!!!!!
        m_switch = (jnp.sum(s) > 0.).astype(jnp.float32)
        rS = random.choice(skey, s.shape[1], p=jnp.squeeze(s))
        rS = nn.one_hot(rS, num_classes=s.shape[1], dtype=jnp.float32)
        s = s * (1. - m_switch) + rS * m_switch
    ############################################################################
    return _v, s, raw_s, _rfr

@partial(jit, static_argnums=[3,4])
def update_theta(dt, v_theta, s, tau_theta, theta_plus=0.05):
    """
    Runs homeostatic threshold update dynamics
    """
    #theta_decay = 0.9999999 #0.999999762 #jnp.exp(-dt/1e7)
    #theta_plus = 0.05
    #_V_theta = V_theta * theta_decay + S * theta_plus
    theta_decay = jnp.exp(-dt/tau_theta)
    _v_theta = v_theta * theta_decay + s * theta_plus
    #_V_theta = V_theta + -V_theta * (dt/tau_theta) + S * alpha
    return _v_theta

class LIFCell(Component): ## leaky integrate-and-fire cell
    ## Class Methods for Compartment Names
    @classmethod
    def inputCompartmentName(cls):
        return 'j' ## electrical current

    @classmethod
    def outputCompartmentName(cls):
        return 's' ## spike/action potential

    @classmethod
    def timeOfLastSpikeCompartmentName(cls):
        return 'tols' ## time-of-last-spike (record vector)

    @classmethod
    def voltageCompartmentName(cls):
        return 'v' ## membrane potential/voltage

    @classmethod
    def thresholdThetaName(cls):
        return 'thrTheta' ## action potential threshold

    @classmethod
    def refractCompartmentName(cls):
        return 'rfr' ## refractory variable(s)

    ## Bind Properties to Compartments for ease of use
    @property
    def current(self):
        return self.compartments.get(self.inputCompartmentName(), None)

    @current.setter
    def current(self, inp):
        if inp is not None:
            if inp.shape[1] != self.n_units:
                raise RuntimeError(
                    "Input Compartment size does not match provided input size " + str(inp.shape) + "for "
                    + str(self.name))
        self.compartments[self.inputCompartmentName()] = inp

    @property
    def spikes(self):
        return self.compartments.get(self.outputCompartmentName(), None)

    @spikes.setter
    def spikes(self, out):
        if out is not None:
            if out.shape[1] != self.n_units:
                raise RuntimeError(
                    "Output compartment size (n, " + str(self.n_units) + ") does not match provided output size "
                    + str(out.shape) + " for " + str(self.name))
        self.compartments[self.outputCompartmentName()] = out

    @property
    def timeOfLastSpike(self):
        return self.compartments.get(self.timeOfLastSpikeCompartmentName(), None)

    @timeOfLastSpike.setter
    def timeOfLastSpike(self, t):
        if t is not None:
            if t.shape[1] != self.n_units:
                raise RuntimeError("Time of last spike compartment size (n, " + str(self.n_units) +
                                   ") does not match provided size " + str(t.shape) + " for " + str(self.name))
        self.compartments[self.timeOfLastSpikeCompartmentName()] = t

    @property
    def voltage(self):
        return self.compartments.get(self.voltageCompartmentName(), None)

    @voltage.setter
    def voltage(self, v):
        if v is not None:
            if v.shape[1] != self.n_units:
                raise RuntimeError("Time of last spike compartment size (n, " + str(self.n_units) +
                                   ") does not match provided size " + str(v.shape) + " for " + str(self.name))
        self.compartments[self.voltageCompartmentName()] = v

    @property
    def refract(self):
        return self.compartments.get(self.refractCompartmentName(), None)

    @refract.setter
    def refract(self, rfr):
        if rfr is not None:
            if rfr.shape[1] != self.n_units:
                raise RuntimeError("Refractory variable compartment size (n, " + str(self.n_units) +
                                   ") does not match provided size " + str(rfr.shape) + " for " + str(self.name))
        self.compartments[self.refractCompartmentName()] = rfr

    @property
    def threshold_theta(self):
        return self.compartments.get(self.thresholdThetaName(), None)

    @threshold_theta.setter
    def threshold_theta(self, thr):
        self.compartments[self.thresholdThetaName()] = thr

    # Define Functions
    def __init__(self, name, n_units, tau_m, R_m, thr=-52., v_rest=-65., v_reset=60.,
                 tau_theta=1e7, theta_plus=0.05, refract_T=5., key=None, one_spike=True,
                 useVerboseDict=False, directory=None, **kwargs):
        super().__init__(name, useVerboseDict, **kwargs)

        ##Random Number Set up
        self.key = key
        if self.key is None:
            self.key = random.PRNGKey(time.time_ns())

        ## membrane parameter setup (affects ODE integration)
        self.tau_m = tau_m ## membrane time constant
        self.R_m = R_m ## resistance value
        self.one_spike = one_spike ## True => constrains system to simulate 1 spike per time step

        self.v_rest = v_rest #-65. # mV
        self.v_reset = v_reset # -60. # -65. # mV (milli-volts)
        self.tau_theta = tau_theta ## threshold time constant # ms (0 turns off)
        self.theta_plus = theta_plus #0.05 ## threshold increment
        self.refract_T = refract_T #5. # 2. ## refractory period  # ms

        ##Layer Size Setup
        self.n_units = n_units

        self.threshold = thr ## (fixed) base value for threshold  #-52 # -72. # mV
        ## adaptive threshold setup
        if directory is None:
            self.threshold_theta = jnp.zeros((1, n_units))
        else:
            self.load(directory)

        self.reset()

    def verify_connections(self):
        self.metadata.check_incoming_connections(self.inputCompartmentName(), min_connections=1)

    def advance_state(self, t, dt, **kwargs):
        if self.spikes is None:
            self.spikes = jnp.zeros((1, self.n_units))
        if self.refract is None:
            self.refract = jnp.zeros((1, self.n_units)) + self.refract_T
        skey = None ## this is an empty dkey if single_spike mode turned off
        if self.one_spike is False:
            self.key, *subkeys = random.split(self.key, 2)
            skey = subkeys[0]

        ## run one step of Euler integration over neuronal dynamics
        self.voltage, self.spikes, raw_spikes, self.refract = \
            run_cell(dt, self.current, self.voltage, self.threshold,
                     self.threshold_theta, self.refract, skey, self.tau_m,
                     self.R_m, self.v_rest, self.v_reset, self.refract_T)
        if self.tau_theta > 0.:
            ## run one step of Euler integration over threshold dynamics
            self.threshold_theta = update_theta(dt, self.threshold_theta, raw_spikes,
                                                self.tau_theta, self.theta_plus)
        ## update tols
        self.timeOfLastSpike = update_times(t, self.spikes, self.timeOfLastSpike)
        #self.timeOfLastSpike = (1 - self.spikes) * self.timeOfLastSpike + (self.spikes * t)
        #self.current = None

    def reset(self, **kwargs):
        self.voltage = jnp.zeros((1, self.n_units)) + self.v_rest
        self.refract = jnp.zeros((1, self.n_units)) + self.refract_T
        self.current = jnp.zeros((1, self.n_units)) #None
        self.timeOfLastSpike = jnp.zeros((1, self.n_units))
        self.spikes = jnp.zeros((1, self.n_units)) #None

    def save(self, directory, **kwargs):
        file_name = directory + "/" + self.name + ".npz"
        jnp.savez(file_name, threshold_theta=self.threshold_theta)

    def load(self, directory, **kwargs):
        file_name = directory + "/" + self.name + ".npz"
        data = jnp.load(file_name)
        self.threshold_theta = data['threshold_theta']
