---
title: "The Ultimate Beginner’s Guide to Geospatial Raster Data"
source: "https://medium.com/data-science/the-ultimate-beginners-guide-to-geospatial-raster-data-feb7673f6db0"
author:
  - "[[Mattia Gatti]]"
published: 2022-10-14
created: 2026-04-30
description: "Everything you need to know about raster files, georeferencing, metadata and Rasterio Python library"
tags:
  - "clippings"
---
## Everything You Need to Know about Raster Files, Georeferencing, Metadata and Rasterio Python Library

![[00. META/Attachments/65d053ef7a54352766f6e6f7e1365223_MD5.webp]]

Photo by Daniele Colucci on Unsplash

Most aerial photographs and imagery from satellites are raster files.
This format is often used to represent real-world phenomena. If you are working with geographic data, there is a high chance you have to deal with it.

To use geographical raster files with Python, different theoretical concepts are required. Before jumping to the programmatic part, I highly recommend you follow the introductory sections.

### Table of Content

1) Introduction: *first concepts.*
2) Applications: *where are rasters used?*
3) ==Colormap:== ==*discrete and continuous colormaps to visualize rasters.*==
4) Georeferencing: *CRS and Affine Transformations.*
5) Raster’s metadata: *all the data associated with rasters.*
6) Rasterio: *read, save, georeference and visualize raster files in Python.*

## Introduction

> A raster consists of a matrix of cells (or pixels) organized into rows and columns where each cell contains a value representing information

![[00. META/Attachments/577014152c6dfc5f1990844fc2e331ee_MD5.webp]]

Raster structure. Image by the author.

Each pixel in a geographical raster is associated with a specific geographical location. This means that if the raster has a 1 *m/px* resolution,every pixel covers an area of 1m². More details about this are given in the Georeferencing section.

Furthermore,

> A raster contains one or more layers of the same size, called bands

![[00. META/Attachments/ba21612bb015f2dac6e0d54e88af3fe3_MD5.webp]]

A three-band raster. Image by the author.

Any type of numerical value can possibly be stored in a cell. According to the context, cells may contain integer or floating point values in different ranges.

JPGs, PNGs, and Bitmaps are all raster files but they aren’t considered in this guide as they are non-geographical. Geographical rasters are usually saved in the TIFF format.

## Applications

![[00. META/Attachments/c26950803aaa94fa8e95b14542216adc_MD5.webp]]

Photo by NASA on Unsplash

As rasters can be applied in various ways, here are the most common applications:

- Satellite images
- Thematic maps
- Digital elevation models (DEM)

### Satellite Images

Images from satellites are usually saved on multiband rasters. The electromagnetic spectrum is divided into multiple portions which can be sensed by a satellite. Not all of them belong to the visible spectrum, but often some will be in the infrared and invisible to the human eye.

A Raster file perfectly suits this type of imagery because each electromagnetic spectrum portion sensed by the satellite can be stored in a band.

Sentinel-2, which is one of the most popular satellites, takes photos using 13 spectral bands, one part from the visible spectrum and the other from the infrared. As a result, each output file is a raster with 13 bands (3 of them are Red, Green and Blue).

The following is a photo taken from Sentinel-2 (only the RGB bands are shown):

![[00. META/Attachments/3ff577ee7a1b3423ca7a2da541ddf7d7_MD5.webp]]

Minsk city (Belarus), Sentinel-2 satellite image. Contains modified Copernicus Sentinel data 2019, CC BY-SA 3.0 IGO, via Wikimedia Commons.

### Thematic Map

A thematic map is used to classify a geographical area. Each zone is associated with a particular class sharing some characteristics. For example, we can classify an agricultural area according to the type of plantations. Rasters are perfect for this task because each cell can store the integer value representing the class to which the pixel associated area belongs.

Below is an example of a thematic map from Lombardia, an Italian region. Each pixel stores a value between 0 and 6 depending on the class:

![[00. META/Attachments/b37eae4ce27fbafd76746f169b0b3d08_MD5.webp]]

