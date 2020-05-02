import os
import sys
from functools import partial
from glob import glob
from multiprocessing import Pool
from time import time
from datetime import datetime
from geopy.distance import geodesic

import numpy as np
import pandas as pd
import yaml
from elasticsearch import Elasticsearch

# add the path to libary to current dir
sys.path.append(os.path.dirname(__file__))
from espandas import Espandas

# global executer
with open(os.path.dirname(__file__) + '/../config_ontology.yaml','r') as f:
    # raw data ontology
    MAPPING = yaml.safe_load(f)
    
# retrieve active patient
def retrieve_active_patients(patient_file, person_type, input_folder):
    id_col = MAPPING['track.person'][person_type]['id']
    df = pd.read_csv(patient_file)
    files = [f"{input_folder}/{row[id_col]}.csv" for _, row in df.iterrows() if row['has_track']]
    return files

# concat all file results (support list of df or folder string)
def concat_files(input_obj, order_key = None):
    # if input is a folder
    if type(input_obj) == str:
        dfs = []
        for file_ in glob(input_obj + '/*.csv'):
            dfs.append(pd.read_csv(file_))
    else:
        dfs = input_obj
    # concat list of dfs
    df = pd.concat(dfs, axis = 0, ignore_index = True)
    if order_key:
        return df.sort_values(by = order_key)
    else:
        return df

## ========================== Functions of Contact Model =====================
def p_t_1(row, time):
    latest_start = max(row['sourceTime_min'], row['targetTime_min'])
    earliest_end = min(row['sourceTime_max'], row['targetTime_max'])
    delta = (earliest_end - latest_start) / np.timedelta64(1, 'm')
    # calculat time interval overlap
    overlap = max(0, delta)
    return overlap/time

#compute the probability in space
def p_x(row, R):
    #linear approximation from geodesic
    distance_m=abs(geodesic((row['sourceLat_avg'],row['sourceLong_avg']), 
                            (row['targetLat_avg'],row['targetLong_avg'])).km*1000)
    return 1-(distance_m/(R*2))

def probabilistic_model(_input,_time,R,model='continuos'):
    # if there is no tracking
    try:
        df =pd.read_csv(_input)
    # early stop if the patient did not have track
    except FileNotFoundError:
        return pd.DataFrame()
    # singleton, only self contact
    if (df['sourceId'] != df['targetId']).sum() < 1:
        return pd.DataFrame()
    
    # if there is valid contact outside
    # convert time stamp
    for col in ['sourceTime','targetTime_min','targetTime_max']:
        df[col] = pd.to_datetime(df[col])
        
    # Get External link
    df_other = df[df['sourceId'] != df['targetId']]
 
    # get self link subset
    cols = ['sourceRefId','targetTime_min','targetTime_max','targetLat_avg','targetLong_avg']
    df_self = df[df['sourceId'] == df['targetId']][cols]
    # for selflink target == source
    df_self = df_self.rename(columns ={'targetTime_min': 'sourceTime_min',
                                       'targetTime_max': 'sourceTime_max',
                                       'targetLat_avg' : 'sourceLat_avg',
                                       'targetLong_avg': 'sourceLong_avg'})

    # append selflink info
    df_clean = df_other.merge(df_self, on = 'sourceRefId', how = 'inner')
    # apply probability calculation
    pt = df_clean.apply(p_t_1, time = _time, axis = 1)
    px = df_clean.apply(p_x, R = R, axis = 1)
    df_clean['p'] = pt * px
    # only return the positive overlap contact
    df_clean = df_clean[df_clean['p'] > 0]
    # resturn
    return df_clean

#here we compute the iterative polarization for th risky people
def recursive(p):
    p_f=0
    for _p in p:
        p_f +=_p*(1-p_f)
    return p_f

# Perform risj calculatio
def recursive_p(data,rho):
    t_c = MAPPING['track.person']['1st_layer']['time']
    df = data.groupby(['sourceId','sourceDataSrc','targetId','targetDataSrc']).agg({'p':recursive,
                                                                          'sourceTime': min})
    # return only risky person
    
    df =  df.reset_index().rename(columns = {'sourceTime': t_c})
    return df[df['p'] >= rho]

# calculate risky contacts
def calculate_risky_contact(result, files, rho, person_type, patient_list = None, output_folder = None):
    # processing ricky person
    risky_contact = concat_files(result)
    if output_folder:
        risky_contact.drop_duplicates().to_csv(output_folder + '/risky_contacts.csv', index = False)
    # get the list of risky contact
    risky_contact = recursive_p(risky_contact, rho=rho)
    # remove list of known patient
    if patient_list:
        id_p = MAPPING['track.person'][person_type]['id']
        t_p = MAPPING['track.person'][person_type]['time']
        patient_list = pd.read_csv(patient_list)
        risky_contact = risky_contact.merge(patient_list[[id_p,t_p]], left_on = 'targetId', right_on = id_p, how = 'left')
        if t_p + '_y' in risky_contact.columns:
            risky_contact = risky_contact[risky_contact[t_p + '_y'].isna()].drop(columns = t_p + '_y') # if the column name is overlapped
            risky_contact = risky_contact.rename(columns = {t_p + '_x': t_p}) # restore column names
        else:
            risky_contact = risky_contact[risky_contact[t_p].isna()]
    # ouput model result
    sources = len(files)
    contacts = len(pd.unique(risky_contact['targetId']))
    R = contacts / sources
    print(f'Rho {rho}: # of contacts: {contacts}, # of sources: {sources}, R note= {R: .2f}')
    return risky_contact

