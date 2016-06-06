#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Evaluate dedupe and search models against labeled datasets. Do hyper-parameter tuning.

Evaluation types:
   - Precision @ k for search.
   - Precision-recall-curve for dedupe.
"""

import matplotlib.pyplot as plt
import numpy as np
from sklearn.metrics import precision_recall_curve, average_precision_score, classification_report
from sklearn.preprocessing import MinMaxScaler
import matplotlib.pyplot as plt

import mc_ingest
import mc_dedupe
from mc_generic import group, setup_main, raw_input_enter, download_streamed, tcache, pretty_print
from random import sample
from os import mkdir, listdir, makedirs
from os.path import exists
from random import random, shuffle
import requests
import zipfile


def download_ukbench(fn_out = 'datasets/ukbench/ukbench.zip'):
    """
    Dataset:     ukbench:
    Credit:      D. Nistér and H. Stewénius. Scalable recognition with a vocabulary tree.
    Project URL: http://vis.uky.edu/~stewe/ukbench/
    Description: 4 photos of each object. More difficult semantic-similarity test.
    Stats:       6376 images, 4 images per positive set, 2GB zipped
    """
    
    dir_out = 'datasets/ukbench/'
    dir_out_full = 'datasets/ukbench/full/'

    if not exists(dir_out_full):
        makedirs(dir_out_full)
    
    download_streamed(url = 'http://vis.uky.edu/~stewe/ukbench/ukbench.zip',
                      fn = fn_out,
                      use_temp = True,
                      verbose = True,
                      skip_existing = True,
                      )
    
    if len(listdir(dir_out_full)) == 10200:
        return
    
    print 'EXTRACTING...'
    
    with zipfile.ZipFile(fn_out, 'r') as zf:
        zf.extractall(dir_out)
            
    print 'EXTRACTED',dir_out_full,len(listdir(dir_out_full))
    

def iter_ukbench(max_num = 0,
                 do_img_data = True,
                 ):

    fn_out = 'datasets/ukbench/ukbench.zip'
    download_ukbench(fn_out)

    cache_dir = 'datasets/ukbench/cache/'

    if not exists(cache_dir):
        makedirs(cache_dir)
    
    for group_num,grp in enumerate(group(xrange(10199 + 1), 4)):
        for nn in grp:
            
            if nn % 100 == 0:
                print 'iter_ukbench()',nn
            
            if max_num and (nn == max_num):
                return
            
            fn = 'datasets/ukbench/full/ukbench%05d.jpg' % nn
            #print ('fn',fn)

            with open(fn) as f:
                d = f.read()
            
            hh = {'_id': unicode(nn),
                  'group_num':group_num,
                  'fn':fn,
                  }
            
            if do_img_data:
                
                d2 = tcache(cache_dir + 'cache_%05d' % nn,
                            mc_ingest.shrink_and_encode_image,
                            d,
                            )
                
                hh['image_thumb'] = d2

            #number of instances of this semantic object:
            hh['num_instances_this_object'] = 4 
            
            yield hh


def eval(max_num = 500,
         num_queries = 500,
         the_gen = iter_ukbench,
         rep_model_names = ['baseline_ng',
                            'baseline',
                            #'all_true',
                            'random_guess',
                            ],
         ignore_self = False,
         ):
    """
    Main evaluation script.
    """
    
    index_name = 'eval_index'
    doc_type = 'eval_doc'

    precision = {}
    recall = {}
    average_precision = {}

    num_true = 0
    num_false = 0
    
    es = mc_ingest.es_connect()
    
    if es.indices.exists(index_name):
        print ('DELETE_INDEX...', index_name)
        es.indices.delete(index = index_name)
        print ('DELETED')
    
    def iter_wrap():
        # Put in ingest_bulk() format:
        
        for hh in the_gen(max_num):
            
            xdoc = {'_op_type': 'index',
                    '_index': index_name,
                    '_type': doc_type,
                    }
            
            xdoc.update(hh)
            
            for x in rr:
                assert x['num_instances_this_object'] > 1.0,'Dataset needs to have multiple instances of each object.'
            
            yield xdoc

    print 'INSERTING...'
    
    num_inserted = mc_ingest.ingest_bulk(the_gen(max_num),
                                         index_name = index_name,
                                         doc_type = doc_type,
                                         redo_thumbs = False,
                                         )
    print 'INSERTED',num_inserted
    
    print 'DEDUPE...'
    
    num_updated = mc_dedupe.dedupe_reindex(index_name = index_name,
                                           doc_type = doc_type,
                                           duplicate_modes = ['baseline', 'baseline_ng'],
                                           )
    
    print 'DEDUPE_UPDATED',num_updated
    
    # random set of queries
    
    p_at_k = {}

    dedupe_true = {}
    dedupe_prob = {}

    done = {}
        
    for rep_model_name in rep_model_names:

        print 'STARTING',rep_model_name

        done[rep_model_name] = set()
        
        p_at_k[rep_model_name] = {'at_04':0,
                                  'at_10':0,
                                  'at_50':0,
                                  }
        
        if rep_model_name == 'all_true':
            dedupe_true[rep_model_name] = ([1.0] * 500) + ([0.0] * 500)
            dedupe_prob[rep_model_name] = [1.0] * 1000
            continue
        
        if rep_model_name == 'random_guess':
            dedupe_true[rep_model_name] = ([1.0] * 500) + ([0.0] * 500)
            dedupe_prob[rep_model_name] = [random() for x in xrange(1000)]
            continue
        
        rep_model = mc_dedupe.REP_MODEL_NAMES[rep_model_name]()
        
        dedupe_true[rep_model_name] = []
        dedupe_prob[rep_model_name] = []

        # Insert fake zero as shown here? Don't think this actually does much to solve the stability
        #  problems with the P/R curve:
        #  https://github.com/scikit-learn/scikit-learn/issues/4223
        
        dedupe_true[rep_model_name].append(0)
        dedupe_prob[rep_model_name].append(0.0)
        
        for c,hh in enumerate(the_gen(num_queries, do_img_data = False)):
            
            group_num = hh['group_num']
            
            query = rep_model.img_to_es_query(img_fn = hh['fn'])
            
            rr = es.search(index = index_name,
                           doc_type = doc_type,
                           body = query,
                           fields = ['_id', 'group_num'],
                           size = 100,#max_num, #50,
                           timeout = '5s',
                           )
            
            rr = rr['hits']['hits']

            #print ('GOT','query-(id,grp):',(hh['_id'],group_num),'result-(id,grp):',[(x['_id'],x['fields']['group_num'][0]) for x in rr])
            
            at_4 = len([1
                        for x
                        in rr[:4]
                        if (x['fields']['group_num'][0] == hh['group_num']) and (x['_id'] != hh['_id'])
                        ]) / (x['num_instances_this_object'] - 1.0)
            at_10 = len([1
                         for x
                         in rr[:10]
                         if (x['fields']['group_num'][0] == hh['group_num']) and (x['_id'] != hh['_id'])
                         ]) / (x['num_instances_this_object'] - 1.0)
            at_50 = len([1
                         for x
                         in rr[:50]
                         if (x['fields']['group_num'][0] == hh['group_num']) and (x['_id'] != hh['_id'])
                         ]) / (x['num_instances_this_object'] - 1.0)

            p_at_k[rep_model_name]['at_04'] += at_4
            p_at_k[rep_model_name]['at_10'] += at_10
            p_at_k[rep_model_name]['at_50'] += at_50
            
            #print 'at_4',at_4,'at_10',at_10,'at_50',at_50

            #if at_4:
            #    raw_input_enter()
            
            
            ### Dedupe stuff:

            zrr = rr[:]
            shuffle(zrr)
            
            for cc,hh2 in enumerate(zrr):

                #if cc % 50 == 0:
                #    print cc
                
                if (ignore_self) and (hh2['_id'] == hh['_id']):
                    continue

                if ((hh2['_id'], hh['_id']) in done[rep_model_name]) or ((hh2['_id'], hh['_id']) in done[rep_model_name]):
                    continue
                
                
                label = 0
                if hh2['fields']['group_num'][0] == hh['group_num']:
                    label = 1
                
                if True:
                    #attempt to keep these balanced:
                    
                    if num_true > num_false:
                        if label == 1:
                            continue
                    elif num_false > num_true:
                        if label == 0:
                            continue
                
                if label == 1:
                    num_true += 1
                else:
                    num_false += 1

                done[rep_model_name].add((hh2['_id'], hh['_id']))
                
                dedupe_true[rep_model_name].append(label)
                dedupe_prob[rep_model_name].append(hh2['_score'])
            
                
                
            print c, rep_model_name, p_at_k[rep_model_name]

        print 'PRECISION_@_K:',rep_model_name,[(x,100 * y / float(num_queries)) for x,y in p_at_k[rep_model_name].items()]

    ### Plot Precision-Recall curves:

    from math import log

    plt.clf()
    
    for mn in rep_model_names:
        
        if len(dedupe_prob[mn]) == 0:
            # Failed to find any matches at all...
            continue
        
        zz = MinMaxScaler(feature_range=(0, 1))
        dedupe_prob[mn] = zz.fit_transform(dedupe_prob[mn])
        
        precision[mn], recall[mn], _ = precision_recall_curve(dedupe_true[mn],
                                                              dedupe_prob[mn],
                                                              pos_label = 1,
                                                              )
        
        average_precision[mn] = average_precision_score(dedupe_true[mn],
                                                        dedupe_prob[mn],
                                                        average="micro",
                                                        )
    
        print mn,'num_true',num_true,'num_false',num_false
        print mn,'TRUE     ',dedupe_true[mn][:10]
        print mn,'PROB     ',dedupe_prob[mn][:10]
        print mn,'precision',list(precision[mn])[:10]
        print mn,'recall   ',list(recall[mn])[:10]

        if False:
            for thresh in np.linspace(0, 1, 20):
                print
                print 'THRESH:',thresh
                print classification_report(dedupe_true[mn],
                                            (np.array(dedupe_prob[mn]) > thresh),
                                            target_names=['diff','same'],
                                            )
                raw_input_enter()
        
        ### Plot Precision-Recall curve for each class:
        
        plt.plot(recall[mn],
                 precision[mn],
                 label='"{0}" model. Average precision = {1:0.2f}'.format(mn,
                                                                          average_precision[mn],
                                                                          ),
                 )

        print 'PLOTTED',mn
    
    plt.xlim([0.0, 1.0])
    plt.ylim([0.0, 1.05])
    plt.xlabel('Recall')
    plt.ylabel('Precision')
    plt.title('Precision-Recall Curve for Dedupe Task')
    plt.legend(loc="lower right")

    print 'SHOW...'
    
    #plt.show()
    
    fn_out = 'eval.png'
    plt.savefig(fn_out)
    from os import system
    system('open ' + fn_out)
    
    print 'CLEAN_UP...'
    
    if es.indices.exists(index_name):
        print ('DELETE_INDEX...', index_name)
        es.indices.delete(index = index_name)
        print ('DELETED')
    
    print 'PRECISION_@_K:',[(mm,[(x,100 * y / float(num_queries)) for x,y in zz.items()]) for mm,zz in p_at_k.items()]
        
    print 'DONE'


from collections import Counter
from math import sqrt, log, floor, ceil

import struct


class LuceneSmallFloat():
    """
    Emulate Lucene's `SmallFloat`.
    
    See: https://lucene.apache.org/core/4_3_0/core/org/apache/lucene/util/SmallFloat.html
    """
    
    @classmethod
    def floatToRawIntBits(cls, b):
        'Simulate Java library function - convert ieee 754 floating point number to integer:'
        return struct.unpack('>l', struct.pack('>f', b))[0]

    @classmethod
    def intBitsToFloat(cls, b):
        'Simulate Java library function - convert integer to ieee 754 floating point'
        if (b < 2147483647) or (b > -2147483648):
            return struct.unpack('>f', struct.pack('>l', b))[0]
        else:
            assert False,'todo?'
            #return struct.unpack('d', struct.pack('Q', int(bin(b), 0)))[0]

    @classmethod
    def byteToFloat(cls, b, numMantissaBits, zeroExp):
        'Converts an 8 bit float to a 32 bit float.'
        if (b == 0):
            return 0.0
        bits = (b & 0xff) << (24 - numMantissaBits)
        bits += (63 - zeroExp) << 24
        return cls.intBitsToFloat(bits)

    @classmethod
    def floatToByte(cls, f, numMantissaBits, zeroExp):
        'Converts an 8 bit float to a 32 bit float.'
        
        bits = cls.floatToRawIntBits(f)
        smallfloat = bits >> (24 - numMantissaBits)

        if (smallfloat <= ((63 - zeroExp) << numMantissaBits)):
            return (bits <= 0) and 0 or 1

        if (smallfloat >= ((63 - zeroExp) << numMantissaBits) + 0x100):
            return -1

        return smallfloat - ((63 - zeroExp) << numMantissaBits)
    
    @classmethod
    def floatToByte315(cls, f):
        'Simulate Lucene function.'
        
        return cls.floatToByte(f, numMantissaBits=3, zeroExp=15)
        
        bits = cls.floatToRawIntBits(f)
        smallfloat = bits >> (24 - 3)

        if (smallfloat <= ((63 - 15) << 3)):
            return (bits <= 0) and 0 or 1

        if (smallfloat >= ((63 - 15) << 3) + 0x100):
            return -1

        return smallfloat - ((63 - 15) << 3)

    @classmethod
    def byte315ToFloat(cls, b):
        'Simulate Lucene function.'

        return cls.byteToFloat(b, numMantissaBits=3, zeroExp=15)
        
        if (b == 0):
            return 0.0
        bits = (b & 0xff) << (24 - 3)
        bits += (63 - 15) << 24
        return cls.intBitsToFloat(bits)

    @classmethod
    def byte52ToFloat(cls, b):
        return cls.byteToFloat(b, numMantissaBits=5, zeroExp=2)

    @classmethod
    def floatToByte52(cls, f):
        return cls.floatToByte(f, numMantissaBits=5, zeroExp=2) 
    
    @classmethod
    def float_round_trip_315(cls, x):
        return cls.byte315ToFloat(cls.floatToByte315(x))

    @classmethod
    def float_round_trip_52(cls, x):
        return cls.byte52ToFloat(cls.floatToByte52(x))

    @classmethod
    def test(cls):
        ' Test from: http://www.openjems.com/tag/querynorm/'
        from math import sqrt
        assert LuceneSmallFloat.float_round_trip_315(1 / sqrt(13)) == 0.25
        print 'PASSED'

class LuceneScoringClassic():
    """
    Emulate Lucene's classic tf-IDF-based relevance scoring formula.
    """
    
    def __init__(self):
        self.df = Counter()
        self.num_docs = 0
        self.docs = {}
        
    def add_doc(self,
                doc,
                id = False,
                ):
        """
        Args:
            doc: Dict of form {term: count}
        """
        self.df.update({x:1 for x in doc})
        self.num_docs += 1
        
        if id is not False:
            self.docs[id] = doc
        
    def score(self,
              query,
              doc,
              query_boost = 1.0,
              verbose = False,
              ):
        """
        Attempt to exactly replicate Lucene's classic relevance scoring formula:
        
        score(q,d)  =  
                queryNorm(q)  
              · coord(q,d)    
              · ∑ (           
                    tf(t in d)   
                  · idf(t)²      
                  · t.getBoost() 
                  · norm(t,d)    
                ) (t in q)    
    
        Args:
            query:  Dict of form {term: count, ...}
            doc:    Dict of form {term: count, ...}

        See Also:
            No one quite gets the formula right, but have a look at these:
            https://www.elastic.co/guide/en/elasticsearch/guide/master/practical-scoring-function.html
            http://www.openjems.com/tag/querynorm/
        """
        
        assert self.num_docs,'First `add_doc()`.'

        is_hit = len(set(query).intersection(doc)) and True

        if not is_hit:
            return 0.0
        
        ## Computes a score factor based on a term or phrase's frequency in a document:
        query_norm = 1.0 / sqrt(sum([(1.0 + log(self.num_docs / (self.df.get(term, 0.0) + 1.0))) ** 2
                                     for term
                                     in query
                                     ]))

        if verbose:
            print 'query_norm',query_norm,'self.num_docs',self.num_docs
        
        # Rewards documents that contain a higher percentage of the query terms:
        coord = len(set(query).intersection(doc)) / float(len(query))
        
        xx = 0.0
        
        for term in query:
            ## Term frequency of this term in this document:
            tf = sqrt(doc.get(term, 0.0))
            
            ## Inverse of frequency of this term in all documents:
            idf  = (1.0 + log(self.num_docs / (self.df.get(term, 0.0) + 1.0))) ** 2
            
            ## Query-level boost:
            boost = query_boost
            
            ## Field-length norm (number of terms in field), combined with the field-level boost, if any:
            
            if True:
                ## !!! For our needs, we can just assume field_norm is 1.0:
                
                field_norm = 1.0
                
            else:
                ## Full field_norm calculation. Everything here is tricky. Luckily we can ignore it for our needs:
                
                field_length = 1 ## See docs / source for details on this. For our query forms, assume 1.
                
                field_norm = LuceneSmallFloat.float_round_trip_315(boost / sqrt(field_length))
            
            xx += tf * idf * field_norm # * boost + (idf * query_norm)
            
            if verbose:
                print '->tf',tf,'idf(%d,%d)' % (self.num_docs, self.df.get(term,0)),'idf',idf,
                print 'boost',boost,
                print 'field_length',field_length,'field_norm',field_norm,'=xx',tf * idf * boost * field_norm
            
        rr = xx * query_norm * coord

        #rr = floor(rr * 1e8) / 1e8
        
        if verbose:
            print 'xx',xx,'query_norm',query_norm,'coord',coord,'=',rr
        #raw_input_enter()
        
        return rr


class ElasticSearchEmulator():
    """
    Attempts to exactly reproduce the particular subset of ES functionality we use.
    
    Useful for indexer system design without having to make assuptions about Lucene / ES black-box scoring formulas,
    for testing, model evaluation, and hyper-parameter optimization.
    """
    
    def __init__(self,
                 scoring = LuceneScoringClassic(),
                 *args,
                 **kw):

        class indices():
            def exists(self,
                       *args,
                        **kw):
                return False
            
            def delete(self,
                       *args,
                        **kw):
                pass
            
            def create(self,
                       index,
                       body,
                       *args,
                        **kw):
                pass
            
            def refresh(self,
                        index,
                        *args,
                        **kw):
                pass
        
        
        self.indices = indices()

        self.scoring = scoring
        
    def index(self,
              index,
              doc_type,
              id,
              body,
              *args,
              **kw):
        """
        Accept documents of the form:
        
            {'word1':1, 'word2':2, 'word3':3}
        """
        assert id
        assert body
        
        terms = {x:y for x,y in body.items() if not x.startswith('_')}
        
        self.scoring.add_doc(terms,
                             id = id,
                             )
    
    def search(self,
               index,
               doc_type,
               body,
               explain = False,
               *args,
               **kw):
        """
        Accepts only queries of the form:
        
            {'query': {'bool': {'should': [{'term':{'word1':1}}, {'term':{'word2':2}} ] } } } 
        """

        ## Get query back into same format as docs:
        
        qterms = {}
        for xx in [x['term'] for x in body['query']['bool']['should']]:
            qterms.update(xx)
        
        rh = {'hits':{'hits':[]}}
        
        ## Score and sort docs:
        
        xx = []
        for doc_id,doc in self.scoring.docs.iteritems():

            xdoc = doc.copy()
            xdoc['_id'] = doc_id
            
            xx.append((self.scoring.score(qterms,
                                          doc,
                                          ),
                       xdoc
                       ),
                      )
        
        ## Apparently ES moves stuff around like this:
        
        for sc,doc in sorted(xx, reverse = True):
            
            h = {'_id':unicode(doc['_id']),
                 '_type':unicode(doc_type),
                 '_index':unicode(index),
                 '_source':doc,
                 '_score':sc,
                 }
            
            del doc['_id']
            
            if explain:
                h['_explanation'] = {'details':[], 'description':'EMULATOR_NOT_IMPLEMENTED', 'value':sc}
            
            rh['hits']['hits'].append(h)
        
        return rh


def short_ex(rr):
    """
    Condense ES explains.

    Note: Quick throw-away function. Ignore.
    """

    assert False,'WIP'
    
    paths = []

    def ex(rr, depth, path):
        if depth > 2:
            return
        #print rr['description'].replace(' ','_').replace('(','{').replace(')','}').replace(':','') + '(',
        if not rr['details']:
            path.append('=' + str(rr['value']))
            paths.append(path)

        if 'of:' in rr['description']:
            print ' '.join(rr['description'].split()[-2:-1]) + '(',
        else:
            print '<<' + rr['description'] + '>>',
            return

        #print 'func(',
        for c,a in enumerate(rr['details']):
            ex(a, depth + 1, path[:] + [str(rr['description'].replace('\x01', '').replace('\x00', ''))[:50]])
            if c != len(rr['details']) - 1:
                print ',',
        print '=',rr['value'],
        print ')',

    for hit in rr['hits']['hits']:
        ex(hit['_explanation'], 0, [])
        print
        print

    print 
    print 'PATHS:'
    
    for path in paths:
        print 'path',path
        
    raw_input_enter()

    
def test_scoring_sim(docs = ['the brown fox is nice', 'the house is big', 'nice fox', 'the fish is fat', 'fox'],
                     query = 'fox is big',
                     #docs = ['a','b','c','d','e','e'],
                     #query = 'a b v z',
                     index_name = 'query_test',
                     doc_type = 'query_test_doc',
                     ):
    """
    Let's see if we can exactly reproduce the Lucene classic scoring function.

    Run this test to evaluate the simulated index vs real ElasticSearch.
    """
    
    from string import lowercase,letters,digits
    from random import choice
    
    #docs = [choice(lowercase)+choice(lowercase) for x in xrange(10)]
    #query = ' '.join([choice(docs) for x in xrange(2)])

    print 'DOCS:'
    for doc in docs:
        print repr(doc)

    print
    print 'QUERY:'
    print repr(query)

    print
    
    ## This is optional:
    
    qq = {}
    qq_rev = {}
    qq_num = [0]
    
    def doc_to_term_counts(zz):
        """
        Avoid potential problems related to ES analyzers by converting term keys from strings to integer IDs.
        
        If you don't want this, just replace with `Counter(zz.split())`.
        """

        if True:
            # Disabled, seems it's not needed for our "should match" queries.
            return Counter(zz.split())
        else:
            rh = {}
            for w,cnt in Counter(zz.split()).items():
                if w not in qq:
                    qq_num[0] += 1
                    qq[w] = qq_num[0]
                    qq_rev[qq_num[0]] = w
                rh[qq[w]] = cnt
            print (zz,'->',{qq_rev[x]:y for x,y in rh.items()})
            print 'aa',rh
            return rh

    
    ## If you want to test the scoring without the full ES emulator:

    if False:    
        xx = LuceneScoringClassic()
        
        for x in docs:
            #xx.add_doc(Counter(x.split()))
            xx.add_doc(doc_to_term_counts(x))

        for a,b in list(sorted([xx.score(Counter(query.split()), Counter(x.split()))
                                for x
                                in docs
                                ],
                               reverse = True)):
            print 'SCORE',a,b

    
    ## Try multiple ES versions and compare results:
    
    results = []
    
    for es in [ElasticSearchEmulator(),
               mc_ingest.es_connect(),
               ]:

        print
        print 'START',es.__class__.__name__
        
        if es.indices.exists(index_name):
            es.indices.delete(index = index_name)

        es.indices.create(index = index_name,
                          body = {'settings': {'number_of_shards': 1, #must be 1, or scoring has problems.
                                               'number_of_replicas': 0,
                                               },
                                  },
                          #ignore = 400,
                          )

        for c,doc in enumerate(docs):
            es.index(index = index_name,
                     doc_type = doc_type,
                     id = str(c),
                     body = doc_to_term_counts(doc),
                     )
        
        es.indices.refresh(index = index_name)
        
        aa = {'query': {'bool': {'should': [{'term': {x:y}} for x,y in doc_to_term_counts(query).items()] } } } 
        
        rr = es.search(index = index_name,
                       doc_type = doc_type,
                       body = aa,
                       explain = True,
                       )

        ## NOTE: Hits with tied scores are returned from ES in unpredictable order. Let's re-sort using IDs as tie-breakers:
        
        rr['hits']['hits'] = [c for (a,b),c in sorted([((x['_score'], x['_id']),x) for x in rr['hits']['hits']], reverse=True)]
        
        #print pretty_print(rr)

        #short_ex(rr)
        
        for hit in rr['hits']['hits']:
            print '-->score:','%.12f' % hit['_score'],'id:',hit['_id'], 'source:',hit['_source']

        
        results.append((es.__class__.__name__,
                        tuple([x['_id'] for x in rr['hits']['hits'] if x['_score'] > 0.0]),
                        ))

    print
    print 'FINAL_RESULTS:'

    ml = max([len(x) for x,y in results])
    
    first = False
    any_failed = False
    for nm, rr in results:

        print '-->',nm.ljust(ml),
        
        if first is False:
            first = rr
            print 'SAME',
        elif (first != rr):
            any_failed = True
            print 'DIFF',
        else:
            print 'SAME',

        print rr
            
    assert not any_failed,'FAILED'

    print
    print 'ALL_PASSED'

functions=['eval',
           'test_scoring_sim',
           ]

def main():
    setup_main(functions,
               globals(),
               )

if __name__ == '__main__':
    main()

