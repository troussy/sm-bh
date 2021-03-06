import numpy as np
import math

# Class for handling the Lambda, Gamma, and Theta tensors
class TEBD(object):

	# Initialize
	def __init__(self, model, sim, init, logs):
		self.Lambda = lambda0(sim)
		coeffs = Initialize_States(sim, init)
		self.Gamma = Gamma0(coeffs, sim)
		self.tau = 0
		self.model = model
		self.sim = sim
		self.init = init
		self.logs = logs
		self.rhos = np.zeros((sim['L'], sim['N']+1, sim['d'], sim['d']))
		self.a_avg = np.zeros((sim['L'], sim['N']+1), dtype=np.complex64)
		self.n_avg = np.zeros((sim['L'], sim['N']+1))

	# The simulation loop
	def Run_Simulation(self):
		# Define simulation parameters
		N = self.sim['N']
		L = self.sim['L']
		d = self.sim['d']
		logs = self.logs

		# Define operators
		ops = Operators(self.model, self.sim)
		V_odd = ops.V_odd
		V_even = ops.V_even
		V_last = ops.V_last
		a_op = ops.a
		n_op = ops.n_op

		# Create arrays to hold data
		# and store initial values
		if (logs['rho']):
			for r in range(0, L):
				self.rhos[r,0] = self.Single_Site_Rho(r)
		if (logs['a']):
			for r in range(0, L):
				self.a_avg[r,0] = np.trace(np.dot(self.Single_Site_Rho(r), a_op))
		if (logs['n']):
			for r in range(0, L):
				self.n_avg[r,0] = np.trace(np.dot(self.Single_Site_Rho(r), n_op))

		# # Loop: do all the odds, then evens, then odds
		for i in range(1, N+1):
			# Evolve odd links delta * t / 2
			for h in range(0, L-1):
				if h % 2 == 1:
					self.Update(V_odd, h)
			if ((L-1) % 2 == 1):
				self.Update_1site(V_last, L-1)	
			
			# Evolve even links delta * t
			for j in range(0, L-1):
				if j % 2 == 0:
					self.Update(V_even, j)
			if ((L-1) % 2 == 0):
				self.Update_1site(V_last, L-1)	
			
			# Evolve odd links delta * t / 2
			for k in range(0, L-1):
				if k % 2 == 1:
					self.Update(V_odd, k)
			if ((L-1) % 2 == 1):
				self.Update_1site(V_last, L-1)	
			
			# Log data:
			if (logs['rho'] and i % (logs['skip'] + 1) == 0):
				# Store single particle density matrices
				for r in range(0, L):
					self.rhos[r,i] = self.Single_Site_Rho(r)
			if (logs['a'] and i % (logs['skip'] + 1) == 0):
				# Store expectation values of a
				for r in range(0, L):
					self.a_avg[r,i] = np.trace(np.dot(self.Single_Site_Rho(r), a_op))
			if (logs['n'] and i % (logs['skip'] + 1) == 0):
				# Store expectation values of n
				for r in range(0, L):
					self.n_avg[r,i] = np.trace(np.dot(self.Single_Site_Rho(r), n_op))

			# Can delete this later:
			if (i % 50 == 0):
				print "step {0} done".format(i)


	# Build the Theta tensor
	# NOTE: this definition of Theta DOES NOT agree with the one in
	# the Mishmash thesis.
	# Here we're using an alternate def of Theta to reduce numerical errors.
	# This definition of Theta does not include the Lambdas
	# on the far left and right of the formula,
	# since we want to eventually divide them off anyway.
	def Build_Theta(self, l):
		Lambda = self.Lambda
		Gamma_lp1 = self.Gamma[l+1]
		Gamma_l = self.Gamma[l]

		if (l != 0 and l != self.sim['L']-2):
			theta = np.tensordot(np.diag(Lambda[l,:]), Gamma_lp1, axes=(1,1))
			theta = np.tensordot(Gamma_l, theta, axes=(2,0))

			# # Now indices are [i_l, a_(l-1), i_(l+1), a_(l+1)]
			# # Swap them to [i_l, i_(l+1), a_(l-1), a_(l+1)] to avoid confusion
			theta = np.transpose(theta, (0,2,1,3))

		# Structure of Gamma^(0) and Gamma^(L-1) are different...
		elif (l == 0):
			theta = np.tensordot(np.diag(Lambda[l,:]), Gamma_lp1, axes=(1,1))
			theta = np.tensordot(Gamma_l, theta, axes=(1,0))
			# Indices already [i_l, i_(l + 1), a_(l + 1)]
		elif (l == self.sim['L']-2):
			theta = np.tensordot(np.diag(Lambda[l,:]), Gamma_lp1, axes=(1,1))
			theta = np.tensordot(Gamma_l, theta, axes=(-1,0))
			# Swap indices to be [i_l, i_(l + 1), a_(l - 1)]
			theta = np.transpose(theta, (0,2,1))
		return theta

	# This follows the discussion in
	# http://inside.mines.edu/~lcarr/theses/mishmash_thesis_2008.pdf,
	# section 3.2.3.
	# Note that while the linked thesis indexes from 1,
	# we index from zero here to avoid confusion in the code.
	# Therefore, l runs from [0, ..., L - 1] in our case,
	# instead of [1, ..., L] as shown in the thesis.
	def Update(self, V, l):
		d = self.sim['d']; L = self.sim['L'];
		chi = self.sim['chi']; delta = self.sim['delta']

		# Build the appropriate Theta tensor
		Theta = self.Build_Theta(l)
		# Apply the unitary matrix V
		Theta = np.tensordot(V, Theta, axes=([2,3], [0,1]))
		
		# Need to treat boundary subsystems differently...
		if (l != 0 and l != L - 2):
			# Reshape to a square matrix and do singular value decomposition:
			Theta = np.reshape(np.transpose(Theta, (0,2,1,3)), (d*chi, d*chi))
			# A and transpose.C contain the new Gamma[l] and Gamma[l+1]
			# B contains new Lambda[l]
			A, B, C = np.linalg.svd(Theta)
			C = np.transpose(C)

			# Truncate at chi eigenvalues and enforce normalization
			self.Lambda[l,:] = B[0:chi] / np.linalg.norm(B[0:chi])

			# Keep track of the truncation error accumulated on this step
			self.tau += delta * (1 - np.linalg.norm(B[0:chi])**2)

			# Find the new Gammas:
			# Gamma_l:
			A = np.reshape(A[:, 0:chi], (d, chi, chi))
			# Right multiplying by Lambda_l means that we're effectively storing
			# the A tensors instead of the Gamma tensors.
			# See Quantum Gases: Finite Temperature and Non-Equilibrium Dynamics, pg. 341
			Gamma_l_new = np.tensordot(A, np.diag(self.Lambda[l]), axes=(-1, 0))
			self.Gamma[l] = Gamma_l_new

			# Gamma_(l+1):
			C = np.reshape(C[:, 0:chi], (d, chi, chi))
			Gamma_lp1_new = C
			self.Gamma[l+1] = Gamma_lp1_new

		# The Gamma_0 tensor has one less index... need to treat slightly differently
		elif (l == 0):
			# Reshape to a square matrix and do singular value decomposition:
			Theta = np.reshape(Theta, (d, d*chi))
			# A and transpose.C contain the new Gamma[l] and Gamma[l+1]
			# B contains new Lambda[l]
			A, B, C = np.linalg.svd(Theta)
			C = np.transpose(C)

			# Enforce normalization
			# Don't need to truncate here because chi is bounded by
			# the dimension of the smaller subsystem, here equals d < chi
			self.Lambda[l,0:d] = B / np.linalg.norm(B)

			# Keep track of the truncation error accumulated on this step
			self.tau += delta * (1 - np.linalg.norm(B)**2)

			# Find the new Gammas:
			# Gamma_l:
			# Note: can't truncate because the matrix
			# is smaller than in the non-edge cases
			# Right multiplying by Lambda_l means that we're effectively storing
			# the A tensors instead of the Gamma tensors.
			# See Quantum Gases: Finite Temperature and Non-Equilibrium Dynamics, pg. 341
			self.Gamma[l][:, 0:d] = np.tensordot(A, np.diag(self.Lambda[l,0:d]), axes=(-1, 0))
			# Treat the l = 1 case normally...
			C = np.reshape(C[:, 0:chi], (d, chi, chi))
			Gamma_lp1_new = C
			self.Gamma[l+1] = Gamma_lp1_new

		elif (l == L - 2):
			# Reshape to a square matrix and do singular value decomposition:
			Theta = np.reshape(np.transpose(Theta, (0,2,1)), (d*chi, d))
			# A and transpose.C contain the new Gamma[l] and Gamma[l+1]
			# B contains new Lambda[l]
			A, B, C = np.linalg.svd(Theta)
			C = np.transpose(C)

			# Enforce normalization
			# Don't need to truncate here because chi is bounded by
			# the dimension of the smaller subsystem, here equals d < chi
			self.Lambda[l,0:d] = B / np.linalg.norm(B)

			# Keep track of the truncation error accumulated on this step
			self.tau += delta * (1 - np.linalg.norm(B)**2)

			# Find the new Gammas:
			# Treat the L-2 case normally:
			A = np.reshape(A[:,0:chi], (d, chi, chi))
			# Right multiplying by Lambda_l means that we're effectively storing
			# the A tensors instead of the Gamma tensors.
			# See Quantum Gases: Finite Temperature and Non-Equilibrium Dynamics, pg. 341
			Gamma_l_new = np.tensordot(A, np.diag(self.Lambda[l]), axes=(-1, 0))
			self.Gamma[l] = Gamma_l_new

			# Gamma_(L-1):
			# Note: can't truncate because the matrix
			# is smaller than in the non-edge cases
			self.Gamma[l+1][:,0:d] = C

	# Update from applying a single-site operator.
	# In practice, this will only be used for
	# the on-site term for the final site.
	def Update_1site(self, V, l):
		self.Gamma[l] = np.tensordot(V, self.Gamma[l], axes=(0,0))

	# Calculate the reduced density matrix,
	# tracing over all sites except site k
	# See Mishmash thesis for derivation
	def Single_Site_Rho(self, k):
		L = self.sim['L']

		Gamma_k = self.Gamma[k]
		# Need to treat boundaries differently...
		# See Mishmash thesis pg. 73 for formulas
		if (k != 0 and k != L - 1):
			Rho_L = np.tensordot(np.diag(self.Lambda[k-1,:]), np.conjugate(Gamma_k), axes=(1,1))
			Rho_L = np.tensordot(Rho_L, np.diag(self.Lambda[k,:]), axes=(-1,0))
			Rho_R = np.tensordot(np.diag(self.Lambda[k,:]), Gamma_k, axes=(1,1))
			Rho_R = np.tensordot(Rho_R, np.diag(self.Lambda[k,:]), axes=(-1,0))
			Rho = np.tensordot(Rho_L, Rho_R, axes=([0,2],[0,2]))
			Rho = np.transpose(Rho)
		elif (k == 0):
			Rho_L = np.tensordot(np.conjugate(Gamma_k), np.diag(self.Lambda[k,:]), axes=(-1,0))
			Rho_R = np.tensordot(Gamma_k, np.diag(self.Lambda[k,:]), axes=(-1,-1))
			Rho = np.tensordot(Rho_L, Rho_R, axes=(-1,-1))
			Rho = np.transpose(Rho)
		elif (k == L - 1):
			Rho_L = np.tensordot(np.diag(self.Lambda[k-1,:]), np.conjugate(Gamma_k), axes=(-1,-1))
			Rho_R = np.tensordot(np.diag(self.Lambda[k-1,:]), Gamma_k, axes=(-1, -1))
			Rho = np.tensordot(Rho_L, Rho_R, axes=(0,0))
			Rho = np.transpose(Rho)
		return Rho



