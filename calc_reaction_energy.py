from ase import Atoms
from ase.build import add_adsorbate
from ase.visualize import view
from ase.calculators.vasp import Vasp
from ase.calculators.emt import EMT
from ase.collections import g2
from ase.db import connect
from ase.optimize import BFGS
from tools import fix_lower_surface
from reaction_tools import get_reac_and_prod, get_number_of_reaction
import sys
import json
import os
import pandas as pd
import numpy as np
import argparse
import shutil
import socket

# whether to cleanup working directory for vasp
clean   = False
# save figures for structure
savefig = False
# whether to do sigle point energy calculation after geometry optimization
do_single_point = False
# whether to keep cell shape (i.e. ISIF=4 or 7)
keep_cell_shape = True
# whether to check coordinate by view
check  = False

# workdir to store vasp data
#workdir = ""
workdir = "/work/a_ishi/"

parser = argparse.ArgumentParser()
parser.add_argument("--id", help="id for surface system")
parser.add_argument("--calculator", default="emt", choices=["emt", "EMT", "vasp", "VASP"])
parser.add_argument("--surf_json",  default="surf.json", help="json for surfaces")
parser.add_argument("--reac_json",  default="reaction_energy.json", help="file to write reaction energy")

args = parser.parse_args()
unique_id  = args.id
calculator = args.calculator.lower()
surf_json  = args.surf_json
reac_json  = args.reac_json
#
# temprary database to avoid overlapping calculations
#
tmpdbfile = 'tmp.db'
tmpdbfile = os.path.join(os.getcwd(), tmpdbfile)
tmpdb = connect(tmpdbfile)

# molecule collection from ase
collection = g2

# surface information
nlayer = 4
#nlayer = 14
nrelax = nlayer // 2

if not os.path.isfile(reac_json):
	# reac_json does not exist -- make
	with open(reac_json, "w") as f:
		f.write(json.dumps([], indent=4))

print("hostname: ", socket.gethostname())
print("id: ", unique_id)

db = connect(surf_json)
steps = 100 # maximum number of geomtry optimization steps

if "vasp" in calculator:
	prec   = "normal"
	xc     = "beef-vdw"
	#xc     = "pbe"
	ivdw   = 0
	nsw    = 0  # steps
	nelm   = 40
	nelmin = 5
	ibrion = -1
	potim  = 0.2
	algo   = "VeryFast"  # sometimes VeryFast fails
	ismear = 1
	sigma  = 0.2
	ediff  = 1.0e-4
	ediffg = -0.05
	kpts   = [1, 1, 1]
	ispin  = 2
	kgamma = True
	pp     = "potpaw_PBE.54"
	npar   = 6
	nsim   = npar
	isym   = 0
	lreal  = True
	lorbit = 10  # to avoid error
	lwave  = True if do_single_point else False
	lcharg = True if do_single_point else False

	ldipol = True
	idipol = 3

	calc_mol  = Vasp(prec=prec, xc=xc, ivdw=ivdw, algo=algo, ediff=ediff, ediffg=ediffg, ibrion=ibrion, potim=potim, nsw=nsw,
					 nelm=nelm, nelmin=nelmin, kpts=[1, 1, 1], kgamma=True,ispin=ispin,  pp=pp, npar=npar, nsim=nsim, isym=isym,
					 lreal=lreal, lwave=lwave, lcharg=lcharg, ismear=0, sigma=sigma, lorbit=lorbit)
	calc_surf = Vasp(prec=prec, xc=xc, ivdw=ivdw, algo=algo, ediff=ediff, ediffg=ediffg, ibrion=ibrion, potim=potim, nsw=nsw,
					 nelm=nelm, nelmin=nelmin, kpts=kpts, kgamma=kgamma, ispin=ispin, pp=pp, npar=npar, nsim=nsim, isym=isym,
					 lreal=lreal, lwave=lwave, lcharg=lcharg, ismear=ismear, sigma=sigma, lorbit=lorbit, ldipol=ldipol, idipol=idipol)
elif "emt" in calculator:
	calc_mol  = EMT()
	calc_surf = EMT()
	optimize_unitcell = False
else:
	print("currently VASP or EMT is supported ... quit")
	sys.exit(1)
	
height = 1.4

def set_unitcell_gasphase(Atoms, vacuum=10.0):
	cell = np.array([1, 1, 1]) * vacuum
	Atoms.set_cell(cell)
	if "vasp" in calculator:
		Atoms.set_pbc(True)


