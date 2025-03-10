"""Flexible method to load confounds generated by fMRIprep.

Authors: Pierre Bellec, François Paugam, Hanad Sharmarke, Hao-Ting Wang,
Michael W. Weiss, Steven Meisler, Thibault Piront.
"""
import warnings

import pandas as pd

from . import load_confounds_components as components
from .load_confounds_utils import (
    MissingConfound,
    _get_confounds_file,
    _get_json,
    _load_confounds_file_as_dataframe,
    _load_confounds_json,
    _prepare_output,
    _sanitize_confounds,
)

# Global variables listing the admissible types of noise components
all_confounds = [
    "motion",
    "high_pass",
    "wm_csf",
    "global_signal",
    "compcor",
    "ica_aroma",
    "scrub",
    "non_steady_state"
]

# extra parameters needed for each noise component
component_parameters = {
    "motion": ["motion"],
    "wm_csf": ["wm_csf"],
    "global_signal": ["global_signal"],
    "compcor": ["meta_json", "compcor", "n_compcor"],
    "ica_aroma": ["ica_aroma"],
    "scrub": ["scrub", "fd_threshold", "std_dvars_threshold"],
}


def _check_strategy(strategy):
    """Ensure the denoising strategies are valid."""
    if (not isinstance(strategy, tuple)) and (not isinstance(strategy, list)):
        raise ValueError("strategy needs to be a tuple or list of strings"
                         f" A {type(strategy)} was provided instead.")
    for conf in strategy:
        if conf == "non_steady_state":
            warnings.warn("Non-steady state volumes are always detected. It "
                          "doesn't need to be supplied as part of the "
                          "strategy. Supplying non_steady_state in strategy "
                          "will not have additional effect.")
        if conf not in all_confounds:
            raise ValueError(f"{conf} is not a supported type of confounds.")

    # high pass filtering must be present if using fmriprep compcor outputs
    if ("compcor" in strategy) and ("high_pass" not in strategy):
        raise ValueError("When using compcor, `high_pass` must be included in "
                         f"strategy. Current strategy: '{strategy}'")


def _check_error(missing):
    """Consolidate a single error message across multiple missing confounds."""
    if missing["confounds"] or missing["keywords"]:
        error_msg = (
            "The following keywords or parameters are missing: "
            + f" {missing['confounds']}"
            + f" {missing['keywords']}"
            + ". You may want to try a different denoising strategy."
        )
        raise ValueError(error_msg)