# Operator definitions:
# Not really important for this to be a class
class Operators(object):
	def __init__(self, model, sim):
		# Set up ladder operators	
		d = sim['d']
		a = np.zeros((d,d), dtype=np.complex64)
		for i in range(0,d-1):
			a[i, i+1] = math.sqrt(i+1)
		a_dag = np.transpose(a)
		n_op = np.dot(a_dag, a)

		self.a = a
		self.a_dag = a_dag
		self.n_op = n_op
	
		# Set up Hamiltonian
		J = model['J']; U = model['U']; delta = sim['delta']

		# Build two site Hamiltonian:
		H_2site = -J * (np.kron(a_dag, a) + np.kron(a, a_dag)) + (U / 2) * np.kron(np.dot(n_op, n_op - np.identity(d)), np.identity(d))
		# Need to treat the last link differently...
		# Use as a single-site operator
		H_last = (U / 2) * np.dot(n_op, n_op - np.identity(d))
		# Diagonalize 
		w,v = np.linalg.eig(H_2site)
		self.V_odd = np.reshape(np.dot(np.dot(v,np.diag(np.exp(-1j*delta*(w) / 2))), np.transpose(v)), (d,d,d,d))
		self.V_even = np.reshape(np.dot(np.dot(v,np.diag(np.exp(-1j*delta*(w)))), np.transpose(v)), (d,d,d,d))
		# Same thing for last site
		wp, vp = np.linalg.eig(H_last)
		if ((sim['L'] - 1) % 2 == 0):
			self.V_last = np.dot(np.dot(vp,np.diag(np.exp(-1j*delta*(wp)))), np.transpose(vp))
		else:
			self.V_last = np.dot(np.dot(vp,np.diag(np.exp(-1j*delta*(wp) / 2))), np.transpose(vp))


