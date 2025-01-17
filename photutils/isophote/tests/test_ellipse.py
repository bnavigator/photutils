# Licensed under a 3-clause BSD style license - see LICENSE.rst
"""
Tests for the ellipse module.
"""

import math

import numpy as np
import pytest
from astropy.io import fits
from astropy.modeling.models import Gaussian2D

from photutils.datasets import get_path, make_noise_image
from photutils.isophote.ellipse import Ellipse
from photutils.isophote.geometry import EllipseGeometry
from photutils.isophote.isophote import Isophote, IsophoteList
from photutils.isophote.tests.make_test_data import make_test_image
from photutils.utils._optional_deps import HAS_SCIPY

# define an off-center position and a tilted sma
POS = 384
PA = 10.0 / 180.0 * np.pi

# build off-center test data. It's fine to have a single np array to use
# in all tests that need it, but do not use a single instance of
# EllipseGeometry. The code may eventually modify it's contents. The safe
# bet is to build it wherever it's needed. The cost is negligible.
OFFSET_GALAXY = make_test_image(x0=POS, y0=POS, pa=PA, noise=1.0e-12,
                                seed=0)


@pytest.mark.skipif(not HAS_SCIPY, reason='scipy is required')
class TestEllipse:
    def setup_class(self):
        # centered, tilted galaxy
        self.data = make_test_image(pa=PA, seed=0)

    @pytest.mark.remote_data
    def test_find_center(self):
        path = get_path('isophote/M51.fits', location='photutils-datasets',
                        cache=True)
        hdu = fits.open(path)
        data = hdu[0].data
        hdu.close()

        geometry = EllipseGeometry(252, 253, 10.0, 0.2, np.pi / 2)
        geometry.find_center(data)
        assert geometry.x0 == 257.0
        assert geometry.y0 == 258.0

    def test_basic(self):
        ellipse = Ellipse(self.data)
        isophote_list = ellipse.fit_image()

        assert isinstance(isophote_list, IsophoteList)
        assert len(isophote_list) > 1
        assert isinstance(isophote_list[0], Isophote)

        # verify that the list is properly sorted in sem-major axis length
        assert isophote_list[-1] > isophote_list[0]

        # the fit should stop where gradient loses reliability.
        assert len(isophote_list) == 69
        assert isophote_list[-1].stop_code == 1

    def test_linear(self):
        ellipse = Ellipse(self.data)
        isophote_list = ellipse.fit_image(linear=True, step=2.0)

        # verify that the list is properly sorted in sem-major axis length
        assert isophote_list[-1] > isophote_list[0]

        # difference in sma between successive isohpotes must be constant.
        step = isophote_list[-1].sma - isophote_list[-2].sma
        assert math.isclose((isophote_list[-2].sma - isophote_list[-3].sma),
                            step, rel_tol=0.01)
        assert math.isclose((isophote_list[-3].sma - isophote_list[-4].sma),
                            step, rel_tol=0.01)
        assert math.isclose((isophote_list[2].sma - isophote_list[1].sma),
                            step, rel_tol=0.01)

    def test_fit_one_ellipse(self):
        ellipse = Ellipse(self.data)
        isophote = ellipse.fit_isophote(40.0)

        assert isinstance(isophote, Isophote)
        assert isophote.valid

    def test_offcenter_fail(self):
        # A first guess ellipse that is centered in the image frame.
        # This should result in failure since the real galaxy
        # image is off-center by a large offset.
        ellipse = Ellipse(OFFSET_GALAXY)
        with pytest.warns(RuntimeWarning, match='Degrees of freedom'):
            isophote_list = ellipse.fit_image()

        assert len(isophote_list) == 0

    def test_offcenter_fit(self):
        # A first guess ellipse that is roughly centered on the
        # offset galaxy image.
        g = EllipseGeometry(POS + 5, POS + 5, 10.0, eps=0.2, pa=PA, astep=0.1)
        ellipse = Ellipse(OFFSET_GALAXY, geometry=g)
        isophote_list = ellipse.fit_image()

        # the fit should stop when too many potential sample
        # points fall outside the image frame.
        assert len(isophote_list) == 63
        assert isophote_list[-1].stop_code == 1

    def test_offcenter_go_beyond_frame(self):
        # Same as before, but now force the fit to goo
        # beyond the image frame limits.
        g = EllipseGeometry(POS + 5, POS + 5, 10.0, eps=0.2, pa=PA, astep=0.1)
        ellipse = Ellipse(OFFSET_GALAXY, geometry=g)
        isophote_list = ellipse.fit_image(maxsma=400.0)

        # the fit should go to maxsma, but with fixed geometry
        assert len(isophote_list) == 71
        assert isophote_list[-1].stop_code == 4

        # check that no zero-valued intensities were left behind
        # in the sample arrays when sampling outside the image.
        for iso in isophote_list:
            assert not np.any(iso.sample.values[2] == 0)

    def test_ellipse_shape(self):
        """Regression test for #670/673."""

        ny = 500
        nx = 150
        g = Gaussian2D(100.0, nx / 2.0, ny / 2.0, 20, 12,
                       theta=40.0 * np.pi / 180.0)
        y, x = np.mgrid[0:ny, 0:nx]
        noise = make_noise_image((ny, nx), distribution='gaussian', mean=0.0,
                                 stddev=2.0, seed=0)
        data = g(x, y) + noise
        ellipse = Ellipse(data)  # estimates initial center
        isolist = ellipse.fit_image()
        assert len(isolist) == 54


@pytest.mark.remote_data
@pytest.mark.skipif(not HAS_SCIPY, reason='scipy is required')
class TestEllipseOnRealData:
    def test_basic(self):
        path = get_path('isophote/M105-S001-RGB.fits',
                        location='photutils-datasets', cache=True)
        hdu = fits.open(path)
        data = hdu[0].data[0]
        hdu.close()

        g = EllipseGeometry(530.0, 511, 30.0, 0.2, 20.0 / 180.0 * 3.14)

        ellipse = Ellipse(data, geometry=g)
        isophote_list = ellipse.fit_image()

        assert len(isophote_list) >= 60

        # check that isophote at about sma=70 got an uneventful fit
        assert isophote_list.get_closest(70.0).stop_code == 0
