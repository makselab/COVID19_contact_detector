# mobile_covid19_tracker

Construct close contact from mobile tracking data. For users coming from makselab's Project `COVID19 K-core tracker` (https://github.com/makselab/COVID19) Please refer to the "running for research" section.

Link for the app we are deploying!
https://www.ceara.gov.br/2020/05/26/governo-lanca-ceara-app-com-servicos-de-saude/

## Production

Deployment code for calculation pipeline as backend of an actual app. 

## Staging

Pipeline of detecting and generating close contact network. Requires deployment of Elasticsearch and Airflow

## Running for research

To running for research on 'COVID19 K-core tracker'. Please download `staging` folder only. And following the below.

1. Install Elasticsearch ver. >= 7.6 (https://www.elastic.co/)
2. Install necessary packages by `pip install requirements.txt`
3. Download the data and extract any folder. 
4. Edit `config_params.yaml` to set parameters of generating network. Set "track.person" field to "levels" and modify the location of files and temp/output folder accordingly. See the comments for details.
5. Edit `config_status.yaml` to make sure the time in "grandata" field is later the the "last run".
6. `cd staging/` and in staging folder, run `python src/data_ingest.py`. This step automatically ingest the raw data into elasticsearch.
7. Run `python research/level_expansion.py` to generate close contact network. You can setting up how many chuncks you are going to expand by modifying the `max_chunk` variable in it. The I/O file/folder and paramter is controled by the `config_params.yaml`.
