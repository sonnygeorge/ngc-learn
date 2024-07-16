from ngclearn import resolver, Component, Compartment
from ngclearn.components.jaxComponent import JaxComponent
from jax import numpy as jnp, jit
from ngclearn.utils import tensorstats

class RewardErrorCell(JaxComponent): ## Reward prediction error cell
    """
    A reward prediction error (RPE) cell.

    | --- Cell Input Compartments: ---
    | reward - current reward signal at time `t`
    | accum_reward - current accumulated episodic reward signal
    | --- Cell Output Compartments: ---
    | mu - current moving average prediction of reward at time `t`
    | rpe - current reward prediction error (RPE) signal
    | accum_reward - current accumulated episodic reward signal (IF online predictor not used)

    Args:
        name: the string name of this cell

        n_units: number of cellular entities (neural population size)

        alpha: decay factor to apply to (exponential) moving average prediction

        ema_window_len: exponential moving average window length -- for use only
            in `evolve` step for updating episodic reward signals; (default: 10)
    """
    def __init__(self, name, n_units, alpha, ema_window_len=10, batch_size=1,
                 **kwargs):
        super().__init__(name, **kwargs)

        ## RPE meta-parameters
        self.alpha = alpha
        self.ema_window_len = ema_window_len

        ## Layer Size Setup
        self.n_units = n_units
        self.batch_size = batch_size

        ## Compartment setup
        restVals = jnp.zeros((self.batch_size, self.n_units))
        self.mu = Compartment(restVals) ## reward predictor state(s)
        self.reward = Compartment(restVals) ## target reward signal(s)
        self.rpe = Compartment(restVals) ## reward prediction error(s)
        self.accum_reward = Compartment(restVals)  ## accumulated reward signal(s)
        self.Ns = Compartment(jnp.zeros((self.batch_size, 1)))
        self.n_ep_steps = Compartment(jnp.zeros((self.batch_size, 1))) ## number of episode steps taken

    @staticmethod
    def _advance_state(dt, alpha, mu, rpe, reward, n_ep_steps, accum_reward, Ns):
        ## compute/update RPE and predictor values
        accum_reward = accum_reward + reward
        #m = (Ns > 0.) * 1.
        #_Ns = Ns * m + (1. - m) ## mask out Ns
        rpe = reward - mu #/_Ns #reward - mu
        mu = mu * (1. - alpha) + reward * alpha
        # mu = mu + reward
        # Ns = Ns + 1.
        n_ep_steps = n_ep_steps + 1
        return mu, rpe, n_ep_steps, accum_reward, Ns

    @resolver(_advance_state)
    def advance_state(self, mu, rpe, n_ep_steps, accum_reward, Ns):
        self.mu.set(mu)
        self.rpe.set(rpe)
        self.n_ep_steps.set(n_ep_steps)
        self.accum_reward.set(accum_reward)
        self.Ns.set(Ns)

    @staticmethod
    def _evolve(dt, ema_window_len, n_ep_steps, mu, accum_reward, reward): #, rpe):
        accum_reward = accum_reward + reward
        n_ep_steps = n_ep_steps + 1
        ## total episodic reward signal
        r = accum_reward/n_ep_steps
        mu = (1. - 1./ema_window_len) * mu + (1./ema_window_len) * r
        rpe = r - mu
        return mu, rpe, accum_reward

    @resolver(_evolve)
    def evolve(self, mu, rpe, accum_reward):
        self.mu.set(mu)
        self.rpe.set(rpe)
        self.accum_reward.set(accum_reward)

    @staticmethod
    def _reset(batch_size, n_units):
        restVals = jnp.zeros((batch_size, n_units))
        mu = restVals
        rpe = restVals
        resetMask = jnp.zeros((batch_size, 1))
        accum_reward = resetMask
        reward = resetMask
        n_ep_steps = resetMask
        Ns = resetMask
        return mu, rpe, accum_reward, reward, n_ep_steps, Ns

    @resolver(_reset)
    def reset(self, mu, rpe, accum_reward, reward, n_ep_steps, Ns):
        self.mu.set(mu)
        self.rpe.set(rpe)
        self.accum_reward.set(accum_reward)
        self.reward.set(reward)
        self.n_ep_steps.set(n_ep_steps)
        self.Ns.set(Ns)

    @classmethod
    def help(cls): ## component help function
        properties = {
            "cell_type": "RewardErrorCell - computes the reward prediction error "
                         "at each time step `t`; this is an online RPE estimator"
        }
        compartment_props = {
            "inputs":
                {"reward": "External reward signals/values"},
            "outputs":
                {"mu": "Current state of reward predictor",
                 "rpe": "Current value of reward prediction error at time `t`",
                 "accum_reward": "Current accumulated episodic reward signal (generally "
                                 "produced at the end of a control episode of `n_steps`)",
                 "n_ep_steps": "Number of episodic steps taken/tracked thus far "
                               "(since last `reset` call)"},
        }
        hyperparams = {
            "n_units": "Number of neuronal cells to model in this layer",
            "alpha": "Moving average decay factor",
            "ema_window_len": "Exponential moving average window length",
            "batch_size": "Batch size dimension of this component"
        }
        info = {cls.__name__: properties,
                "compartments": compartment_props,
                "dynamics": "rpe = reward - mu; mu = mu * (1 - alpha) + reward * alpha; "
                            "accum_reward = accum_reward + reward",
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
