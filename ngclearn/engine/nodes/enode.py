import tensorflow as tf
import sys
import numpy as np
import copy
from ngclearn.engine.nodes.node import Node
from ngclearn.utils import transform_utils

"""
Copyright (C) 2021 Alexander G. Ororbia II - All Rights Reserved
You may use, distribute and modify this code under the
terms of the GNU LGPL-3.0-or-later license.

You should have received a copy of the XYZ license with
this file. If not, please write to: ago@cs.rit.edu , or visit:
https://www.gnu.org/licenses/lgpl-3.0.en.html
"""

class ENode(Node):

    def __init__(self, name, dim, error_type="mse", beta=1.0, leak=0.0, zeta=1.0,
                 act_fx="identity", precis_kernel=None, ex_scale=1.0):
        node_type = "error"
        super().__init__(node_type, name, dim)
        self.error_type = error_type
        self.use_mod_factor = False
        self.ex_scale = ex_scale

        fx, dfx = transform_utils.decide_fun(act_fx)
        self.fx = fx
        self.dfx = dfx

        self.Prec = None # the precision matrix for this node
        self.Sigma = None # the covariance matrix for this node
        if precis_kernel is not None: # (init_type, sigma)
            self.is_learnable = True # if precision is used, then this node becomes "learnable"
            prec_type, prec_sigma = precis_kernel
            #if self.prec_sigma > 0.0:
            # create potential precision synapses at point of connection to target_node
            diag = tf.eye(self.dim) #* prec_sigma
            init = diag + tf.random.uniform([self.dim,self.dim],minval=-prec_sigma,maxval=prec_sigma) * (1.0 - diag)
            #init = diag + init_weights("orthogonal", [self.z_dims[l],self.z_dims[l]], stddev=prec_sigma, seed=seed) * (1.0 - diag)
            Sigma = tf.Variable(init, name="Sigma_{0}".format(self.name) )
            self.Sigma = Sigma

        # node meta-parameters
        self.beta = beta
        self.leak = leak
        self.zeta = zeta

        # error neuron-specific vector statistics
        self.stat["pred_mu"] = None
        self.stat["pred_targ"] = None
        self.stat["L"] = None
        self.stat["avg_scalar"] = None # if clamped/set, will scale error neurons and loss by 1/N, N = mini-batch size
        self.stat["weights"] = None

        self.build_tick()

    ############################################################################
    # Setup Routines
    ############################################################################

    def clear(self):
        super().clear()
        self.stat["pred_mu"] = None
        self.stat["pred_targ"] = None
        self.stat["L"] = None
        self.stat["avg_scalar"] = None
        self.stat["weights"] = None

    def check_correctness(self):
        is_correct = True
        for j in range(len(self.input_nodes)):
            n_j = self.input_nodes[j]
            cable_j = self.input_cables[j]
            dest_var_j = cable_j.out_var
            if dest_var_j != "pred_mu" and dest_var_j != "pred_targ":
                is_correct = False
                print("ERROR: Cable {0} mis-wires to {1}.{2}".format(cable_j.name, self.name, dest_var_j))
                break
        n_ins = len(self.input_nodes)
        if n_ins != 2:
            print("ERROR: Only two nodes can exactly wire to this error node, not {0}".format(n_ins))
            is_correct = False
        return is_correct

    ############################################################################
    # Signal Transmission Routines
    ############################################################################

    def step(self, skip_core_calc=False):
        Ws = self.stat.get("weights")
        Ns = self.stat.get("avg_scalar")
        z = self.stat.get("z")
        #pre_z = None
        dz = None
        if self.is_clamped is False and skip_core_calc is False:
            for j in range(len(self.input_nodes)):
                n_j = self.input_nodes[j]
                cable_j = self.input_cables[j]
                dest_var_j = cable_j.out_var
                tick_j = self.tick.get(dest_var_j)
                var_j = self.stat.get(dest_var_j) # get current value of component
                dz_j = cable_j.propagate(n_j)
                if tick_j > 0: #if var_j is not None:
                    var_j = var_j + dz_j
                else:
                    var_j = dz_j
                self.stat[dest_var_j] = var_j
                self.tick[dest_var_j] = self.tick[dest_var_j] + 1

            pred_mu = self.stat.get("pred_mu")
            pred_targ = self.stat.get("pred_targ")

            # TODO: should this block of code for masking be moved elsewhere to improve efficiency?
            bmask = self.stat.get("mask")
            if bmask is not None: # applies mask to all component variables of this node
                if pred_mu is not None:
                    pred_mu = pred_mu * bmask
                if pred_targ is not None:
                    pred_targ = pred_targ * bmask

            if pred_mu is None:
                print("ERROR:  {0}.pred_mu is NONE!".format(self.name))
                sys.exit(1)
            if pred_targ is None:
                print("ERROR:  {0}.pred_targ is NONE!".format(self.name))
                sys.exit(1)

            if self.error_type == "mse":
                dz = pred_targ - pred_mu
                #dz = -dz
                #z = z * self.zeta + dz * self.beta - z * leak
                z = dz
                e = z
                # compute local loss that this error node represents
                L_batch = tf.reduce_sum(e * e, axis=1, keepdims=True) #/(e.shape[0] * 2.0)
                if Ws is not None: # optionally scale units by a fixed external set of weights
                    L_batch = L_batch * Ws
                    z = z * Ws
                L = tf.reduce_sum(L_batch)
                z = z  * self.ex_scale
                if Ns is not None: # optionally scale units and local loss by 1/Ns
                    L = L * (1.0/Ns)
                    z = z * (1.0/Ns)
                self.stat["L"] = L
            else:
                print("Error: {0} for error neuron not implemented yet".format(self.error_type))
                sys.exit(1)
            # Spratling-style error neurons
            # eps2 = 1e-2
            # self.e = self.z/tf.math.maximum(eps2, self.z_mu)
            if self.Prec is not None:
                #pre_z = e + 0
                z = tf.matmul(z, self.Prec)
                #sys.exit(0)
        # the post-activation function is computed always, even if pre-activation is clamped
        phi_z = self.fx(z)
        self.stat["dz"] = dz
        #self.stat["pre_z"] = pre_z # FOR COMPATIBILITY WITH PRECISION CALC
        self.stat["z"] = z
        self.stat["phi(z)"] = phi_z
        # print("***************")
        # print("{}.phi(z) =\n{}".format(self.name,phi_z))

        bmask = self.stat.get("mask")
        if bmask is not None: # applies mask to all component variables of this node
            if self.stat.get("dz") is not None:
                self.stat["dz"] = self.stat.get("dz") * bmask
            if self.stat.get("z") is not None:
                self.stat["z"] = self.stat.get("z") * bmask
            if self.stat.get("phi(z)") is not None:
                self.stat["phi(z)"] = self.stat.get("phi(z)") * bmask

        self.build_tick()

    def compute_precision(self, rebuild_cov=True):
        """
            Co-function that pre-computes the precision matrices for this NGC node.
            NGC uses the Cholesky-decomposition form of precision (Sigma)^{-1}
        """
        eps = 0.00025 #0.0001 # stability factor for precision/covariance computation
        cov_l = self.Sigma #tf.math.abs(self.Sigma[l])

        diag_l = tf.eye(cov_l.shape[1])
        vari_l = tf.math.maximum(1.0, cov_l) * diag_l # restrict diag( Sigma ) to be >= 1.0
        # #vari_l = tf.math.abs(cov_l * diag_l) # variance is restricted to be positive
        cov_l = vari_l + (cov_l * (1.0 - diag_l))
        #cov_l = cov_l + (1.0 - diag_l) * 0.001
        cov_l = cov_l + eps

        # min_val = 0.005
        # m_l = tf.cast(tf.math.less(cov_l, min_val),dtype=tf.float32)
        # cov_l = cov_l * (1.0 - m_l) + (m_l * min_val)
        #cov_l = cov_l * (1.0 - diag_l) + diag_l
        if rebuild_cov is True:
            self.Sigma.assign( cov_l )

        # Note for Numerical Stability:
        #   Add small pertturbation eps * I to covariance before decomposing
        #   (due to rapidly decaying Eigen values)
        #R = tf.linalg.cholesky(cov_l + diag_l) # decompose
        R = tf.linalg.cholesky(cov_l) # + diag_l * eps) # decompose
        #R = tf.linalg.cholesky(cov_l)
        prec_l = tf.transpose(tf.linalg.triangular_solve(R,diag_l,lower=True))
        self.Prec = prec_l

        # eps = 0.0005 #0.0001
        # cov_l = self.Sigma #tf.math.abs(self.Sigma[l])
        # diag_l = tf.eye(cov_l.shape[1])
        # vari_l = tf.math.abs(cov_l * diag_l) # variance is restricted to be positive
        # cov_l = vari_l + (cov_l * (1.0 - diag_l))
        # if rebuild_cov is True:
        #     self.Sigma.assign( cov_l )
        # # Note for Numerical Stability: Add small pertturbation eps * I to covariance before decomposing
        # #                               (due to rapidly decaying Eigen values)
        # R = tf.linalg.cholesky(cov_l + diag_l * eps) # decompose
        # #R = tf.linalg.cholesky(cov_l) # decompose
        # prec_l = tf.transpose(tf.linalg.triangular_solve(R,diag_l,lower=True))
        # self.Prec = prec_l

    def calc_update(self, update_radius=-1.0):
        """
            Calculate the updates to the local synaptic parameters related to this
            specific node
        """
        delta = []
        # compute update to lateral correlation synapses
        if self.Sigma is not None:
            Prec_l = self.Prec
            #e_noprec = self.stat.get("pre_z")
            #e = e_noprec
            e = self.stat.get("phi(z)")
            B = tf.matmul(e, e, transpose_a=True)
            #dW = tf.matmul(tf.matmul(-Prec_l, B), Prec_l) - Prec_l
            dW = (B - Prec_l) * 0.5 # d_L_l / d_cov_l (derivative w.r.t. covariance)
            #dW = tf.matmul(tf.matmul(Prec_l, B), Prec_l) * 0.5 - Prec_l * 0.5 # deriv w.r.t. Cov, can get Prec from Cholesky/Triangular solve from Cov
            #dW = self.Sigma[l] - B * 0.5 # <-- direct derivative w.r.t. precision but would require Cov = (Prec)^{-1}
            if update_radius > 0.0:
                dW = tf.clip_by_norm(dW, update_radius)
            if self.use_mod_factor is True:
                W_M = transform_utils.calc_modulatory_factor(self.Sigma)
                dW = dW * W_M
            dW = -dW
            delta.append(dW)
        return delta
