#!/usr/bin/env python

import numpy as np
import pydantic
import astropy.io.fits
import astropy.time
import lsst.shoefits as shf
import io
from typing import Annotated, TextIO

LINE_LENGTH = 70

class Example(pydantic.BaseModel):
    array: Annotated[shf.Array, shf.Fits(extname="DATA")]
    time: shf.Time
    instrument: Annotated[str, shf.ExportFitsHeaderKey("INSTRUME")]

def hline(c: str) -> str:
    return c * LINE_LENGTH

def print_header(header: astropy.io.fits.Header, f: TextIO) -> None:
    for card in header.cards:
        print(str(card).rstrip(), file=f)

def main():
    example = Example(array=np.array([[1, 2, 3], [4, 5, 6]], dtype=np.int16), time=astropy.time.Time.now(), instrument="ImaginaryCam")
    stream = io.BytesIO()
    shf.FitsWriteContext(shf.PolymorphicAdapterRegistry()).write(example, stream, indent=2)
    stream.seek(0)
    fits = astropy.io.fits.open(stream)
    with open("example-layout.txt", "w") as f:
        print_header(fits[0].header, f)
        print(hline("-"), file=f)
        print_header(fits[1].header, f)
        print(hline("-"), file=f)
        print("<binary image data>", file=f)
        print(hline("-"), file=f)
        print_header(fits[2].header, f)
        print(hline("-"), file=f)
        print("<binary table heap pointers>", file=f)
        print(hline("-"), file=f)
        for line in fits[2].data[0]["json"].tobytes().decode().splitlines():
            print(line, file=f)

if __name__ == "__main__":
    main()