# Helper functions for initialization:

# Initialize state vectors (product state)
# L sites, number cutoff nmax
# n_onsite is the number on each site
# flag: 0 is Fock state, 1 is (truncated) coherent state with mean occupation = n_onsite
# flag = 0: if number_onsite is an integer, initialize n = n_onsite Mott insulator
# 		if not, initialize w/ probability (n_onsite - floor(n_onsite))
# flag = 1: approximate coherent state with alpha = sqrt(n_onsite)
def Initialize_States(sim, init):
	n_max = sim['d']
	L = sim['L']
	n_onsite = init['nbar']
	flag = init['flag']

	# Initialize a matrix of zeros
	mat = np.zeros((L, n_max), dtype=np.complex64)

	# If not coherent states
	if (flag == 0):
		if (math.floor(n_onsite) >= 0):
			# Check that you're under the number cutoff
			if (math.floor(n_onsite) < n_max):
				mat[:,math.floor(n_onsite)] = 1
			# If not, initialize to vacuum
			else:
				return mat

			# Check for fractional occupation
			if (n_onsite != math.floor(n_onsite)):
				filling = n_onsite - math.floor(n_onsite)
				rands = np.random.rand(L)
				# Populate next highest state with probability = filling
				for i in range(0, L):
					if rands[i] < filling:
						mat[i,math.floor(n_onsite)+1] = 1
						mat[i,math.floor(n_onsite)] = 0
	# If coherent state
	elif (flag == 1):
		# Calculate normalization factor
		norm = 0
		for i in range(0, n_max):
			norm += math.pow(n_onsite, i) / math.factorial(i)
		norm = np.sqrt(norm)
		# Build coherent states
		for i in range(0, n_max):
			mat[:,i] = math.pow(n_onsite, float(i) / 2) / (np.sqrt(math.factorial(i)) * norm)
	return mat