def set_calculator_with_directory(Atoms, calc, directory="."):
	if "vasp" in calculator:
		calc.directory = directory
	Atoms.set_calculator(calc)


def run_optimizer(atoms, steps=100, optimize_unitcell=False, keep_cell_shape=False):
	calc = atoms.get_calculator()

	if "vasp" in calculator:
		# VASP
		calc.int_params["ibrion"]  = 2
		calc.int_params["nsw"]     = steps
		calc.input_params["potim"] = potim
		calc.exp_params["ediffg"]  = ediffg

		if optimize_unitcell:
			if keep_cell_shape:
				# step1: cell volume
				calc.int_params["isif"]    = 7
				calc.int_params["nsw"]     = steps
				calc.input_params["potim"] = potim
				calc.exp_params["ediffg"]  = ediff * 0.1  # energy based
				atoms.set_calculator(calc)
				atoms.get_potential_energy()

				# step2: ionic 
				calc.int_params["isif"]   = 2
				calc.exp_params["ediffg"] = ediffg
				atoms.set_calculator(calc)
			else:
				# ionic + cell
				calc.int_params["isif"]   = 4
				calc.exp_params["ediffg"] = ediff * 0.1  # energy based
				atoms.set_calculator(calc)
		else:
			# ionic
			calc.int_params["isif"]    = 2
			calc.int_params["nsw"]     = steps
			calc.input_params["potim"] = potim
			calc.exp_params["ediffg"]  = ediffg
	else:
		# EMT
		opt = BFGS(atoms)
		opt.run(fmax=0.1, steps=steps)
		en = atoms.get_potential_energy()

	# do calculation
	en = atoms.get_potential_energy()

	#
	# reset vasp calculator to single point energy's one
	#
	if "vasp" in calculator:
		if do_single_point:
			calc.int_params["ibrion"]  = -1
			calc.int_params["nsw"]     =  0
			calc.int_params["isif"]    =  2
			calc.int_params["istart"]  =  1
			calc.int_params["icharg"]  =  1
			calc.input_params["potim"] =  0
			atoms.set_calculator(calc)

	return en, atoms


def get_mol_type(mol, site):
	if site == 'gas':
		if 'surf' in mol:
			mol_type = 'surf'
		else:
			mol_type = 'gaseous'
	else:
		mol_type = 'adsorbed'

	return mol_type


def add_to_json(jsonfile, data):
	#
	# add data to database
	#
	with open(jsonfile, "r") as f:
	# remove "doing" record as calculation is done
		datum = json.load(f)
		for i in range(len(datum)):
			if (datum[i]["unique_id"] == unique_id) and (datum[i]["status"] == "doing"):
				datum.pop(i)
				break

		datum.append(data)

	with open(jsonfile, "w") as f:
		json.dump(datum, f, indent=4)


def savefig_atoms(atoms, filename):
	import matplotlib.pyplot as plt
	from ase.visualize.plot import plot_atoms
	fig,ax = plt.subplots()
	#plot_atoms(atoms, ax, rotation='280x,0y,0z')
	plot_atoms(atoms, ax, rotation='0x,0y,0z')
	ax.set_axis_off()
	fig.savefig(filename)


# --------------------- end functions

reactionfile = "nh3.txt"
(r_ads, r_site, r_coef,  p_ads, p_site, p_coef) = get_reac_and_prod(reactionfile)
rxn_num = get_number_of_reaction(reactionfile)

surf = db.get_atoms(unique_id=unique_id).copy()

try:
	df_reac = pd.read_json(reac_json)
	df_reac = df_reac.set_index("unique_id")
except:
	# blanck json file --- going
	pass
	
if unique_id in df_reac.index:
	if "reaction_energy" in df_reac.loc[unique_id]:
		deltaE = df_reac.loc[unique_id].reaction_energy
		print("already done")
		sys.exit(0)
	elif df_reac.loc[unique_id]["status"] == "doing":
		print("somebody is doing")
		sys.exit(0)
 
# no one is doing this system ... calculate here
#with open(reac_json, "r") as f:
#	datum = json.load(f)
#	data  = {"unique_id": unique_id, "status": "doing"}
#	datum.append(data)
#with open(reac_json, "w") as f:
#	json.dump(datum, f, indent=4)

deltaE = np.array([])

