"""Test the thresholding utilities."""
import nibabel as nib
import numpy as np
import pytest
from nilearn.glm import (
    cluster_level_inference,
    fdr_threshold,
    threshold_stats_img,
)
from nilearn.glm.thresholding import _compute_hommel_value
from nilearn.image import get_data
from numpy.testing import assert_almost_equal, assert_equal
from scipy.stats import norm


def test_fdr():
    rng = np.random.RandomState(42)
    n = 100
    x = np.linspace(0.5 / n, 1.0 - 0.5 / n, n)
    x[:10] = 0.0005
    x = norm.isf(x)
    rng.shuffle(x)
    assert_almost_equal(fdr_threshold(x, 0.1), norm.isf(0.0005))
    assert fdr_threshold(x, 0.001) == np.infty
    with pytest.raises(ValueError):
        fdr_threshold(x, -0.1)
    with pytest.raises(ValueError):
        fdr_threshold(x, 1.5)
    # addresses #2879
    n = 10
    pvals = np.linspace(1 / n, 1, n)
    pvals[0] = 0.007
    assert np.isfinite(fdr_threshold(norm.isf(pvals), 0.1))


def test_threshold_stats_img():
    shape = (9, 10, 11)
    p = np.prod(shape)
    data = norm.isf(np.linspace(1.0 / p, 1.0 - 1.0 / p, p)).reshape(shape)
    alpha = 0.001
    data[2:4, 5:7, 6:8] = 5.0
    stat_img = nib.Nifti1Image(data, np.eye(4))
    mask_img = nib.Nifti1Image(np.ones(shape), np.eye(4))

    # test 1
    th_map, _ = threshold_stats_img(
        stat_img, mask_img, alpha, height_control="fpr", cluster_threshold=0
    )
    vals = get_data(th_map)
    assert np.sum(vals > 0) == 8

    # test 2: excessive cluster forming threshold
    th_map, _ = threshold_stats_img(
        stat_img,
        mask_img,
        threshold=100,
        height_control=None,
        cluster_threshold=0,
    )
    vals = get_data(th_map)
    assert np.sum(vals > 0) == 0

    # test 3: excessive size threshold
    th_map, z_th = threshold_stats_img(
        stat_img, mask_img, alpha, height_control="fpr", cluster_threshold=10
    )
    vals = get_data(th_map)
    assert np.sum(vals > 0) == 0
    assert z_th == norm.isf(0.0005)

    # test 4: fdr threshold + bonferroni
    for control in ["fdr", "bonferroni"]:
        th_map, _ = threshold_stats_img(
            stat_img,
            mask_img,
            alpha=0.05,
            height_control=control,
            cluster_threshold=5,
        )
        vals = get_data(th_map)
        assert np.sum(vals > 0) == 8

    # test 5: direct threshold
    th_map, _ = threshold_stats_img(
        stat_img,
        mask_img,
        threshold=4.0,
        height_control=None,
        cluster_threshold=0,
    )
    vals = get_data(th_map)
    assert np.sum(vals > 0) == 8

    # test 6: without mask
    th_map, _ = threshold_stats_img(
        stat_img, None, threshold=4.0, height_control=None, cluster_threshold=0
    )
    vals = get_data(th_map)
    assert np.sum(vals > 0) == 8

    # test 7 without a map
    th_map, threshold = threshold_stats_img(
        None, None, threshold=3.0, height_control=None, cluster_threshold=0
    )
    assert threshold == 3.0
    assert th_map is None

    th_map, threshold = threshold_stats_img(
        None, None, alpha=0.05, height_control="fpr", cluster_threshold=0
    )
    assert threshold > 1.64
    assert th_map is None

    with pytest.raises(ValueError):
        threshold_stats_img(None, None, alpha=0.05, height_control="fdr")
    with pytest.raises(ValueError):
        threshold_stats_img(
            None, None, alpha=0.05, height_control="bonferroni"
        )

    # test 8 wrong procedure
    with pytest.raises(ValueError):
        threshold_stats_img(None, None, alpha=0.05, height_control="plop")