# Initialize the coefficient tensors
# See http://inside.mines.edu/~lcarr/theses/mishmash_thesis_2008.pdf,
# Appendix A, assuming product wavefunctions
# Important not to inadverdently cast to real numbers instead of complex!
def lambda0(sim):
	L = sim['L']; chi = sim['chi']
	# From Appendix A, pg. 173
	mat = np.zeros((L-1, chi), dtype=np.complex64)
	mat[:,0] = 1
	return mat

# From Appendix A, pg. 173
def Gamma0(coeffs, sim):
	d = sim['d']; L = sim['L']; chi = sim['chi']
	Gamma = []

	# Note that the first and last Gamma tensors
	# have a different form (two indices instead of three),
	# so they need to be initialized separately
	mat = np.zeros((d, chi), dtype=np.complex64)
	mat[:,0] = coeffs[0,:]
	Gamma.append(mat)

	for i in range(1, L-1):
		mat = np.zeros((d, chi, chi), dtype=np.complex64)
		mat[:, 0, 0] = coeffs[i,:]
		Gamma.append(mat)

	mat = np.zeros((d, chi), dtype=np.complex64)
	mat[:,0] = coeffs[L-1,:]
	Gamma.append(mat)
	return Gamma


### OLD VERSION BELOW ###

# # Model parameters:
# J = 0; U = 20.0;

