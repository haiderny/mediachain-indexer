#!/usr/bin/env python

import os
from mc_generic import intget

## Getty key, for creating local dump of getty images:

MC_GETTY_KEY = os.environ.get('MC_GETTY_KEY', '')

## One or more comma-separated RFC-1738 formatted URLs:
# e.g. MC_ES_URLS = 'http://user:secret@localhost:9200/,https://user:secret@other_host:443/production'

MC_ES_URLS = intget(os.environ.get('MC_ES_URLS', '')) or ''

## Elasticsearch index & doc type for image docs (identified by Media IDs):

MC_INDEX_NAME = os.environ.get('MC_INDEX_NAME', '') or 'getty_test'
MC_DOC_TYPE = os.environ.get('MC_DOC_TYPE', '') or 'image'
MC_NUMBER_OF_SHARDS = intget(os.environ.get('MC_DOC_TYPE', '')) or 1
MC_NUMBER_OF_REPLICAS = intget(os.environ.get('MC_NUMBER_OF_REPLICAS', '')) or 0

## Elasticsearch index & doc type resolving media IDs to cluster IDs:

MC_INDEX_NAME_MID_TO_CID = os.environ.get('MC_INDEX_NAME_MID_TO_CID', '') or 'clustering_baseline_mid_to_cid'
MC_DOC_TYPE_MID_TO_CID = os.environ.get('MC_DOC_TYPE_MID_TO_CID', '') or 'cluster_nums'


## Elasticsearch index & doc type resolving cluster IDs to clusters (list of media IDs):

MC_INDEX_NAME_CID_TO_CLUSTER = os.environ.get('MC_INDEX_NAME_CID_TO_CLUSTER', '') or 'clustering_baseline_cid_to_cluster'
MC_DOC_TYPE_CID_TO_CLUSTER = os.environ.get('MC_DOC_TYPE_CID_TO_CLUSTER', '') or 'clusters'


## Used for ingesting from blockchain:

MC_AWS_ACCESS_KEY_ID = os.environ.get('MC_AWS_ACCESS_KEY_ID', '') or ''
MC_AWS_SECRET_ACCESS_KEY = os.environ.get('MC_AWS_SECRET_ACCESS_KEY', '') or ''
MC_REGION_NAME = os.environ.get('MC_REGION_NAME', '') or ''   #AWS region of DynamoDB instance           
MC_ENDPOINT_URL = os.environ.get('MC_ENDPOINT_URL', '') or '' #AWS endpoint of DynamoDB instance

