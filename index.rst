##########################################
A New Approach to LSST's Image Data Models
##########################################

.. abstract::

   The ``lsst.afw.image.Exposure`` class, its nested component classes, and the ``lsst.afw.table.io`` C++ persistence library that translates them to FITS are in need of replacement.  They make our on-disk file formats hard to document or read with external libraries, they're brittle and hard to maintain and evolve (largely because they force extensions to be written in C++).  They rely on ``cfitsio``, which cannot perform partial reads on object stores, which will be absolutely critical in our hybrid-model Data Facility architecture.  The types themselves suffer from numerous small problems that are hard to fix individually, such as the ``Mask`` plane dictionary singleton and the PSF "trampoline" system's reliance on poorly-supported ``pybind11`` functionality (leading in practice to a major memory leak).  This technote will describe an approach to replacing these types that initially focuses on the serialization system and on-disk data models, while setting the stage for eventual deprecation of the ``Exposure`` and related types in the future.

Add content here
================

See the `Documenteer documentation <https://documenteer.lsst.io/technotes/index.html>`_ for tips on how to write and configure your new technote.
