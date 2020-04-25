"""
Created on 2020-4-23 
@author: Matteo Serafino, Shaojun Luo
"""
import os
import sys
import yaml
from datetime import datetime
from multiprocessing import Pool
from functools import partial

# add the directory
sys.path.append(os.path.dirname(__file__) + '/..')
# read the relavant libaries
import lib.lib_model as utils

# read parameter and dependencies of the step
with open(os.path.dirname(__file__) + '/../config_params.yaml','r') as f:
    params = yaml.safe_load(f)
    # choose the type of person we want to run
    person_type = params['track.person']['person.type']
    # I/O setting
    input_folder = params[person_type]['folders']['contact.profile']
    output_folder = params[person_type]['folders']['deliver']
    num_cores = params['track.contact']['num.cores']
    # query parameters
    rho     =  params['contact.model']['rho']
    m_after =  params['track.contact']['minute.after']
    max_d =    params['track.contact']['distance.max']
    num_cores =params['track.contact']['num.cores']

# get the list of files for execute
files = utils.retrieve_active_patients(output_folder +'/active_patients.csv', person_type, input_folder)

# assign probability
with Pool(num_cores) as p:
    func = partial(utils.probabilistic_model, output_folder = output_folder,_time = m_after, R = max_d,model='continuos')
    result = list(p.map(func, files))
# final result delivery
risky_contact = utils.deliver_risky_contact(result, files, output_folder, rho)

# Find the first layer
layer_1st = risky_contact[['targetId', 'infectedTime']].drop_duplicates()
layer_1st.to_csv(output_folder + '/active_1st_layer.csv', index = False)

