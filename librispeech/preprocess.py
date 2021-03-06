import os
import librosa
import numpy as np
from scikits.audiolab import Sndfile, play
import collections
import re
import h5py
import pickle
from optparse import OptionParser

parser = OptionParser()
parser.add_option('--root',help='root dir',dest='root',default='LibriSpeech')
parser.add_option('--save',help='save directory',dest='save',default='LibriSpeech/preprocessed/')
parser.add_option('--train',help='train directory',dest='train',default='train-clean-100')
parser.add_option('--nchunks',help='number of chunks to divide data into',dest='nchunks',default=40)
parser.add_option('--script_test',help='sample limit for testing',dest='script_test',default=False)
parser.add_option('--maxnumsamples',help='limit num samples',dest='maxnumsamples',default=1e20)
parser.add_option('--logmel',help='generate logmel',dest='logmel',default=False)
parser.add_option('--cqt',help='generate cqt',dest='cqt',default=False)
parser.add_option('--logmel_stacked',help='generate logmel stacked',dest='logmel_stacked',default=False)
parser.add_option('--cqt_stacked',help='generate cqt stacked',dest='cqt_stacked',default=False)
parser.add_option('--all',help='generate all features',dest='all',default=False)
(options, args) = parser.parse_args()

rootdir         = options.root
savedir         = options.save
traindir        = os.path.join(rootdir,options.train)
validdir        = os.path.join(rootdir,'dev-clean')
testdir         = os.path.join(rootdir,'test-clean')
nchunks         = int(options.nchunks)
script_test     = options.script_test
maxnumsamples   = int(options.maxnumsamples)

print '\n'
if script_test:
    print 'run script test with 20 samples'
    maxnumsamples = 20
    nchunks       = 5
    savedir       = 'preprocess_test'

print 'rootdir       = %s' % rootdir
print 'traindir      = %s' % traindir
print 'validdir      = %s' % validdir
print 'testdir       = %s' % testdir
print 'savedir       = %s' % savedir
print 'nchunks       = %s' % nchunks
print 'maxnumsamples = %s' % maxnumsamples

print '\n'

os.system('mkdir -p %s' % savedir)

#------------------- organize files and process transcriptions --------------------
def loadTxtFile(filepath):
    with open(filepath,'r') as f:
        lines = [l.split(' ') for l in f.read().split('\n')]
    while len(lines[-1]) <= 1:
        #print 'removing',lines[-1]
        lines = lines[:-1]
    lines = {l[0]:{'transcription':' '.join(l[1:]),'txtfile':filepath} for l in lines}
    return lines

def organizeFiles(rootdir):
    lines = {}
    audio = {}
    unknown = {}
    for dirname, subdirlist, filelist in os.walk(rootdir):
        for f in filelist:
            filepath = os.path.join(dirname,f)
            if len(f) >= 4:
                if f[-4:] == '.txt':
                    lines.update(loadTxtFile(filepath))
                elif f[-5:] == '.flac':
                    audio[f.replace('.flac','')] = {'audiofile':filepath}
                else:
                    unknown[f] = {'filepath':filepath}
    files = lines
    for k,v in audio.iteritems():
        files[k]['audiofile'] = v['audiofile']
    
    return files

def getCharMap(files):
    # files should be a list, e.g. [trainfiles, validfiles, testfiles]
    charlist = collections.Counter()
    wordlist = collections.Counter()
    for lines in files:
        for key,data in lines.iteritems():
            transcription = data['transcription']
            for c in transcription:
                charlist[c] += 1
            for w in transcription.split():
                wordlist[w] += 1
    # 1-based indexing for torch
    charmap = {k:i+1 for i,k in enumerate(sorted(charlist.keys()))}
    wordmap = {k:i+1 for i,k in enumerate(sorted(wordlist.keys()))}
    
    charEOS = len(charmap)+1
    wordEOS = len(wordmap)+1
    
    charmap['<eos>'] = charEOS
    wordmap['<eos>'] = wordEOS
    
    return charmap, wordmap

def processTranscriptions(lines,charmap,wordmap):
    charEOS = charmap['<eos>']
    wordEOS = wordmap['<eos>']
    
    for key,data in lines.iteritems():
        transcription = data['transcription']
        data['chars'] = np.array([charmap[c] for c in transcription]+[charEOS])
        data['words'] = np.array([wordmap[w] for w in transcription.split()]+[wordEOS])

#------------------- preprocess audio --------------------
def logmel(filename,n_fft=2048,hop_length=512,nfreqs=None):
    f = Sndfile(filename, 'r')
    data = f.read_frames(f.nframes)
    melspectrogram = librosa.feature.melspectrogram(y=data, sr=f.samplerate, n_fft=n_fft, hop_length=hop_length)
    logmel = librosa.core.logamplitude(melspectrogram)
    if nfreqs != None:
        logmel = logmel[:nfreqs,:]
    energy = librosa.feature.rmse(y=data)
    spectr = np.vstack((logmel,energy))
    delta1 = librosa.feature.delta(spectr,order=1)
    delta2 = librosa.feature.delta(spectr,order=2)

    features = np.vstack((spectr,delta1,delta2))
    return features.T