Lombardia (Italy), Thematic map. Image from Sentinel-2 Image Time Series for Crop Mapping.

### Digital Elevation Model (DEM)

A digital elevation model is used to represent surface reliefs. DEM is a type of raster whose pixels contain float values: the elevation values of the surface.

What is here represented is a DEM of a Mars surface area:

![[00. META/Attachments/670aa94943a55b1c35eead3a1f0fd000_MD5.webp]]

A crater on the Mars surface. Image from UAHiRISE (edited).

To allow the visualization of the first file only the visible bands were showed, but the second and third files were not directly visualizable because the value saved in each cell is not a color but a piece of information.

In the next section, the workaround required to visualize this kind of raster files will be focused on.

## Colormap

![[00. META/Attachments/5cba59d417b0a2a11acc4f5ae35cc94f_MD5.webp]]

Photo by Alexander Grey on Unsplash

As rasters have no constraints on the type and range of numerical values you can store, it is not always possible to show them visually. For example, the last images I showed above are two single-band rasters: in the former, each pixel is an integer between 0 and 6 while in the latter, a float between *\-4611* and - *3871*. Their information doesn’t represent a color*.*

To visualise these kinds of rasters we use a colormap, i.e.

> A function which maps cell values to colors

Thus, when visualizing a raster through a colormap, its values will be replaced by colors.

There are 2 main types of colormaps: **continuous** and **non-continuous**.

### Non-continuous Colormaps

They are made by defining a piecewise function using *value-color* pairs.

In the thematic map example, I defined 7 value-color pairs: <0, black>, <1, red>, <3, orange>, <4, yellow>, <5, blue>, <6, gray>, <2, green>.

![[00. META/Attachments/072f336e4a605d5567fabe90e28185e7_MD5.webp]]

A non-continuous colormap. Image by the author.

This method is often used when the raster includes a small set of values.

### Continuous Colormaps

They are made by associating the interval of the raster values with an interval of colors using a continuous function.

Usually, before applying this type of colormap, all the raster values are scaled in the range \[0, 1\] using the following formula:

![[00. META/Attachments/118dc7464b0e7c2cfa6da489588e3721_MD5.webp]]

Min-max scaling formula. Image generated using CodeCogs.

In the grayscale colormap, values in the \[0,1\] range are associated with gray values in the \[0,255\] range using a linear function:

![[00. META/Attachments/041b845839d5c6b7d325b6de43e3bc25_MD5.webp]]

Grayscale colormap. Image by the author.

A colorbar shows the result in a proper way:

![[00. META/Attachments/8094251b4781fa191e3189869828240d_MD5.webp]]

Grayscale colormap. Image by the author.

In this case the 0 value is represented by the black color, the 1 value by white and all the values between them by different shapes of gray.

To better visualize a raster, we can also define an RGB colormap, in which each raster value will be associated with a red, green and blue value.

The following is a popular colormap in literature known as Turbo:

![[00. META/Attachments/d808bea0a2ae64f651e2635eeacfae9b_MD5.webp]]

Turbo colormap. Image by the author and look-up table from here.

This colormap starts with blue shades for the lowest values and ends with red shades for the highest:

![[00. META/Attachments/a46006dc9bae949c65b4adfff5db092a_MD5.webp]]

Turbo colormap. Image by the author.

In the DEM example, I used this type of colormap to convert elevation information into colors. This is the kind of colormap used when mapping a range of values into colors (instead of a small set like in non-continuous colormaps).

## Georeferencing

![[00. META/Attachments/f5932a2f06f85cba175db6e9bac13c62_MD5.webp]]

Photo by GeoJango Maps on Unsplash

Each cell in a geographical raster covers a particular geographical area and its coordinates, represented by the row and the column, can be converted into real-world geographic coordinates. The translation process uses two components: the **Coordinate Reference System (CRS)** and the **Affine Transformations**.

