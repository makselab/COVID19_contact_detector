import yaml
from glob import glob
import os
import sys
from functools import partial
from multiprocessing import Pool

# add the directory
sys.path.append(os.path.dirname(__file__) + '/..')
# read the relavant libaries
import lib.lib_close_contact as utils

# read parameter of the step
with open(os.path.dirname(__file__) + '/../config_params.yaml', 'r') as stream:
    params = yaml.safe_load(stream)
    # choose the type of person we want to run
    person_type = params['track.person']['person.type']
    # elasticsearch related parameters
    HOST_URL = params['elasticsearch']['host']
    PORT = params['elasticsearch']['port']
    # I/O settings
    input_folder = params[person_type]['folders']['track']
    output_folder = params[person_type]['folders']['close_contact']
    result_folder = params[person_type]['folders']['result']
    # query parameters
    m_before = params['track.close_contact']['minute.before']
    m_after =  params['track.close_contact']['minute.after']
    min_d =    params['track.close_contact']['distance.minimum']

print(f'running query for "{person_type}"')
# read files
files = glob(input_folder + '/*.csv')
# Track the list of close contact
func = partial(utils.track_close_contact, output_folder = output_folder, person_type = person_type, 
                                          minutes_before = m_before, minutes_after = m_after, distance = min_d,
                                          host_url = HOST_URL, port = PORT, index_prefix = 'fortaleza_')

# Parrellel processing patient to all 
with Pool(11) as p:
    dfs = list(p.map(func, files))

# get the summary
utils.close_contact_summary(dfs, result_folder)

# shorten the list
utils.shorten_close_contact(output_folder, result_folder +'/close_contact_stats.csv')
