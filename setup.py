#!/usr/bin/env python

from setuptools import setup, find_packages
from os.path import join, realpath, dirname

reqs_file = join(dirname(realpath(__file__)), 'requirements.txt')

with open(reqs_file) as f:
    reqs = f.readlines()

setup(version = '0.0.1',
      name = 'mediachain-indexer',
      description = 'Mediachain Indexer - Search, Dedupe, Ingestion.',
      author = 'Mediachain Labs',
      packages = find_packages('.'),
      entry_points = {'console_scripts': ['mediachain-indexer-dedupe = mediachain.indexer.mc_dedupe:main',
                                          'mediachain-indexer-ingest = mediachain.indexer.mc_ingest:main',
                                          'mediachain-indexer-web = mediachain.indexer.mc_web:main',
                                          'mediachain-indexer-test = mediachain.indexer.mc_test:main',
                                          ]
                      },
    url = 'http://mediachain.io',
    install_requires = reqs,
)
