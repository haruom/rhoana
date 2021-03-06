############################################################
# GPU Implementation of Random Forest Classifier - Training
# v0.1
# Seymour Knowles-Barley
############################################################
# Based on c code from:
# http://code.google.com/p/randomforest-matlab/
# License: GPLv2
############################################################

import numpy as np
import os
import sys
import h5py
import glob
import mahotas

features_file = sys.argv[1]
forest_file = sys.argv[2]
output_file = sys.argv[3]

NODE_TERMINAL = -1
NODE_TOSPLIT  = -2
NODE_INTERIOR = -3

# Load the forest settings

model = h5py.File(forest_file, 'r')

treemap = model['/forest/treemap'][...]
nodestatus = model['/forest/nodestatus'][...]
xbestsplit = model['/forest/xbestsplit'][...]
bestvar = model['/forest/bestvar'][...]
nodeclass = model['/forest/nodeclass'][...]

nrnodes = model['/forest/nrnodes'][...];
ntree = model['/forest/ntree'][...];
nclass = model['/forest/nclass'][...];

# Load the features
f = h5py.File(features_file, 'r')

nfeatures = len(f.keys())
image_shape = f[f.keys()[0]].shape
npix = image_shape[0] * image_shape[1]
fshape = (nfeatures, npix)
features = np.zeros(fshape, dtype=np.float32)

for i,k in enumerate(f.keys()):
	features[i,:] = f[k][...].ravel()


# Predict

votes = np.zeros((npix, nclass), dtype=np.int32)

for treei in range(ntree):

	k = np.zeros((npix), dtype=np.int32)

	non_terminal = np.nonzero(nodestatus[treei, k] != NODE_TERMINAL)[0]
	while len(non_terminal) > 0:
		knt = k[non_terminal]
		m = bestvar[treei, knt] - 1
		#Split by a numerical predictor
		choice = 1 * (features[m, non_terminal] > xbestsplit[treei, knt])
		k[non_terminal] = treemap[treei * 2, knt * 2 + choice] - 1
		non_terminal = np.nonzero(nodestatus[treei, k] != NODE_TERMINAL)[0]
		#print "{0} non terminal nodes.".format(len(non_terminal))

	#We found all terminal nodes: assign class label
	#jts[chunki + treei] = nodeclass[treeOffset + k]
	#nodex[chunki + treei] = k + 1
	cast_votes = nodeclass[treei, k] - 1
	votes[range(npix),cast_votes] = votes[range(npix),cast_votes] + 1

	print "Done tree {0} of {1}.".format(treei+1, ntree)

# Save / display results

prob_image = np.reshape(np.float32(votes) / ntree, (image_shape[0], image_shape[1], nclass))

if prob_image.shape[2] == 3:

	output_image_file = output_file + '.allclass.png'
	mahotas.imsave(output_image_file, np.uint8(prob_image * 255))

	win_0 = np.logical_and(prob_image[:,:,0] > prob_image[:,:,1], prob_image[:,:,0] > prob_image[:,:,2])
	win_2 = np.logical_and(prob_image[:,:,2] > prob_image[:,:,0], prob_image[:,:,2] > prob_image[:,:,1])
	win_1 = np.logical_not(np.logical_or(win_0, win_2))

	win_image = prob_image
	win_image[:,:,0] = win_0 * 255
	win_image[:,:,1] = win_1 * 255
	win_image[:,:,2] = win_2 * 255

	output_image_file = output_file + '.winclass.png'
	mahotas.imsave(output_image_file, np.uint8(win_image))

elif prob_image.shape[2] == 2:

	output_image_file = output_file + '.allclass.png'

	out_image = np.zeros((prob_image.shape[0], prob_image.shape[1], 3), dtype=np.uint8)
	out_image[:,:,0] = prob_image[:,:,0] * 255
	out_image[:,:,1] = prob_image[:,:,1] * 255
	out_image[:,:,2] = prob_image[:,:,0] * 255
	mahotas.imsave(output_image_file, out_image)

	win_0 = prob_image[:,:,0] > prob_image[:,:,1]
	win_1 = np.logical_not(win_0)

	win_image = np.zeros((prob_image.shape[0], prob_image.shape[1], 3), dtype=np.uint8)
	win_image[:,:,0] = win_0 * 255
	win_image[:,:,1] = win_1 * 255
	win_image[:,:,2] = win_0 * 255

	output_image_file = output_file + '.winclass.png'
	mahotas.imsave(output_image_file, win_image)

temp_path = output_file + '_tmp'
out_hdf5 = h5py.File(temp_path, 'w')
# copy the probabilities for future use
probs_out = out_hdf5.create_dataset('probabilities',
                                    data = prob_image,
                                    chunks = (64,64,1),
                                    compression = 'gzip')
out_hdf5.close()

if os.path.exists(output_file):
    os.unlink(output_file)
os.rename(temp_path, output_file)

print '{0} done.'.format(features_file)