print(" --- calculating %s ---" % surf.get_chemical_formula())
for irxn in range(rxn_num):
	print("irxn = %d" % irxn)

	energies = {"reactant": 0.0, "product": 0.0}

	for side in ["reactant", "product"]:
		if side == "reactant":
			mols  = r_ads[irxn]
			sites = r_site[irxn]
			coefs = r_coef[irxn]
		elif side == "product":
			mols  = p_ads[irxn]
			sites = p_site[irxn]
			coefs = p_coef[irxn]

		E = 0.0
		for imol, mol in enumerate(mols):
			if mol[0] == "surf":
				chem = mol[0]
			else:
				chem = collection[mol[0]]

			site = sites[imol][0]
			mol_type = get_mol_type(chem, site)

			if mol_type == "gaseous":
				# gas-phase species
				atoms = Atoms(chem)
				if check: view(atoms)
				set_unitcell_gasphase(atoms)
				atoms.center()
				calc = calc_mol
				optimize_unitcell = False

			elif mol_type == "surf":
				# bare surface
				atoms = surf.copy()
				if check: view(atoms)
				atoms = fix_lower_surface(atoms, nlayer, nrelax)
				atoms.set_initial_magnetic_moments(magmoms=[0.01]*len(atoms))
				calc = calc_surf
				optimize_unitcell = True
 
			elif mol_type == "adsorbed":
				# adsorbate calculation
				chem = collection[mol[0]]
				chem.rotate(180, "y")
				if site == "atop":
					#offset = (0.50, 0.50)  # for [2, 2] supercell
					#offset = (0.33, 0.33)  # for [3, 3] supercell
					offset = (0.40, 0.50)  # for stepped
				elif site == "fcc":
					#offset = (0.33, 0.33)  # for [2, 2] supercell
					#offset = (0.20, 0.20)  # for [3, 3] supercell
					offset = (0.22, 0.30)  # for stepped
				else:
					offset = (0.50, 0.50)

				surf_formula = surf.get_chemical_formula()
				name = surf_formula + "gas" + unique_id
				past  = tmpdb.get(name=name)
				surf  = tmpdb.get_atoms(id=past.id)
				atoms = surf

				atoms = fix_lower_surface(atoms, nlayer, nrelax)
				add_adsorbate(atoms, chem, offset=offset, height=height)
				atoms.set_initial_magnetic_moments(magmoms=[0.01]*len(atoms))
				calc  = calc_surf
				optimize_unitcell = False
			else:
				print("something wrong in determining mol_type")
				sys.exit(1)
			#
			# Identification done. Look for temporary database
			# for identical system.
			#
			formula = atoms.get_chemical_formula()
			try:
				past = tmpdb.get(name = formula + site + unique_id)
			except:
				first_time = True
			else:
				if site == past.data.site:
					if len(mol) == 1:
						# found in tmpdb
						atoms = tmpdb.get_atoms(id=past.id)
						first_time = False

			dir = workdir + unique_id + "_" + formula
			set_calculator_with_directory(atoms, calc, directory=dir)

			first_or_not = "first time" if first_time else "already calculated"
			print("now calculating {0:>12s} ... {1:s}".format(formula, first_or_not))
			if first_time:
				if do_single_point:
					# geometry optimization + single point energy calculation
					sys.stdout.flush()
					en, atoms = run_optimizer(atoms, steps=steps, optimize_unitcell=optimize_unitcell)
					sys.stdout.flush()
					en = atoms.get_potential_energy() # single point
				else:
					# geometry optimization only
					sys.stdout.flush()
					en, atoms = run_optimizer(atoms,  steps=steps, optimize_unitcell=optimize_unitcell, keep_cell_shape=keep_cell_shape)

				if savefig and mol_type == "adsorbed":
					savefig_atoms(atoms, "{0:s}_{1:02d}_{2:02d}.png".format(dir, irxn, imol))
				if clean and "vasp" in calculator:
					shutil.rmtree(dir)

			else:
				past = tmpdb.get(id=past.id)
				en = past.data.energy

			E += coefs[imol]*en

			# recording to database
			if(first_time):
				id = tmpdb.reserve(name = formula + site + unique_id)
				if id is None: # somebody is writing to db
					continue
				else:
					name = formula + site + unique_id
					tmpdb.write(atoms, name=name, id=id, data={"energy": en, "site": site})

		energies[side] = E


	dE = energies["product"] - energies["reactant"]
	deltaE = np.append(deltaE, dE)
	print("reaction energy = %8.4f" % dE)

	if abs(dE) > 10.0:
		print("errorous reaction energy ... quit")
		sys.exit(1)
	#
	# done
	#
if check: view(surf)

data = {"unique_id": unique_id, "reaction_energy": list(deltaE)}
add_to_json(reac_json, data)