def load_confounds(img_files,
                   strategy=("motion", "high_pass", "wm_csf"),
                   motion="full",
                   scrub=5, fd_threshold=0.2, std_dvars_threshold=3,
                   wm_csf="basic",
                   global_signal="basic",
                   compcor="anat_combined", n_compcor="all",
                   ica_aroma="full",
                   demean=True):
    """
    Use confounds from :term:`fMRIPrep`.

    To enable easy confound variables loading from :term:`fMRIPrep` outputs,
    `load_confounds` provides an interface that groups subsets of confound
    variables into noise components and their parameters. It is possible to
    fine-tune a subset of noise components and their parameters through this
    function.

    The implementation will only support :term:`fMRIPrep` functional derivative
    directory from the 1.2.x series. The `compcor` noise component requires
    1.4.x series or above.

    .. versionadded:: 0.9.0

    Parameters
    ----------
    img_files : path to processed image files, optionally as a list.
        Processed nii.gz/dtseries.nii/func.gii file reside in a
        :term:`fMRIPrep` generated functional derivative directory (i.e.The
        associated confound files should be in the same directory as the image
        file). As long as the image file, confound related tsv and json are in
        the same directory with BIDS-complied names, `load_confounds` can
        retrieve the relevant files correctly.

        - `nii.gz` or `dtseries.nii`: path to files, optionally as a list.
        - `func.gii`: list of a pair of paths to files, optionally as a list
          of lists.

    strategy : tuple or list of strings.
        Default ("motion", "high_pass", "wm_csf")
        The type of noise components to include.

        - "motion":  head motion estimates. Associated parameter: `motion`
        - "wm_csf" confounds derived from white matter and cerebrospinal fluid.
          Associated parameter: `wm_csf`
        - "global_signal" confounds derived from the global signal.
          Associated parameter: `global_signal`
        - "compcor" confounds derived from CompCor :footcite:`Behzadi2007`.
          When using this noise component, "high_pass" must also be applied.
          Associated parameter: `compcor`, `n_compcor`
        - "ica_aroma" confounds derived from ICA-AROMA :footcite:`Pruim2015`.
          Associated parameter: `ica_aroma`
        - "scrub" regressors for :footcite:`Power2014` scrubbing approach.
          Associated parameter: `scrub`, `fd_threshold`, `std_dvars_threshold`

        For each component above, associated parameters will be applied if
        specified. If associated parameters are not specified, any values
        supplied to the parameters are ignored.
        For example, `strategy=('motion', 'global_signal')` will allow users
        to supply input to associated parameter `motion` and `global_signal`;
        if users pass `wm_csf` parameter, it will not be applied as it is not
        part of the `strategy`.

        There are two additional noise components with no optional parameters.

        - "non_steady_state" denotes volumes collected before
          the :term:`fMRI` scanner has reached a stable state.
        - "high_pass" adds discrete cosines transformation
          basis regressors to handle low-frequency signal drifts.

        Non-steady-state volumes will always be checked. There's no need to
        supply this component to the strategy.

    motion : {'basic', 'power2', 'derivatives', 'full'}
        Type of confounds extracted from head motion estimates.

        - "basic" translation/rotation (6 parameters)
        - "power2" translation/rotation + quadratic terms (12 parameters)
        - "derivatives" translation/rotation + derivatives (12 parameters)
        - "full" translation/rotation + derivatives + quadratic terms + power2d
          derivatives (24 parameters)

    wm_csf : {'basic', 'power2', 'derivatives', 'full'}
        Type of confounds extracted from masks of white matter and
        cerebrospinal fluids.

        - "basic" the averages in each mask (2 parameters)
        - "power2" averages and quadratic terms (4 parameters)
        - "derivatives" averages and derivatives (4 parameters)
        - "full" averages + derivatives + quadratic terms + power2d derivatives
          (8 parameters)

    global_signal : {'basic', 'power2', 'derivatives', 'full'}
        Type of confounds extracted from the global signal.

        - "basic" just the global signal (1 parameter)
        - "power2" global signal and quadratic term (2 parameters)
        - "derivatives" global signal and derivative (2 parameters)
        - "full" global signal + derivatives + quadratic terms + power2d
          derivatives (4 parameters)

    scrub : int, default 5
        After accounting for time frames with excessive motion, further remove
        segments shorter than the given number. The default value is 5
        (referred as full scrubbing in :footcite:`Power2014`). When the value
        is 0, temove time frames based on excessive framewise displacement and
        DVARS only. One-hot encoding vectors are added as regressors for each
        scrubbed frame.

    fd_threshold : float, default 0.2
        Framewise displacement threshold for scrub (default = 0.2 mm)

    std_dvars_threshold : float, default 3
        Standardized DVARS threshold for scrub (default = 3).
        DVARs is defined as root mean squared intensity difference of volume N
        to volume N+1 :footcite:`Power2012`. D referring to temporal derivative
        of timecourses, VARS referring to root mean squared variance over
        voxels.

    compcor : {'anat_combined', 'anat_separated', 'temporal',\
    'temporal_anat_combined', 'temporal_anat_separated'}

        .. warning::
            Require fmriprep >= v:1.4.0.

        Type of confounds extracted from a component based noise correction
        method :footcite:`Behzadi2007`.

        - "anat_combined" noise components calculated using a white matter and
          CSF combined anatomical mask
        - "anat_separated" noise components calculated using white matter mask
          and CSF mask compcor separately; two sets of scores are concatenated
        - "temporal" noise components calculated using temporal compcor
        - "temporal_anat_combined" components of "temporal" and "anat_combined"
        - "temporal_anat_separated" components of "temporal" and
          "anat_separated"

    n_compcor : "all" or int, default "all"
        The number of noise components to be extracted.
        For acompcor_combined=False, and/or compcor="full", this is the number
        of components per mask.
        "all": select all components (50% variance explained by
        :term:`fMRIPrep` defaults)

    ica_aroma : {'full', 'basic'}

        - "full": use :term:`fMRIPrep` output
          `~desc-smoothAROMAnonaggr_bold.nii.gz`.
        - "basic": use noise independent components only.

    demean : boolean, default True
        If True, the confounds are standardized to a zero mean (over time).
        When using :class:`nilearn.maskers.NiftiMasker` with default
        parameters, the recommended option is True.
        When using :func:`nilearn.signal.clean` with default parameters, the
        recommended option is False.
        When `sample_mask` is not None, the mean is calculated on retained
        volumes.

    Returns
    -------
    confounds : pandas.DataFrame, or list of
        A reduced version of :term:`fMRIPrep` confounds based on selected
        strategy and flags.
        The columns contains the labels of the regressors.

    sample_mask : None, numpy.ndarray, or list of
        When no volumns require removal, the value is None.
        Otherwise, shape: (number of scans - number of volumes removed, )
        The index of the niimgs along time/fourth dimension for valid volumes
        for subsequent analysis.
        This attribute should be passed to parameter `sample_mask` of
        :class:`nilearn.maskers.NiftiMasker` or
        :func:`nilearn.signal.clean`.
        Volumns are removed if flagged as following:

        - Non-steady-state volumes (if present)
        - Motion outliers detected by scrubbing

    Notes
    -----
    The noise components implemented in this class are adapted from
    :footcite:`Ciric2017`. Band-pass filter is replaced by high-pass filter.
    Low-pass filters can be implemented, e.g., through `NifitMaskers`. Other
    aspects of the preprocessing listed in :footcite:`Ciric2017` are controlled
    through :term:`fMRIPrep`, e.g. distortion correction.

    See Also
    --------
    :func:`nilearn.interfaces.fmriprep.load_confounds_strategy`

    References
    ----------
    .. footbibliography::

    """
    _check_strategy(strategy)

    # load confounds per image provided
    img_files, flag_single = _sanitize_confounds(img_files)
    confounds_out = []
    sample_mask_out = []
    for file in img_files:
        sample_mask, conf = _load_confounds_for_single_image_file(
            file, strategy, demean,
            motion=motion,
            scrub=scrub,
            fd_threshold=fd_threshold,
            std_dvars_threshold=std_dvars_threshold,
            wm_csf=wm_csf,
            global_signal=global_signal,
            compcor=compcor, n_compcor=n_compcor,
            ica_aroma=ica_aroma)
        confounds_out.append(conf)
        sample_mask_out.append(sample_mask)

    # If a single input was provided,
    # send back a single output instead of a list
    if flag_single:
        confounds_out = confounds_out[0]
        sample_mask_out = sample_mask_out[0]
    return confounds_out, sample_mask_out