# result dilivery
def deliver_risky_person(risky_contact, file_name, subset = None):
    t_c = MAPPING['track.person']['1st_layer']['time']
    if subset:
        # Push notificationconsider only app users for risky result delivery
        risky_contact= risky_contact.loc[risky_contact['targetDataSrc']==subset]
    # condense risky contact
    risky_person = risky_contact.drop_duplicates().groupby('targetId')[t_c].min()
    risky_person = risky_person.reset_index(name = t_c)
    # save the file
    risky_person.to_csv(file_name, index = False)

### ============================ function to calculate the read zone =============================

def infected_zones(file_, R = 8):
    Data=pd.read_csv(file_) #read file
    # convert and sort date time
    Data['minTime'] = pd.to_datetime(Data['acquisitionTime'])
    Data['maxTime'] = Data['minTime']
    start_smooth = True
    red_zones = Data # initiate
    # use a while statement aggregate neighbor segments divided by outliers
    while (len(red_zones) != len(Data)) | start_smooth:
        start_smooth = False
        start_run = True
        Data = red_zones.sort_values('minTime')
        red_zones = [] # reset
        # use simple stack / queue to aggregate points
        for _, row in Data.iterrows():
            if start_run: # begin of running
                lat,lng,min_t,max_t =[row['lat']],[row['long']],[row['minTime']],[row['maxTime']]
                x_0=(row['lat'],row['long'])
                start_run = False
            # smaller than diameter 2R, then add segment
            elif geodesic(x_0, (row['lat'],row['long'])).km*1000 < 2*R:
                lat.append(row['lat'])
                lng.append(row['long'])
                min_t.append(row['minTime'])
                max_t.append(row['maxTime'])
                # update dynamic center
                x_0 = (np.mean(lat), np.mean(lng))
            else: # end segment
                # exit and pop all values
                red_zones.append([row['mobileId'],max(max_t), min(min_t), x_0[0], x_0[1]])
                # restart the date we want
                lat,lng,min_t,max_t =[row['lat']],[row['long']],[row['minTime']],[row['maxTime']]
                x_0 = (row['lat'],row['long'])
        # append any remaining queue
        if len(max_t) > 0:
            red_zones.append([row['mobileId'],max(max_t), min(min_t), x_0[0], x_0[1]])
        # organized to redzones
        red_zones = pd.DataFrame(red_zones,columns=['mobileId','maxTime','minTime','lat','long'])
        red_zones = red_zones[red_zones['maxTime'] > red_zones['minTime']]
        red_zones['delta'] = (red_zones['maxTime'] - red_zones['minTime'])/ np.timedelta64(1, 's')
    return red_zones

# run the detectio of red zones
def detect_red_zones(contact_file, person_type, input_folder, R = 8):
    start_time = time()
    # filter with only active contact
    files = retrieve_active_patients(contact_file,person_type, input_folder)
    # for red zone, we consider the patient and contact from all resources.
    with Pool(12) as p:
        dfs = list(p.map(partial(infected_zones, R = R), files))
    df = concat_files(dfs)
    print(f'Get {len(df)} records, Time Lapsed: {(time()-start_time)/60:.2f}min')
    return df
            
## ==================== Select subset of patient from close contact list ===================

# join close contact table one by one
def filter_close_contact(file_, patient_list, id_col):
    print(f'joining: {file_}')
    try:
        df = pd.read_csv(file_)
    except FileNotFoundError:
        print(f'{os.path.basename(file_)} have no contact, skip')
        return pd.DataFrame()
    # select patient subset
    df = df.merge(patient_list[id_col], left_on = 'targetId', right_on = id_col,how = 'inner')
    df = df.drop(columns = [id_col])
    return df

# get the close contact subsets
def select_close_contact_subset(input_file, person_type, query_files, n_workers = 4):
    patient_list = pd.read_csv(input_file) # read patient list
    id_col = MAPPING['track.person'][person_type]['id']
    func = partial(filter_close_contact, patient_list = patient_list, id_col = id_col)
    # usin parallel for processing
    with Pool(n_workers) as p:
        dfs = list(p.map(func, query_files))
    df = pd.concat(dfs).sort_values(['sourceId','sourceTime','targetTime'])
        
    return df.drop_duplicates()