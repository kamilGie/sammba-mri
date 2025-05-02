# -*- coding: utf-8 -*-

# Author: Nachiket Nadkarni, 2017
# License: CeCILL-B

import os
import subprocess
import itertools
import warnings
import numpy as np
import nibabel
from .utils import _rotate_affine

def _is_dicom(filename):
    """
    Determines by name and extension if a file is an Enhanced Multiframe DICOM 
    or not. So this just means checking if the path conforms to EnIm*.dcm.

    Parameters
    ----------
    filename : str
        Path to file to check.

    Returns
    -------
    True if `filename` is a DICOM file, False otherwise.
    """
    
    # properly testing to see if a file is a DICOM or not is probably beyond the 
    # scope of this module, but if we are to do it at all, a good idea seems to
    # be that used by dcmtk's dcmftest:
    # "All files specified on the command line are checked for the presence of 
    # the DICOM "magic word" 'DICM' at byte position 128. No attempt is made to 
    # parse the complete data set."

    if filename.startswith('EnIm') and filename.endswith('.dcm'):
            return True

    return False


def dcm_to_nii(dcmdump_path, dicom_filename, save_directory, siap_fix=True,
               id_in_filename=True, date_in_filename=True,
               time_in_filename=True, protocol_in_filename=True,
               paravision_folder_in_filename=True,
               siap_in_filename=True):
    """ Converts Bruker Paravision enhanced multiframe DICOM files into
    NIfTI-1 format.

    Assumes int16; this will be changed in the future.
    NIFTI files are named based on several tag values found in the DICOM. Also
    saved with the same name as the .nii.gz is a .txt file of extracted
    meta-data that could be useful to the processing of certain protocols
    such as perfusion, T1/T2 mapping and diffusion.

    Thanks to common.py of dicom2nifiti by Arne Brys, icometrix, which saved
    me when it comes to specifying the affine for nibabel.

    Parameters
    ----------
    dcmdump_path : str
        Path to the compiled dcmdump (see Note).

    dicom_filename : str
        Path to the DICOM file (typically named EnIm1.dcm).

    save_directory : str
        Path to the directory to save the extracteed NIFTI image.

    siap_fix : bool, optional
        If True, swaps the superior-inferior and anterior-posterior axes to be
        how I think they should be. In rodents, Paravision sets dorsal-ventral
        as AP and rostral-caudal as SI. I think they should be the other way
        round
        https://en.wikipedia.org/wiki/Anatomical_terms_of_location#Main_terms

    id_in_filename : bool, optional
        If True, animal ID is included in the filename of the generated NIFTI.

    date_in_filename : bool, optional
        If True, acquisition date is included in the filename of the generated
        NIFTI.

    time_in_filename : bool, optional
        If True, acquisition time included in the filename of the generated
        NIFTI.

    protocol_in_filename : bool, optional
        If True, the protocl acronym is included in the filename of the
        generated NIFTI.

    paravision_folder_in_filename : bool, optional
        If True, Paravision folder number is included in the filename
        of the generated NIFTI.

    siap_in_filename : bool, optional
        If True, 'fixedSIAP' or 'origSIAP' is included in the filename of the
        generated NIFTI, to tell whether or not axes were swapped.

    Returns
    -------
    nii_filename : str
        Path to the created NIFTI image.

    Notes
    -----
    This is effectively a python wrapper to dcmdump, processing and passing
    its output to nibabel and a text file.
    Depends on access to a compiled version of dcmdump (part of OFFIS dcmtk;
    http://dcmtk.org/dcmtk.php.en and
    http://support.dcmtk.org/docs/dcmdump.html)
    which does the initial parsing: extraction of the header/metadata as text
    and the image data as a raw vector.

    Useful documents include DICOM spec C.7.6.2.1.1 and 10.7.1.3
    common.py of dicom2nifiti by Arne Brys, icometrix saved me when it comes to
    specifying the affine for nibabel! see http://dicom2nifti.readthedocs.io.
    he effectively did the hard part, interpreting nibabel's DICOM tutorial for
    me.

    Only tested on PV6 .dcm files and a limited number of sequences. Little or
    no error-checking. There are a lot of circumstances where this converter
    will fail or be sub-optimal.
    """

    # regularise/standardise input paths
    input_paths = [dcmdump_path, dicom_filename, save_directory]
    input_paths = [os.path.abspath(input_path) for input_path in input_paths]
    dcmdump_path, dicom_filename, save_directory = input_paths

    # read dicom_filename header/metadata using dcmdump
    # +L ensures long tags are fully printed
    # -M prevents 'very long values' from being read in, which vastly improves 
    # performance in at least one case (my windows 10 laptop). the same machine
    # running the code within a WSSL bash shell was far faster; not sure where 
    # the nt bottleneck is
    # universal_newlines=TRUE should keep output format consistent across python 
    # 2 and 3, plus posix and nt
    dcmdump_output = subprocess.check_output([dcmdump_path, dicom_filename,
                                              '+L', '-M'],
                                             universal_newlines=True)

    # fields that are likely to be empty or multiple are awkward to dynamically
    # declare, so do it here rather than in the parser loop below
    TR = []  # is not always in DICOM
    protocol = []  # cos of DKI
    bruker_sequence = []  # cos of DKI
    diffdir = []
    TIs = []
    bval = []
    bvalXX = []
    bvalXY = []
    bvalXZ = []
    bvalYY = []
    bvalYZ = []
    bvalZZ = []
    IPPs = []
    ISPnums = []
    repno = []
    DIVs = []
    frame_comments = []

    # via subprocess, dcmdump produces numerous lines of string output.
    # for some parameters such as SeriesDate, there should hopefully be only
    # one line. for others, such as InStackPositionNumber, there may be
    # several. three example lines are shown below:

    # '(0008,0021) DA [20160219]                      #   8, 1 SeriesDate'
    # '(0018,9079) FD 35                              #   8, 1 InversionTimes'
    # '(0020,0032) DS [-9\\-7.417465618\\1.68366613]  #  26, 3 ImagePositionPatient'

    # fields interpreted as strings are delimited with square brackets
    # (incidentally, several numeric fields get interpreted as strings, I do
    # not know why, and I assume it does not matter). in the loop below, each
    # line is parsed to identify what field it represents and extract the value

    for line in dcmdump_output.splitlines():
        # pline = processed line. some lines have leading whitespace
        pline = line.lstrip()
        if len(pline) >= 11:
            if pline[0] == '(' and pline[5] == ',' and pline[10] == ')':
                tag = pline[0:11]
                val = pline[:pline.rfind('#')].rstrip()[15:]
                # remove [] that dcmdump delimits strings with
                if val[0] == '[':
                    val = val[1:-1]

                vals = val.split('\\') # \\ should work on both posix and nt
                # turn single value lists into single values
                if type(vals) == list:
                    if len(vals) == 1:
                        vals = vals[0]
                # assign output to variable names
                if tag == '(0008,0021)':  # Series Date
                    acqdate = vals
                if tag == '(0008,0031)':  # Series Time
                    acqtime = vals
                if tag == '(0010,0020)':  # Patient ID​
                    patID = vals
                if tag == '(0018,0023)':  # MR Acquisition Type
                    acqdims = vals
                if tag == '(0018,0050)':  # Slice Thickness​
                    thk = float(vals)
                if tag == '(0018,0080)':  # Repetition Time
                    TR = float(vals)
                if tag == '(0018,1030)':  # Protocol Name
                    protocol = vals
                if tag == '(0018,5100)':  # Patient Position
                    patpos = vals
                if tag == '(0018,9005)':  # Pulse Sequence Name
                    bruker_sequence = vals
                if tag == '(0018,9075)':  # Diffusion Directionality​
                    diffdir.append(vals)
                if tag == '(0018,9079)':  # Inversion Times
                    TIs.append(float(vals))
                if tag == '(0018,9087)':  # Diffusion b-value
                    bval.append(float(vals))
                if tag == '(0018,9602)':  # Diffusion b-value XX
                    bvalXX.append(float(vals))
                if tag == '(0018,9603)':  # Diffusion b-value XY​
                    bvalXY.append(float(vals))
                if tag == '(0018,9604)':  # Diffusion b-value XZ
                    bvalXZ.append(float(vals))
                if tag == '(0018,9605)':  # Diffusion b-value YY
                    bvalYY.append(float(vals))
                if tag == '(0018,9606)':  # Diffusion b-value YZ
                    bvalYZ.append(float(vals))
                if tag == '(0018,9607)':  # Diffusion b-value Z
                    bvalZZ.append(float(vals))
                if tag == '(0020,0032)':  # Image Position (Patient)
                    IPPs.append([float(i) for i in vals])
                if tag == '(0020,0037)':  # Image Orientation (Patient)
                    cosines = [float(i) for i in vals]
                if tag == '(0020,9057)':  # In-Stack Position Number
                    ISPnums.append(int(vals))
                if tag == '(0020,9128)':  # Temporal Position Index​
                    repno.append(int(vals))
                if tag == '(0020,9157)':  # Dimension Index Values
                    DIVs.append([int(i) for i in vals])
                if tag == '(0020,9158)':  # Frame Comments
                    frame_comments.append(vals)
                if tag == '(0028,0008)':  # Number of Frames
                    frames = int(vals)
                if tag == '(0028,0010)':  # Rows
                    rows = int(vals)
                if tag == '(0028,0011)':  # Columns
                    cols = int(vals)
                if tag == '(0028,0030)':  # Pixel Spacing
                    pixspac = [float(i) for i in vals]

                # might be useful in the future
                # (0028,0100)  # Bits Allocated
                # (0028,0101)  # Bits Stored
                # (0028,0102)  # High Bit
                # (0028,0103)  # Pixel Representation

    # if they have length zero (or just unequal to ISPnums, though no idea how
    # that could be possible), populate vectors that will be included in ptbl
    # (parameter table). there must be a more efficient way
    if len(diffdir) != len(ISPnums):
        diffdir = list(itertools.repeat('NA', len(ISPnums)))
    if len(TIs) != len(ISPnums):
        TIs = list(itertools.repeat('NA', len(ISPnums)))
    if len(bval) != len(ISPnums):
        bval = list(itertools.repeat('NA', len(ISPnums)))
    if len(bvalXX) != len(ISPnums):
        bvalXX = list(itertools.repeat('NA', len(ISPnums)))
    if len(bvalXY) != len(ISPnums):
        bvalXY = list(itertools.repeat('NA', len(ISPnums)))
    if len(bvalXZ) != len(ISPnums):
        bvalXZ = list(itertools.repeat('NA', len(ISPnums)))
    if len(bvalYY) != len(ISPnums):
        bvalYY = list(itertools.repeat('NA', len(ISPnums)))
    if len(bvalYZ) != len(ISPnums):
        bvalYZ = list(itertools.repeat('NA', len(ISPnums)))
    if len(bvalZZ) != len(ISPnums):
        bvalZZ = list(itertools.repeat('NA', len(ISPnums)))
    if len(repno) != len(ISPnums):
        repno = list(itertools.repeat('NA', len(ISPnums)))
    if len(frame_comments) != len(ISPnums):
        frame_comments = list(itertools.repeat('NA', len(ISPnums)))

    # ptbl = parameter table

    IPPs_str = [str(ipps) for ipps in IPPs]
    ptbl_data = np.hstack((np.array([repno, ISPnums, diffdir, TIs, bval, bvalXX,
                                bvalXY, bvalXZ, bvalYY, bvalYZ, bvalZZ, IPPs_str]).T,
                                np.atleast_2d(frame_comments).T, DIVs))

    slices = max(ISPnums)  # maybe a bit dangerous

    # use check_output rather than call to avoid stdout filling up the terminal
    rawfile = os.path.join(save_directory, 'EnIm1.dcm.0.raw')
    if os.path.exists(rawfile):
        os.remove(rawfile)
    sink = subprocess.check_output([dcmdump_path, dicom_filename, '+W',
                                    save_directory])
    rawarray = np.fromfile(rawfile, dtype=np.int16)
    os.remove(rawfile)

    # rawarray is actually just a vector, need to reshape into a run of frames
    rawarray = np.reshape(rawarray, (frames, rows, cols))
    rawarray = np.reshape(rawarray, (int(frames / slices), slices, rows, cols))
    rawarray = np.transpose(rawarray, (3, 2, 1, 0))

    # fsp = first slice position, lsp = last slice position
    fsp = np.array(np.array(IPPs)[np.array(ISPnums) == 1].tolist()[0])
    lsp = np.array(np.array(IPPs)[np.array(ISPnums) == slices].tolist()[0])

    # https://en.wikipedia.org/wiki/Euclidean_distance
    # not used yet
    flspdiff = fsp - lsp
    eucliddist = (flspdiff[0] ** 2 + flspdiff[1] ** 2 + flspdiff[2]**2) ** 0.5

    if slices == 1:  # single slice
        step = [0, 0, -1]
    else:
        step = (fsp - lsp) / (1 - slices)
        slicegap = eucliddist / (slices - 1)

    affine = np.matrix(
        [[-cosines[0] * pixspac[1], -cosines[3] * pixspac[0], -step[0], -fsp[0]],
         [-cosines[1] * pixspac[1], -cosines[4] * pixspac[0], -step[1], -fsp[1]],
         [cosines[2] * pixspac[1],  cosines[5] * pixspac[0], step[2], fsp[2]],
         [0, 0, 0, 1]])

    affineident = np.eye(4, dtype=int)

    # not sure if any of these patpos specs is really correct
    if patpos == 'HFS':
        ppaff = _rotate_affine(180, 'y')
    # not sure this is correct: a reflection may be necessary too
    if patpos == 'FFS':
        ppaff = affineident
    if patpos == 'HFP':
        ppaff = _rotate_affine(180, 'x')

    if siap_fix:
        affine = _rotate_affine(270, 'x') * _rotate_affine(180, 'y') *\
            _rotate_affine(180, 'z') * ppaff * affine
    else:
        print('siap_fix is {}'.format(siap_fix))

    header = nibabel.Nifti1Header()
    header.set_xyzt_units('mm', 'msec')
    header.set_data_dtype(np.int16)
    if type(TR) != list:
        header['pixdim'][4] = TR
    img = nibabel.Nifti1Image(rawarray, affine, header=header)

    bf = 'bf' + dicom_filename.split(os.sep)[-5]  # Paravision experiment folder 
                                                  # number
    if siap_fix:
        SIAPfixres = 'fixedSIAP'
    else:
        SIAPfixres = 'origSIAP'
    # the joins deal with a problem of DKI recon where one of the patID and
    # protocol seems to be a list
    basename_parts = []
    if id_in_filename:
        basename_parts.append(''.join(patID))
    if date_in_filename:
        basename_parts.append(''.join(acqdate))
    if time_in_filename:
        basename_parts.append(''.join(acqtime))
    if protocol_in_filename:
        basename_parts.append(''.join(protocol))
    if siap_in_filename:
        basename_parts.append(''.join(SIAPfixres))
    if paravision_folder_in_filename:
        basename_parts.append(''.join(bf))
    if not basename_parts:
        warnings.warn('You choose not to include ID, date, time, protocol, '
                      'SIAP nor paravision folder number in the NIFTI '
                      'filename. Using the DICOM basename instead')
        basename_parts = os.path.basename(dicom_filename)

    basename_no_ext = '_'.join(basename_parts)
    nii_basename = basename_no_ext + '.nii.gz'
    nii_filename = os.path.join(save_directory, nii_basename)
    img.to_filename(nii_filename)
    txt_basename = basename_no_ext + '_ptbl.txt'
    names = ['repno', 'slice', 'diffdir', 'TI', 'bval', 'bvalXX',
              'bvalXY', 'bvalXZ', 'bvalYY', 'bvalYZ', 'bvalZZ', 'slicepos', 'FC']
    divs_names = ['DIV{}'.format(n) for n in range(np.shape(DIVs)[-1])]
    names = names + divs_names
    header = '\t'.join(names)
    fmt = '\t'.join(['%s' for name in names])
    np.savetxt(os.path.join(save_directory, txt_basename),
               ptbl_data, fmt=fmt, header=header)
    return nii_filename


def recursive_dcm_to_nii(dcmdump_path, session_directory, save_directory,
                         **dcm_to_nii_kwargs):
    """ Traverses recursively subdirectories of a given session directory
    and converts all DICOM files to NIFTI files.

    Parameters
    ----------
    dcmdump_path : str
        Path to the compiled dcmdump (see Note)

    session_directory : str
        Path to the top directory.

    save_directory : str
        Path to the directory to save the extracteed NIFTI image.

    dcm_to_nii_kwargs : extra keyword arguments
        Extra keyword arguments are passed to sammba.io_conversions.dcm_to_nii

    Returns
    -------
    nii_filenames : list of str
        List of paths to the created NIFTI images.

    See also
    --------
    sammba.io_conversions.dcm_to_nii
    """
    nii_filenames = []
    for root, dirs, files in os.walk(session_directory):
        for basename in files:
            if _is_dicom(basename):
                nii_filename = dcm_to_nii(
                    dcmdump_path, os.path.join(root, basename),
                    save_directory, **dcm_to_nii_kwargs)
                nii_filenames.append(nii_filename)
    return nii_filenames