def _load_confounds_for_single_image_file(image_file, strategy, demean,
                                          **kwargs):
    """Load confounds for a single image file."""
    # Check for ica_aroma in strategy, this will change the required image_file
    flag_full_aroma = ("ica_aroma" in strategy) and (
        kwargs.get("ica_aroma") == "full"
    )

    confounds_file = _get_confounds_file(image_file,
                                         flag_full_aroma=flag_full_aroma)
    confounds_json_file = _get_json(confounds_file)

    return _load_single_confounds_file(confounds_file=confounds_file,
                                       strategy=strategy,
                                       demean=demean,
                                       confounds_json_file=confounds_json_file,
                                       **kwargs)


def _load_single_confounds_file(confounds_file, strategy, demean=True,
                                confounds_json_file=None, **kwargs):
    """Load and extract specified confounds from the confounds file."""
    flag_acompcor = ("compcor" in strategy) and (
        "anat" in kwargs.get("compcor")
    )
    # Convert tsv file to pandas dataframe
    confounds_all = _load_confounds_file_as_dataframe(confounds_file)

    if confounds_json_file is None:
        confounds_json_file = _get_json(confounds_file)

    # Read the associated json file
    meta_json = _load_confounds_json(confounds_json_file,
                                     flag_acompcor=flag_acompcor)

    missing = {"confounds": [], "keywords": []}
    # always check non steady state volumes are loaded
    confounds_select, missing = _load_noise_component(confounds_all,
                                                      "non_steady_state",
                                                      missing,
                                                      meta_json=meta_json,
                                                      **kwargs)
    for component in strategy:
        loaded_confounds, missing = _load_noise_component(
            confounds_all, component, missing, meta_json=meta_json,
            **kwargs)
        confounds_select = pd.concat([confounds_select, loaded_confounds],
                                     axis=1)

    _check_error(missing)  # raise any missing
    return _prepare_output(confounds_select, demean)


def _load_noise_component(confounds_raw, component, missing, **kargs):
    """Load confound of a single noise component."""
    try:
        need_params = component_parameters.get(component)
        if need_params:
            params = {param: kargs.get(param) for param in need_params}
            loaded_confounds = getattr(components, f"_load_{component}")(
                confounds_raw, **params)
        else:
            loaded_confounds = getattr(components, f"_load_{component}")(
                confounds_raw)
    except MissingConfound as exception:
        missing["confounds"] += exception.params
        missing["keywords"] += exception.keywords
        loaded_confounds = pd.DataFrame()
    return loaded_confounds, missing