# # Simulation parameters:
# # d = Number cutoff, chi = Entanglement cutoff,
# # L = Number of sites
# # Note: need chi > d!!!
# d = 8; chi = 50; L = 8; delta = 0.01; N = 100;

# # Class for handling the Lambda, Gamma, and Theta tensors
# class TensorGroup(object):

# 	def __init__(self, coeffs):
# 		self.Lambda = lambda0()
# 		self.Gamma = Gamma0(coeffs)
# 		self.tau = 0

# 	def Build_Theta(self, l):
# 		Lambda = self.Lambda
# 		Gamma_lp1 = self.Gamma[l+1]
# 		Gamma_l = self.Gamma[l]

# 		# Build the Theta tensor
# 		# NOTE: this definition of Theta DOES NOT agree with the one in
# 		# the Mishmash thesis.
# 		# Here we're using an alternate def of Theta to reduce numerical errors.
# 		# This definition of Theta does not include the Lambdas
# 		# on the far left and right of the formula,
# 		# since we want to eventually divide them off anyway.
# 		if (l != 0 and l != L-2):
# 			theta = np.tensordot(np.diag(Lambda[l,:]), Gamma_lp1, axes=(1,1))
# 			theta = np.tensordot(Gamma_l, theta, axes=(2,0))

# 			# # Now indices are [i_l, a_(l-1), i_(l+1), a_(l+1)]
# 			# # Swap them to [i_l, i_(l+1), a_(l-1), a_(l+1)] to avoid confusion
# 			theta = np.transpose(theta, (0,2,1,3))

# 		# Structure of Gamma^(0) and Gamma^(L-1) are different...
# 		elif (l == 0):
# 			theta = np.tensordot(np.diag(Lambda[l,:]), Gamma_lp1, axes=(1,1))
# 			theta = np.tensordot(Gamma_l, theta, axes=(1,0))
# 			# Indices already [i_l, i_(l + 1), a_(l + 1)]
# 		elif (l == L-2):
# 			theta = np.tensordot(np.diag(Lambda[l,:]), Gamma_lp1, axes=(1,1))
# 			theta = np.tensordot(Gamma_l, theta, axes=(-1,0))
# 			# Swap indices to be [i_l, i_(l + 1), a_(l - 1)]
# 			theta = np.transpose(theta, (0,2,1))
# 		return theta