Before going forward, it’s important to know that the earth’s shape is approximated by means of a geometrical figure, known as the **ellipsoid of revolution** or **spheroid**. As this figure is an approximation, multiple spheroids have been defined over the years using axes with different sizes.

![[00. META/Attachments/c7d8bd3396091c76503f5c65b650783d_MD5.webp]]

A spheroid. Ag2gaeh, CC BY-SA 4.0, via Wikimedia Commons (edited).

### Coordinate Reference System (CRS)

> CRS is a framework used to precisely measure locations on the surface of the Earth as coordinates

Each CRS is based on a specific spheroid, thus, if two CRS use different spheroids, the same coordinates refer to two different locations.

CRS can be divided into:

- **Geographic coordinate systems,** which utilize angular units (degrees). The angular distances are measured from defined origins.
- **Projected coordinate systems**, based on a geographic coordinate system. It uses spatial projection, which is a set of mathematical calculations performed to flatten the 3D data onto a 2D plane, to project the spheroid. It utilizes linear units (feet, meters, etc.) to measure the distance (on both axes) of the location from the origin of the plane.

One of the most popular geographic coordinate systems is **WGS84**,also known as [EPSG:4326](https://epsg.io/4326). It’s based on a spheroid with a semi-minor axis (known as equatorial radius) equal to 6378137 m and a semi-major axis (known as polar radius) equal to 6356752 m. WGS84 uses **Latitude** to find out how far north or south a place is from the Equator and **Longitude** to find out how far east or west a place is from the Prime meridian. Both are specified in degrees.

![[00. META/Attachments/24b6ad5949f4c66f5fa42835d090c76f_MD5.webp]]

Latitude and Longitude of the Earth. Djexplo, CC0, via Wikimedia Commons.

e.g. *40° 43' 50.1960'’ N, 73° 56' 6.8712'’ W* is the New York City position using latitude and longitude.

While one of the most popular projected coordinate systems is **UTM** / **WGS84**, also known as [EPSG:32632](https://epsg.io/32632). It projects the WGS84 spheroid into a plane and then coordinates are defined using (x, y) in meters.

The CRS used in the raster file depends on multiple factors such as when the data was collected, the geographic extent of the data and the purpose of the data. Keep in mind that you can convert the coordinates of a CRS to another. There are also CRS used to georeference surfaces outside our earth, such as Moon and Mars.

### Affine Transformations

Georeferenced rasters use affine transformations to map from image coordinates to real-world coordinates (in the format defined by the CRS).

> Affine transformations are used to map pixel positions into the chosen CRS coordinates

An affine transformation is any transformation that preserves collinearity (three or more points are said to be collinear if they all lie on the same straight line) and the ratios of distances between points on a line.

These are all the affine transformations:

![[00. META/Attachments/63dd7dc0a6283a237ff3a1caa5a97319_MD5.webp]]

Affine transformations. Image by the author.

In georeferencing, most of the time, only scaling and translation transformations are required. Applying them with the right coefficients is what allows translating raster cell coordinates into real-world coordinates. When reading a geographical raster, these coefficients are already defined inside the metadata.

## Get Mattia Gatti’s Stories in Your Inbox

Join Medium for free to get updates from this writer.

The relationship used for the conversion is:

![[00. META/Attachments/80f6277cdd2c5080b071b9cd2b84c1f1_MD5.webp]]

Relation between raster coordinates and CRS coordinates. Image generated using CodeCogs.

If **scale\_x** and **scale\_y** are the **pixel\_width** and **pixel\_height** in CRS unit (degrees, meters, feet, etc.), **r** is the **rotation** of the image in real-world, **x\_origin** and **y\_origin** are the **coordinates** of the top left pixel of the raster in CRS unit, the parameters are:

- A = scale\_x ∙ cos(r)
- B = scale\_y ∙ sin(r)
- C = x\_origin ∙ cos(r) + y\_origin ∙ sin(r)
- D = scale\_x ∙ sin(r)
- E = scale\_y ∙ cos(r)
- F = x\_origin ∙ sin(r) + y\_origin ∙ cos(r)

Keep in mind that one or more of scale\_x, scale\_y, x\_origin and y\_origin can be negative depending on the CRS used.

As most images are **north-up**, and thus **r = 0**, parameters can be simplified:

- A = scale\_x
- B = 0
- C = x\_origin
- E = scale\_y
- D = 0
- F = y\_origin
![[00. META/Attachments/df67918e10c1ba0416dc7e83c8494745_MD5.webp]]

Georeferencing example. Image by the author.

A and E define the scaling ratio while C and F the translation from the origin.

## Metadata

Each geographical raster has metadata associated. Here are the most important fields:

![[00. META/Attachments/c009871c6acdd7c89893f14eb37c7479_MD5.webp]]

Metadata fields. Image by the author.

### CRS

This field stores the information of the Coordinate Reference System, such as the name, unit of measurement, spheroid axes and the coordinates of the origin.

### Transformation

It stores the coefficients A, B, C, D, E, F, used to map raster pixel coordinates to CRS coordinates.

### Data Type

It is usually known as *dtype*. It defines the type of data stored in the raster such as Float32, Float64, Int32, etc.

### NoData Value

Each cell of a raster must hold a value and rasters don’t support null values. If for some cells the source that generated the raster couldn’t provide a value, they are filled using the nodata value. If the nodata value is set to 0, this means that when 0 is read it is not a value to consider because it indicates that the source couldn’t provide a correct value. Usually, rasters with Float32 data type, set the nodata value to **≈** -3.4028235 ∙ 10³⁸.

### Width, Height and Band Count

They are respectively the width of each band, the height of each band and the number of bands of the raster.

### Driver

A driver provides more features to raster files. Most of the time, geographical rasters use the GTiff driver, which allows georeferencing information to be integrated into the file.

## Rasterio

The first library ever made for accessing geographical raster files is [Geospatial Data Abstration Library, GDAL](http://xn--gt\(1\)%20%20gt\(5\)%20%20=%2010m%20%2010m-g1cy/). It was first developed in C and then extended to Python. This way, the Python version provides only little abstraction from the C version. [Rasterio](https://rasterio.readthedocs.io/en/latest/) which is based on GDAL, tries to solve this problem by providing an easier and higher-level interface.

To install the latest version of Rasterio from PyPI use:

```ts
pip install rasterio
```

These are the required imports:

```ts
import rasterio
from rasterio.crs import CRS
from rasterio.enums import Resampling
from matplotlib import pyplot as plt
from mpl_toolkits.axes_grid1 import make_axes_locatable
import numpy as np
from pprint import pprint
```

### Reading a Raster

To open a raster file use:

```ts
raster = rasterio.open('raster.tiff')
```

To print the number of bands use:

```ts
print(raster.count)
```

To read all the raster as a NumPy array use:

```ts
raster_array = raster.read()  # shape = (n_bands x H x W)
```

Alternatively, to read only a specific band use:

```ts
# shape = (H x W)
```

*Keep in mind that the band index begins from 1.*

To read all the metadata associated with a raster use:

```ts
metadata = dataset.meta
pprint(metadata)
```

Output:

```ts
{'count': 1,
 'crs': CRS.from_epsg(32632),
 'driver': 'GTiff',
 'dtype': 'uint8',
 'height': 2496,
 'nodata': 255.0,
 'transform': Affine(10.0, 0.0, 604410.0,
       0.0, -10.0, 5016150.0),
 'width': 3072}
```

When reading a raster, there might be nodata values, and it is advisable to replace them with NaN values. To do this use:

```ts
first_band[first_band == metadata['nodata']] = np.nan
```

To resize a raster by a given factor, define first the output shape:

```ts
out_shape = (raster.count, int(raster.height * 1.5), int(raster.width * 1.5))
```

Then use:

```ts
scaled_raster = raster.read(out_shape=out_shape,
                resampling=Resampling.bilinear)
```

*Keep in mind that after scaling a raster, A and F coefficients of the affine transformation must be changed to the new pixel resolution, otherwise, georeferencing will give the wrong coordinates.*

### Visualization

To show a raster band with a colormap and a colorbar use:

```ts
fig, ax = plt.subplots()
im = ax.imshow(raster.read(1), cmap='viridis')
divider = make_axes_locatable(ax)
cax = divider.append_axes('right', size='5%', pad=0.10)
fig.colorbar(im, cax=cax, orientation='vertical')
plt.savefig('cmap_viz')
```

Output:

![[00. META/Attachments/38c977f069058c0deed0de803e9cce9b_MD5.webp]]

Example of a raster visualization. Image by the author.

In the case of multiple-band satellite rasters, to show the first 3 visible bands use:

```ts
rgb_bands = raster.read()[:3]  # shape = (3, H, W)
plt.imshow(rgb_bands)
```

Usually, satellite imagery stores RGB in the first three bands. If this is not the case, the index has to be changed according to the order of the bands.

### Georeferencing

*Coordinates from the following methods will be returned and must be provided using the current CRS unit.*

To find the real coordinates of a pixel (i, j), where i is the row and j the column, use:

```ts
x, y = raster.xy(i, j)
```

To do the opposite use:

```ts
i, j = raster.index(x, y)
```

To show the bounds of the data:

```ts
print(raster.bounds)
```

Output:

```ts
BoundingBox(left=604410.0, bottom=4991190.0, right=635130.0, top=5016150.0)
```

The raster in this example was georeferenced using ESPG:32632 as CRS, therefore the output coordinates are in meters.

### Save a Raster

Step 1 — Find the [EPSG](https://epsg.io/) code of the desired CRS, then retrieve its information:

```ts
crs = CRS.from_epsg(32632)
```

In this example, EPSG:32632 is used, which was mentioned in the fourth section of this guide.

Step 2— Define an Affine transformation:

```ts
transformation = Affine(10.0, 0.0, 604410.0, 0.0, -10.0, 5016150.0)
```

The purpose of the coefficients A, B, C, D, E, F was explained in the fourth section of this guide.

Step 3 — Save the raster:

```ts
# a NumPy array representing a 13-band raster
array = np.random.rand(13,3000,2000)
with rasterio.open(
    'output.tiff',
    'w',
    driver='GTiff',
    count=array.shape[0],  # number of bands
    height=array.shape[1],
    width=array.shape[2],
    dtype=array.dtype,
    crs=crs,
    transform=transform
) as dst:
    dst.write(array)
```

In case georeferencing is not required set `crs = None` and `transform = None`.

There is another syntax of the write method:

```ts
dst.write(array_1, 1)
# ...
dst.write(array_13, 13)
```

But in most cases, it’s easier to write a single 3d array.

## Conclusion

This guide has shown how in a raster, a set of one or more same-size matrices called bands, each cell contains a piece of information. This information changes according to the tasks, such as satellite imagery, thematic maps, and digital elevation model. Furthermore, depending on the application you might need colormaps to visualize it. Also, you found out that using a coordinate reference system and affine transformations, it’s possible to map each cell position to real-world coordinates. In the end, you saw that Rasterio makes easy to perform read, write, visualization and georeference operations. In case you need a program to open rasters, [QGIS](https://www.qgis.org/) and [ArcGIS](https://www.esri.com/en-us/arcgis/products/arcgis-desktop/overview) are good options.

### Additional Resources

- [Coordinate reference systems](https://docs.qgis.org/3.22/en/docs/gentle_gis_introduction/coordinate_reference_systems.html)
- [Map projections](https://desktop.arcgis.com/en/arcmap/10.3/guide-books/map-projections/what-are-map-projections.htm)
- [Affine transformations library](https://github.com/rasterio/affine)
- [Rasterio official documentation](https://rasterio.readthedocs.io/en/latest/index.html)

Thanks for reading, I hope you have found this useful.
