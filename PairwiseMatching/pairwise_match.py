import sys
from collections import defaultdict
import numpy as np
import os

import h5py
import fast64counter

import time


Debug = False

block1_path, block2_path, direction, halo_size, outblock1_path, outblock2_path = sys.argv[1:]
direction = int(direction)
halo_size = int(halo_size)

###############################
# Note: direction indicates the relative position of the blocks (1, 2, 3 =>
# adjacent in X, Y, Z).  Block1 is always closer to the 0,0,0 corner of the
# volume.
###############################

###############################
# Note that we are still in matlab hdf5 coordinates, so everything is stored ZYX
###############################

###############################
#Change joining thresholds here
###############################
#Join 1 (less joining)
auto_join_pixels = 20000; # Join anything above this many pixels overlap
minoverlap_pixels = 2000; # Consider joining all pairs over this many pixels overlap
minoverlap_dual_ratio = 0.7; # If both overlaps are above this then join
minoverlap_single_ratio = 0.9; # If either overlap is above this then join

# Join 2 (more joining)
# auto_join_pixels = 10000; # Join anything above this many pixels overlap
# minoverlap_pixels = 1000; # Consider joining all pairs over this many pixels overlap
# minoverlap_dual_ratio = 0.5; # If both overlaps are above this then join
# minoverlap_single_ratio = 0.8; # If either overlap is above this then join


print 'Running pairwise matching', " ".join(sys.argv[1:])

# Extract overlapping regions
for ntry in range(5):
    try:
        bl1f = h5py.File(block1_path, 'r')
        block1 = bl1f['labels'][...]
        label_chunks = bl1f['labels'].chunks
        if 'merges' in bl1f:
            previous_merges1 = bl1f['merges'][...]
        else:
            previous_merges1 = None
        bl1f.close()

        bl2f = h5py.File(block2_path, 'r')
        block2 = bl2f['labels'][...]
        if 'merges' in bl2f:
            previous_merges2 = bl2f['merges'][...]
        else:
            previous_merges2 = None
        bl2f.close()

    except IOError:
        print "IOError reading hdf5 (try {0}). Waiting...".format(ntry)
        time.sleep(10)
        pass

assert block1.size == block2.size

# append the blocks, and pack them so we can use the fast 64-bit counter
stacked = np.vstack((block1, block2))
inverse, packed = np.unique(stacked, return_inverse=True)
packed = packed.reshape(stacked.shape)
packed_block1 = packed[:block1.shape[0], :, :]
packed_block2 = packed[block1.shape[0]:, :, :]

# extract overlap

lo_block1 = [0, 0, 0];
hi_block1 = [None, None, None]
lo_block2 = [0, 0, 0];
hi_block2 = [None, None, None]

# Adjust for Matlab HDF5 storage order
#direction = 3 - direction
direction = direction - 1

# Adjust overlapping region boundaries for direction
lo_block1[direction] = - 2 * halo_size
hi_block2[direction] = 2 * halo_size;

block1_slice = tuple(slice(l, h) for l, h in zip(lo_block1, hi_block1))
block2_slice = tuple(slice(l, h) for l, h in zip(lo_block2, hi_block2))
packed_overlap1 = packed_block1[block1_slice]
packed_overlap2 = packed_block2[block2_slice]
print "block1", block1_slice, packed_overlap1.shape
print "block2", block2_slice, packed_overlap2.shape

counter = fast64counter.ValueCountInt64()
counter.add_values_pair32(packed_overlap1.astype(np.int32).ravel(), packed_overlap2.astype(np.int32).ravel())
overlap_labels1, overlap_labels2, overlap_areas = counter.get_counts_pair32()

areacounter = fast64counter.ValueCountInt64()
areacounter.add_values(packed_overlap1.ravel())
areacounter.add_values(packed_overlap2.ravel())
areas = dict(zip(*areacounter.get_counts()))

if Debug:
    from libtiff import TIFF
    for image_i in range(block1.shape[2]):
        tif = TIFF.open('block1_z{0:04}.tif'.format(image_i), mode='w')
        tif.write_image(np.uint8(block1[:, :, image_i] * 13 % 251))
        tif = TIFF.open('block2_z{0:04}.tif'.format(image_i), mode='w')
        tif.write_image(np.uint8(block2[:, :, image_i] * 13 % 251))
    for image_i in range(packed_overlap1.shape[2]):
        tif = TIFF.open('packed_overlap1_z{0:04}.tif'.format(image_i), mode='w')
        tif.write_image(np.uint8(packed_overlap1[:, :, image_i] * 13 % 251))
        tif = TIFF.open('packed_overlap2_z{0:04}.tif'.format(image_i), mode='w')
        tif.write_image(np.uint8(packed_overlap2[:, :, image_i] * 13 % 251))

    # import pylab
    # pylab.figure()
    # pylab.imshow(block1[0, :, :] % 13)
    # pylab.title('block1')
    # pylab.figure()
    # pylab.imshow(block2[0, :, :] % 13)
    # pylab.title('block2')
    # pylab.figure()
    # pylab.imshow(packed_overlap1[0, :, :] % 13)
    # pylab.title('packed overlap1')
    # pylab.figure()
    # pylab.imshow(packed_overlap2[0, :, :] % 13)
    # pylab.title('packed overlap2')

    # pylab.show()