# 	# This follows the discussion in
# 	# http://inside.mines.edu/~lcarr/theses/mishmash_thesis_2008.pdf,
# 	# section 3.2.3.
# 	# Note that while the linked thesis indexes from 1,
# 	# we index from zero here to avoid confusion in the code.
# 	# Therefore, l runs from [0, ..., L - 1] in our case,
# 	# instead of [1, ..., L] as shown in the thesis.
# 	def Update(self, V, l):
# 		# Build the appropriate Theta tensor
# 		Theta = self.Build_Theta(l)
# 		# Apply the unitary matrix V
# 		Theta = np.tensordot(V, Theta, axes=([2,3], [0,1]))
		
# 		# Need to treat boundary subsystems differently...
# 		if (l != 0 and l != L - 2):
# 			# Reshape to a square matrix and do singular value decomposition:
# 			Theta = np.reshape(np.transpose(Theta, (0,2,1,3)), (d*chi, d*chi))
# 			# A and transpose.C contain the new Gamma[l] and Gamma[l+1]
# 			# B contains new Lambda[l]
# 			A, B, C = np.linalg.svd(Theta)
# 			C = np.transpose(C)

# 			# Truncate at chi eigenvalues and enforce normalization
# 			self.Lambda[l,:] = B[0:chi] / np.linalg.norm(B[0:chi])

# 			# Keep track of the truncation error accumulated on this step
# 			self.tau += delta * (1 - np.linalg.norm(B[0:chi])**2)

# 			# Find the new Gammas:
# 			# Gamma_l:
# 			A = np.reshape(A[:, 0:chi], (d, chi, chi))
# 			# Right multiplying by Lambda_l means that we're effectively storing
# 			# the A tensors instead of the Gamma tensors.
# 			# See Quantum Gases: Finite Temperature and Non-Equilibrium Dynamics, pg. 341
# 			Gamma_l_new = np.tensordot(A, np.diag(self.Lambda[l]), axes=(-1, 0))
# 			self.Gamma[l] = Gamma_l_new

# 			# Gamma_(l+1):
# 			C = np.reshape(C[:, 0:chi], (d, chi, chi))
# 			Gamma_lp1_new = C
# 			self.Gamma[l+1] = Gamma_lp1_new

# 		# The Gamma_0 tensor has one less index... need to treat slightly differently
# 		elif (l == 0):
# 			# Reshape to a square matrix and do singular value decomposition:
# 			Theta = np.reshape(Theta, (d, d*chi))
# 			# A and transpose.C contain the new Gamma[l] and Gamma[l+1]
# 			# B contains new Lambda[l]
# 			A, B, C = np.linalg.svd(Theta)
# 			C = np.transpose(C)

# 			# Enforce normalization
# 			# Don't need to truncate here because chi is bounded by
# 			# the dimension of the smaller subsystem, here equals d < chi
# 			self.Lambda[l,0:d] = B / np.linalg.norm(B)

# 			# Keep track of the truncation error accumulated on this step
# 			self.tau += delta * (1 - np.linalg.norm(B)**2)

# 			# Find the new Gammas:
# 			# Gamma_l:
# 			# Note: can't truncate because the matrix
# 			# is smaller than in the non-edge cases
# 			# Right multiplying by Lambda_l means that we're effectively storing
# 			# the A tensors instead of the Gamma tensors.
# 			# See Quantum Gases: Finite Temperature and Non-Equilibrium Dynamics, pg. 341
# 			self.Gamma[l][:, 0:d] = np.tensordot(A, np.diag(self.Lambda[l,0:d]), axes=(-1, 0))
# 			# Treat the l = 1 case normally...
# 			C = np.reshape(C[:, 0:chi], (d, chi, chi))
# 			Gamma_lp1_new = C
# 			self.Gamma[l+1] = Gamma_lp1_new

# 		elif (l == L - 2):
# 			# Reshape to a square matrix and do singular value decomposition:
# 			Theta = np.reshape(np.transpose(Theta, (0,2,1)), (d*chi, d))
# 			# A and transpose.C contain the new Gamma[l] and Gamma[l+1]
# 			# B contains new Lambda[l]
# 			A, B, C = np.linalg.svd(Theta)
# 			C = np.transpose(C)