def logmel_stacked(filename,n_fft=2048,hop_length=512,nfreqs=None):
    f = Sndfile(filename, 'r')
    data = f.read_frames(f.nframes)
    melspectrogram = librosa.feature.melspectrogram(y=data, sr=f.samplerate, n_fft=n_fft, hop_length=hop_length)
    logmel = librosa.core.logamplitude(melspectrogram)
    if nfreqs != None:
        logmel = logmel[:nfreqs,:]
    delta1 = librosa.feature.delta(logmel,order=1)
    delta2 = librosa.feature.delta(logmel,order=2)
    d,L    = logmel.shape
    logmel = logmel.T.reshape(1,L,d)
    delta1 = delta1.T.reshape(1,L,d)
    delta2 = delta2.T.reshape(1,L,d)
    features = np.vstack((logmel,delta1,delta2))
    return features

def CQT(filename, fmin=None, n_bins=84, hop_length=512,nfreqs=None):
    f = Sndfile(filename, 'r')
    data = f.read_frames(f.nframes)
    cqt = librosa.cqt(data, sr=f.samplerate, fmin=fmin, n_bins=n_bins, hop_length=hop_length)
    if nfreqs != None:
        cqt = cqt[:nfreqs,:]
    delta1 = librosa.feature.delta(cqt,order=1)
    delta2 = librosa.feature.delta(cqt,order=2)
    energy = librosa.feature.rmse(y=data)
    features = np.vstack((cqt,delta1,delta2,energy))
    return features.T

def CQT_stacked(filename, fmin=None, n_bins=84, hop_length=512,nfreqs=None):
    f = Sndfile(filename, 'r')
    data = f.read_frames(f.nframes)
    cqt = librosa.cqt(data, sr=f.samplerate, fmin=fmin, n_bins=n_bins, hop_length=hop_length)
    if nfreqs != None:
        cqt = cqt[:nfreqs,:]
    delta1 = librosa.feature.delta(cqt,order=1)
    delta2 = librosa.feature.delta(cqt,order=2)
    d,L    = cqt.shape
    cqt = cqt.T.reshape(1,L,d)
    delta1 = delta1.T.reshape(1,L,d)
    delta2 = delta2.T.reshape(1,L,d)
    features = np.vstack((cqt,delta1,delta2))
    return features

def getFeatures(files,func=logmel,**kwargs):
    for k,f in files.iteritems():
        filepath = f['audiofile']
        f['x'] = func(filepath,**kwargs)

def normalizeFeatures(train,valid,test,pad=1):
    maxlength = 0
    featurelist = []
    for k,f in train.iteritems():
        maxlength = max(maxlength,len(f['x']))
        featurelist.append(f['x'])
    featurelist = np.vstack(featurelist)
    mean = featurelist.mean(axis=0)
    std = featurelist.std(axis=0)

    def normalize_and_pad(files):
        for k,f in files.iteritems():
            mylen = len(f['x'])
            padding = np.zeros((pad,f['x'].shape[1]))
            f['x'] = (f['x']-mean)/std
            f['x'] = np.vstack([padding,f['x'],padding])

    normalize_and_pad(train)
    normalize_and_pad(valid)
    normalize_and_pad(test)

    return mean, std

def normalizeStackedFeatures(train,valid,test,pad=1):
    maxlength = 0
    featurelist = []
    for k,f in train.iteritems():
        maxlength = max(maxlength,len(f['x']))
        featurelist.append(f['x'])
    featurelist = np.concatenate(featurelist,axis=1)
    a,b,c = featurelist.shape
    mean = featurelist.mean(axis=1).reshape(a,1,c)
    std = featurelist.std(axis=1).reshape(a,1,c)

    def normalize_and_pad(files):
        for k,f in files.iteritems():
            mylen = len(f['x'])
            padding = np.zeros((3,pad,f['x'].shape[2]))
            f['x'] = (f['x']-mean)/std
            f['x'] = np.concatenate([padding,f['x'],padding],axis=1)

    normalize_and_pad(train)
    normalize_and_pad(valid)
    normalize_and_pad(test)

    return mean, std

def pickleIt(X,outputName):
    with open(outputName,'wb') as f:
        pickle.dump(X,f)
        
def files2HDF5(files,filename):
    with h5py.File(filename,'w') as h:
        for i,f in enumerate(files.values()):
            grp           = h.create_group(str(i))
            grp['x']      = f['x']
            grp['chars']  = f['chars']
            grp['words']  = f['words']

