##########################################
A New Approach to LSST's Image Data Models
##########################################

.. abstract::

   The ``lsst.afw.image.Exposure`` class, its nested component classes, and the ``lsst.afw.table.io`` C++ persistence library that translates them to FITS are in need of replacement.
   They make our on-disk file formats hard to document or read with external libraries, they're brittle and hard to maintain and evolve (largely because they force extensions to be written in C++).
   They rely on ``cfitsio``, which cannot perform partial reads on object stores, which will be absolutely critical in our hybrid-model Data Facility architecture.
   The types themselves suffer from numerous small problems that are hard to fix individually, such as the ``Mask`` plane dictionary singleton and the PSF "trampoline" system's reliance on poorly-supported ``pybind11`` functionality (leading in practice to a major memory leak).
   This technote will describe an approach to replacing these types that initially focuses on the serialization system and on-disk data models, while setting the stage for eventual deprecation of the ``Exposure`` and related types in the future.

Motivation
==========

The ``lsst.afw.image.Exposure`` class is currently used for almost all LSST image data products, from single-visit processed images to coadds to difference images.
In addition to the main ``image`` plane, it holds an integer ``mask`` plane of the same size (where each bit has a different interpretation) and a floating point ``variance`` plane that records the per-pixel uncertainty (assuming it is uncorrelated).
It also holds many non-image "components", such as the point-spread function model (PSF), world-coordinate system (WCS), photometric calibration, aperture corrections, and observational metadata like the exposure time and boresight pointing.

The ``image``, ``mask``, and ``variance`` planes map fairly naturally to FITS, but the same cannot be said of the component information (except for *some* - but not all - WCS types).
For these, we rely on the ``lsst.afw.table.io`` library, which provides a way for a class to convert to and from the rows of one or more FITS binary tables.
This works moderately well for the few objects whose data are more or less tabular, but the more common case is a sequence of single-row tables with just a handful of columns each, and no information at all about how to assemble the values in those tables into a coherent whole.
This poor on-disk data model is the most pressing problem with the current system, since it will become much harder to retire any format after it is first used in a data release or otherwise used to deliver real LSST data to science users.

As described in a `community.lsst.org blog post <https://community.lsst.org/t/how-the-exposure-class-and-afw-io-wrecked-the-codebase/3384>`__, a slower-moving but possibly bigger problem is the way this system has limited our ability to extend and improve ``Exposure``.
It's all written in C++, a language many of our developers are not fluent in, and it requires any new component types to be written in C++ as well.
And while we seemed to have found a way around that for a while, with a "trampoline" system for writing Python implementations of C++ base classes, that turns out to rely on a fundamentally broken approach to shared pointers in ``pybind11``, the library we use to provide Python bindings to our C++ classes. The result a major memory leak that makes it very difficult to work with our data products in long-lived processes.
This system also effectively requires new component types (or at least a new abstract base class for them) to be defined in the ``lsst.afw`` package, leading that package to accumulate content that gets increasingly difficult to organize.

While it's difficult to extend ``Exposure``, it's even harder to put together an ``Exposure``-like class that's more tailored for a particular use case, and the result is that ``Exposure`` has enough components to serve any role, but so many components that many of don't make sense in most roles.
Coadds do not have visit metadata, and single-visit processed images do not have coadd inputs, but ``Exposure`` always has both, and hence some have to be set to ``None`` / ``NULL`` - a practice now widely recognized as an antipattern in software engineering.
In particular, it's impossible to look at a function declaration that takes an ``Exposure`` and see what which components it actually needs, and all too easy to not document it at all.

Recently one more critical limitation has come to light: ``afw.table.io`` delegates to ``CFITSIO`` to actually read and write FITS files, but ``CFITSIO`` can only work with regular POSIX filesystems [#cfitsio-posix-caveat]_, and we plan to make our image data products available to users primarily over the S3 object store protocol.
This is fine as long as a full file is being read, because we can download it to temporary storage, but it's a disaster for reading tiny subimages of much larger files, which we expect to be extremely common.
Frequently the file will be stored at SLAC/USDF, but the reading code will be running in Google Cloud, and hence doing a full-file transfer for each subimage read is even more problematic.

.. [#cfitsio-posix-caveat] ``CFITSIO`` has very limited support for reading over HTML, but it's not sufficient to solve this problem.