# 			# Enforce normalization
# 			# Don't need to truncate here because chi is bounded by
# 			# the dimension of the smaller subsystem, here equals d < chi
# 			self.Lambda[l,0:d] = B / np.linalg.norm(B)

# 			# Keep track of the truncation error accumulated on this step
# 			self.tau += delta * (1 - np.linalg.norm(B)**2)

# 			# Find the new Gammas:
# 			# Treat the L-2 case normally:
# 			A = np.reshape(A[:,0:chi], (d, chi, chi))
# 			# Right multiplying by Lambda_l means that we're effectively storing
# 			# the A tensors instead of the Gamma tensors.
# 			# See Quantum Gases: Finite Temperature and Non-Equilibrium Dynamics, pg. 341
# 			Gamma_l_new = np.tensordot(A, np.diag(self.Lambda[l]), axes=(-1, 0))
# 			self.Gamma[l] = Gamma_l_new

# 			# Gamma_(L-1):
# 			# Note: can't truncate because the matrix
# 			# is smaller than in the non-edge cases
# 			self.Gamma[l+1][:,0:d] = C

# 	# Calculate the reduced density matrix,
# 	# tracing over all sites except site k
# 	# See Mishmash thesis for derivation
# 	def Single_Site_Rho(self, k):
# 		Gamma_k = self.Gamma[k]
# 		# Need to treat boundaries differently...
# 		# See Mishmash thesis pg. 73 for formulas
# 		if (k != 0 and k != L - 1):
# 			Rho_L = np.tensordot(np.diag(self.Lambda[k-1,:]), np.conjugate(Gamma_k), axes=(1,1))
# 			Rho_L = np.tensordot(Rho_L, np.diag(self.Lambda[k,:]), axes=(-1,0))
# 			Rho_R = np.tensordot(np.diag(self.Lambda[k,:]), Gamma_k, axes=(1,1))
# 			Rho_R = np.tensordot(Rho_R, np.diag(self.Lambda[k,:]), axes=(-1,0))
# 			Rho = np.tensordot(Rho_L, Rho_R, axes=([0,2],[0,2]))
# 			Rho = np.transpose(Rho)
# 		elif (k == 0):
# 			Rho_L = np.tensordot(np.conjugate(Gamma_k), np.diag(self.Lambda[k,:]), axes=(-1,0))
# 			Rho_R = np.tensordot(Gamma_k, np.diag(self.Lambda[k,:]), axes=(-1,-1))
# 			Rho = np.tensordot(Rho_L, Rho_R, axes=(-1,-1))
# 			Rho = np.transpose(Rho)
# 		elif (k == L - 1):
# 			Rho_L = np.tensordot(np.diag(self.Lambda[k-1,:]), np.conjugate(Gamma_k), axes=(-1,-1))
# 			Rho_R = np.tensordot(np.diag(self.Lambda[k-1,:]), Gamma_k, axes=(-1, -1))
# 			Rho = np.tensordot(Rho_L, Rho_R, axes=(0,0))
# 			Rho = np.transpose(Rho)
# 		return Rho


# # Helper functions for initialization:

# # Initialize state vectors (product state)
# # L sites, number cutoff nmax
# # n_onsite is the number on each site
# # flag: 0 is Fock state, 1 is (truncated) coherent state with mean occupation = n_onsite
# # flag = 0: if number_onsite is an integer, initialize n = n_onsite Mott insulator
# # 		if not, initialize w/ probability (n_onsite - floor(n_onsite))
# # flag = 1: approximate coherent state with alpha = sqrt(n_onsite)
# def Initialize_States(L, n_max, n_onsite, flag):
# 	# Initialize a matrix of zeros
# 	mat = np.zeros((L, n_max), dtype=np.complex64)