def dict2HDF5(dct,filename):
    with h5py.File(filename,'w') as h:
        for k,v in dct.iteritems():
            if isinstance(v,np.ndarray):
                h[k] = v
            else:
                print 'ignored %s' % k

def chunks2HDF5(chunks,filepath,ext='.h5'):
    db = []
    n = len(chunks)
    for i,chunk in enumerate(chunks):
        myfilepath = '%s%s%s' % (filepath,i,ext)
        db.append(myfilepath)
        files2HDF5(chunk,myfilepath)
    return db


def chunkIt(files,nchunks=1):
    nfiles = len(files)
    chunksize = nfiles/nchunks + 1
    count = 0
    chunks = []
    for k,v in files.iteritems():
        if count % chunksize == 0:
            chunk = {}
            chunks.append(chunk)
        chunk[k] = v
        count += 1
    return chunks
        
def savelist(lst,filepath):
    with open(filepath,'w') as f:
        for l in lst:
            f.write('%s\n' % l)

def savedict(dct,filepath):
    with open(filepath,'w') as f:
        for k,v in sorted(list(dct.iteritems()),key=lambda x:x[1]):
            f.write('%s %s\n' % (k,v))

def featurePreprocessing(subdirname,func,normfunc,**kwargs):
    print '\ngenerate %s features' % subdirname
    getFeatures(trainfiles,func=func,**kwargs)
    getFeatures(validfiles,func=func,**kwargs)
    getFeatures(testfiles,func=func,**kwargs)

    print 'normalize %s features' % subdirname
    mean, std = normfunc(trainfiles,validfiles,testfiles,pad=1)

    print 'gather metadata'
    meta = {}
    meta['inputFrameSize'] = trainfiles.values()[0]['x'].shape[-1]
    meta['trainsamples']   = len(trainfiles)
    meta['validsamples']   = len(validfiles)
    meta['testsamples']    = len(testfiles)
    meta['numchars']       = len(charmap)
    meta['numwords']       = len(wordmap)
    for k,v in meta.iteritems():
        print '-',k,v

    subdir = os.path.join(savedir,subdirname)
    print 'save to %s' % subdir
    os.system('mkdir -p %s' % subdir)
    trainChunked = chunkIt(trainfiles,nchunks)
    db = chunks2HDF5(trainChunked,os.path.join(subdir,'train'))
    savelist(db,os.path.join(subdir,'train.db'))
    files2HDF5(validfiles,os.path.join(subdir,'valid.h5'))
    files2HDF5(testfiles,os.path.join(subdir,'test.h5'))
    savedict(meta,os.path.join(subdir,'meta.txt'))
    dict2HDF5({'mean':mean,'std':std},os.path.join(subdir,'mean_std.pkl'))

    print 'finished %s' % subdirname


#----------------- run -----------------------
print 'organize files and generate maps'
trainfiles = organizeFiles(traindir)
validfiles = organizeFiles(validdir)
testfiles  = organizeFiles(testdir)
charmap, wordmap = getCharMap([trainfiles,validfiles,testfiles])

# limit number of samples
if len(trainfiles) > maxnumsamples:
    trainfiles = {k:trainfiles[k] for k in trainfiles.keys()[:maxnumsamples]}
    print '-reducing training set size to %s samples' % (len(trainfiles)) 
if len(validfiles) > maxnumsamples:
    validfiles = {k:validfiles[k] for k in validfiles.keys()[:maxnumsamples]}
    print '-reducing validation set size to %s samples' % (len(validfiles)) 
if len(testfiles) > maxnumsamples:
    testfiles  = {k:testfiles[k]  for k in testfiles.keys()[:maxnumsamples]}
    print '-reducing test set size to %s samples' % (len(testfiles)) 

print 'save charmap and wordmap'
savedict(charmap, os.path.join(savedir,'charmap.txt'))
savedict(wordmap, os.path.join(savedir,'wordmap.txt'))

print 'process transcriptions'
processTranscriptions(trainfiles,charmap,wordmap)
processTranscriptions(validfiles,charmap,wordmap)
processTranscriptions(testfiles,charmap,wordmap)

# logmel
if options.all or options.logmel:
    featurePreprocessing('logmel',func=logmel,normfunc=normalizeFeatures,nfreqs=40)

# logmel_stacked
if options.all or options.logmel_stacked:
    featurePreprocessing('logmel_stacked',func=logmel_stacked,normfunc=normalizeStackedFeatures,nfreqs=40)

# CQT
if options.all or options.cqt:
    featurePreprocessing('CQT',func=CQT,normfunc=normalizeFeatures)

# CQT stacked
if options.all or options.cqt_stacked:
    featurePreprocessing('CQT_stacked',func=CQT_stacked,normfunc=normalizeStackedFeatures)