@pytest.mark.parametrize(
    "alpha, expected",
    [
        (1.0e-9, 7),
        (1.0e-7, 6),
        (0.059, 6),
        (0.061, 5),
        (0.249, 5),
        (0.251, 4),
        (0.399, 4),
        (0.401, 3),
        (0.899, 3),
        (0.901, 0),
    ],
)
def test_hommel(alpha, expected):
    """Check that the computation of Hommel value.

    For these, we take the example in  Meijer et al. 2017
    'A shortcut for Hommel's procedure in linearithmic time'
    and check that we obtain the same values.
    https://arxiv.org/abs/1710.08273
    """
    z = norm.isf([1.0e-8, 0.01, 0.08, 0.1, 0.5, 0.7, 0.9])
    assert _compute_hommel_value(z, alpha=alpha) == expected


def test_all_resolution_inference():
    shape = (9, 10, 11)
    p = np.prod(shape)
    data = norm.isf(np.linspace(1.0 / p, 1.0 - 1.0 / p, p)).reshape(shape)
    alpha = 0.001
    data[2:4, 5:7, 6:8] = 5.0
    stat_img = nib.Nifti1Image(data, np.eye(4))
    mask_img = nib.Nifti1Image(np.ones(shape), np.eye(4))

    # test 1: standard case
    th_map = cluster_level_inference(stat_img, threshold=3, alpha=0.05)
    vals = get_data(th_map)
    assert np.sum(vals > 0) == 8

    # test 2: high threshold
    th_map = cluster_level_inference(stat_img, threshold=6, alpha=0.05)
    vals = get_data(th_map)
    assert np.sum(vals > 0) == 0

    # test 3: list of thresholds
    th_map = cluster_level_inference(stat_img, threshold=[3, 6], alpha=0.05)
    vals = get_data(th_map)
    assert np.sum(vals > 0) == 8

    # test 4: one single voxel
    data[3, 6, 7] = 10
    stat_img_ = nib.Nifti1Image(data, np.eye(4))
    th_map = cluster_level_inference(stat_img_, threshold=7, alpha=0.05)
    vals = get_data(th_map)
    assert np.sum(vals > 0) == 1

    # test 5: aberrant alpha
    with pytest.raises(ValueError):
        cluster_level_inference(stat_img, threshold=3, alpha=2)
    with pytest.raises(ValueError):
        cluster_level_inference(stat_img, threshold=3, alpha=-1)

    # test 6 with mask_img
    th_map = cluster_level_inference(
        stat_img, mask_img=mask_img, threshold=3, alpha=0.05
    )
    vals = get_data(th_map)
    assert np.sum(vals > 0) == 8

    # test 7 verbose mode
    th_map = cluster_level_inference(
        stat_img, threshold=3, alpha=0.05, verbose=True
    )

    # test 9: one-sided test
    th_map, z_th = threshold_stats_img(
        stat_img,
        mask_img,
        alpha,
        height_control="fpr",
        cluster_threshold=10,
        two_sided=False,
    )
    assert_equal(z_th, norm.isf(0.001))

    # test 10: two-side fdr threshold + bonferroni
    data[0:2, 0:2, 6:8] = -5.0
    stat_img = nib.Nifti1Image(data, np.eye(4))
    for control in ["fdr", "bonferroni"]:
        th_map, _ = threshold_stats_img(
            stat_img,
            mask_img,
            alpha=0.05,
            height_control=control,
            cluster_threshold=5,
        )
        vals = get_data(th_map)
        assert_equal(np.sum(vals > 0), 8)
        assert_equal(np.sum(vals < 0), 8)
        th_map, _ = threshold_stats_img(
            stat_img,
            mask_img,
            alpha=0.05,
            height_control=control,
            cluster_threshold=5,
            two_sided=False,
        )
        vals = get_data(th_map)
        assert_equal(np.sum(vals > 0), 8)
        assert_equal(np.sum(vals < 0), 0)