to_merge = []
to_steal = []
for l1, l2, overlap_area in zip(overlap_labels1, overlap_labels2, overlap_areas):
    if l1 == 0 or l2 == 0:
        continue
    if ((overlap_area > auto_join_pixels) or
        ((overlap_area > minoverlap_pixels) and
         ((overlap_area > minoverlap_single_ratio * areas[l1]) or
          (overlap_area > minoverlap_single_ratio * areas[l2]) or
          ((overlap_area > minoverlap_dual_ratio * areas[l1]) and
           (overlap_area > minoverlap_dual_ratio * areas[l2]))))):
        if inverse[l1] != inverse[l2]:
            print "Merging segments {0} and {1}.".format(inverse[l1], inverse[l2])
            to_merge.append((inverse[l1], inverse[l2]))
    else:
        print "Stealing segments {0} and {1}.".format(inverse[l1], inverse[l2])
        to_steal.append((overlap_area, l1, l2))

# Merges are handled later

# Process steals
# packed_overlap1_face = packed_overlap1[tuple(0 if i == direction else slice(None, None) for i in range (3))]
# packed_overlap2_face = packed_overlap2[tuple(-1 if i == direction else slice(None, None) for i in range (3))]

# faceareacounter = fast64counter.ValueCountInt64()
# faceareacounter.add_values(packed_overlap1_face.ravel())
# faceareacounter.add_values(packed_overlap2_face.ravel())
# face_areas = defaultdict(int)
# face_areas.update(dict(zip(*faceareacounter.get_counts())))
# for _, l1, l2 in reversed(sorted(to_steal)):  # work largest to smallest
#     if face_areas[l1] >= face_areas[l2]:
#         packed_overlap2[(packed_overlap1 == l1)] = l1
#     else:
#         packed_overlap1[(packed_overlap2 == l2)] = l2

# if Debug:
#     from libtiff import TIFF
#     tif = TIFF.open('packed_overlap1_post_steal.tif', mode='w')
#     tif.write_image(np.uint8(packed_overlap1[0, :, :] * 13 % 251))
#     tif = TIFF.open('packed_overlap2_post_steal.tif', mode='w')
#     tif.write_image(np.uint8(packed_overlap2[0, :, :] * 13 % 251))

#     # import pylab
#     # pylab.figure()
#     # pylab.imshow(packed_overlap1[0, :, :] % 13)
#     # pylab.title('packed_overlap1 post steal')
#     # pylab.figure()
#     # pylab.imshow(packed_overlap2[0, :, :] % 13)
#     # pylab.title('packed_overlap2 post steal')
#     # pylab.show()

# handle merges by rewriting the inverse
merge_map = dict(reversed(sorted(s)) for s in to_merge)
for idx, val in enumerate(inverse):
    if val in merge_map:
        while val in merge_map:
            val = merge_map[val]
        inverse[idx] = val

# Remap and merge
out1 = h5py.File(outblock1_path + '_partial', 'w')
out2 = h5py.File(outblock2_path + '_partial', 'w')
outblock1 = out1.create_dataset('/labels', block1.shape, block1.dtype, chunks=label_chunks, compression='gzip')
outblock2 = out2.create_dataset('/labels', block2.shape, block2.dtype, chunks=label_chunks, compression='gzip')
outblock1[...] = inverse[packed_block1]
outblock2[...] = inverse[packed_block2]

# copy any previous merge tables from block 1 to the new output and merge
if previous_merges1 != None:
    if len(to_merge):
        merges1 = np.vstack((previous_merges1, to_merge))
    else:
        merges1 = previous_merges1
else:
    merges1 = np.array(to_merge).astype(np.uint64)

if merges1.size > 0:
    out1.create_dataset('/merges', merges1.shape, merges1.dtype)[...] = merges1

# copy any previous merge tables from block 2 to the new output
if previous_merges2 != None:
    out2.create_dataset('/merges', previous_merges2.shape, previous_merges2.dtype)[...] = previous_merges2


if Debug:
    from libtiff import TIFF
    tif = TIFF.open('final_block1.tif', mode='w')
    tif.write_image(np.uint8(outblock1[0, :, :] * 13 % 251))
    tif = TIFF.open('final_block2.tif', mode='w')
    tif.write_image(np.uint8(outblock2[0, :, :] * 13 % 251))

    # import pylab
    # pylab.figure()
    # pylab.imshow(outblock1[0, :, :] % 13)
    # pylab.title('final block1')
    # pylab.figure()
    # pylab.imshow(outblock2[0, :, :] % 13)
    # pylab.title('final block2')
    # pylab.show()

# move to final location
out1.close()
out2.close()

if os.path.exists(outblock1_path):
        os.unlink(outblock1_path)
if os.path.exists(outblock2_path):
        os.unlink(outblock2_path)

os.rename(outblock1_path + '_partial', outblock1_path)
os.rename(outblock2_path + '_partial', outblock2_path)
print "Successfully wrote", outblock1_path, 'and', outblock2_path