# 	# If not coherent states
# 	if (flag == 0):
# 		if (math.floor(n_onsite) >= 0):
# 			# Check that you're under the number cutoff
# 			if (math.floor(n_onsite) < n_max):
# 				mat[:,math.floor(n_onsite)] = 1
# 			# If not, initialize to vacuum
# 			else:
# 				return mat

# 			# Check for fractional occupation
# 			if (n_onsite != math.floor(n_onsite)):
# 				filling = n_onsite - math.floor(n_onsite)
# 				rands = np.random.rand(L)
# 				# Populate next highest state with probability = filling
# 				for i in range(0, L):
# 					if rands[i] < filling:
# 						mat[i,math.floor(n_onsite)+1] = 1
# 						mat[i,math.floor(n_onsite)] = 0
# 	# If coherent state
# 	elif (flag == 1):
# 		# Calculate normalization factor
# 		norm = 0
# 		for i in range(0, n_max):
# 			norm += math.pow(n_onsite, i) / math.factorial(i)
# 		norm = np.sqrt(norm)
# 		# Build coherent states
# 		for i in range(0, n_max):
# 			mat[:,i] = math.pow(n_onsite, float(i) / 2) / (np.sqrt(math.factorial(i)) * norm)
# 	return mat

# # Initialize the coefficient tensors
# # See http://inside.mines.edu/~lcarr/theses/mishmash_thesis_2008.pdf,
# # Appendix A, assuming product wavefunctions
# # Important not to inadverdently cast to real numbers instead of complex!
# def lambda0():
# 	# From Appendix A, pg. 173
# 	mat = np.zeros((L-1, chi), dtype=np.complex64)
# 	mat[:,0] = 1
# 	return mat

# # From Appendix A, pg. 173
# def Gamma0(coeffs):
# 	Gamma = []

# 	# Note that the first and last Gamma tensors
# 	# have a different form (two indices instead of three),
# 	# so they need to be initialized separately
# 	mat = np.zeros((d, chi), dtype=np.complex64)
# 	mat[:,0] = coeffs[0,:]
# 	Gamma.append(mat)

# 	for i in range(1, L-1):
# 		mat = np.zeros((d, chi, chi), dtype=np.complex64)
# 		mat[:, 0, 0] = coeffs[i,:]
# 		Gamma.append(mat)

# 	mat = np.zeros((d, chi), dtype=np.complex64)
# 	mat[:,0] = coeffs[L-1,:]
# 	Gamma.append(mat)
# 	return Gamma

# # Operator definitions:

# # Build a, a_dag, n, n_2site
# a = np.zeros((d,d), dtype=np.complex64)
# for i in range(0,d-1):
# 	a[i, i+1] = math.sqrt(i+1)
# a_dag = np.transpose(a)
# n_op = np.dot(a_dag, a)
# # Build two site Hamiltonian:
# H_2site = -J * (np.kron(a_dag, a) + np.kron(a, a_dag)) + (U / 2) * np.kron(np.dot(n_op, n_op - np.identity(d)), np.identity(d))
# # Need to treat the last link differently...
# H_last = (U / 2) * np.kron(np.identity(d), np.dot(n_op, n_op - np.identity(d)))
# # Diagonalize 
# w,v = np.linalg.eig(H_2site)
# V_odd = np.reshape(np.dot(np.dot(v,np.diag(np.exp(-1j*delta*(w) / 2))), np.transpose(v)), (d,d,d,d))
# V_even = np.reshape(np.dot(np.dot(v,np.diag(np.exp(-1j*delta*(w)))), np.transpose(v)), (d,d,d,d))
# # Same thing for last site
# wp, vp = np.linalg.eig(H_last)
# V_odd_last = np.reshape(np.dot(np.dot(vp,np.diag(np.exp(-1j*delta*(wp) / 2))), np.transpose(vp)), (d,d,d,d))
# V_even_last = np.reshape(np.dot(np.dot(vp,np.diag(np.exp(-1j*delta*(wp)))), np.transpose(vp)), (d,d,d,d))