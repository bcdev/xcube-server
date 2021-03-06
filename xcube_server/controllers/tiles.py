import time
from typing import Dict, Any

import matplotlib
import matplotlib.cm as cm
import matplotlib.colors
import matplotlib.colorbar
import numpy as np
import xarray as xr
import io
import matplotlib.figure

from ..im import ImagePyramid, TransformArrayImage, ColorMappedRgbaImage, TileGrid
from ..ne2 import NaturalEarth2Image
from ..utils import compute_tile_grid
from ..context import ServiceContext
from ..defaults import TRACE_PERF, DEFAULT_CMAP_WIDTH, DEFAULT_CMAP_HEIGHT
from ..errors import ServiceBadRequestError, ServiceError, ServiceResourceNotFoundError
from ..reqparams import RequestParams


def get_dataset_tile(ctx: ServiceContext,
                     ds_name: str,
                     var_name: str,
                     x: str, y: str, z: str,
                     params: RequestParams):
    x = params.to_int('x', x)
    y = params.to_int('y', y)
    z = params.to_int('z', z)

    dataset, var = ctx.get_dataset_and_variable(ds_name, var_name)

    dim_names = list(var.dims)
    if 'lon' not in dim_names or 'lat' not in dim_names:
        raise ServiceBadRequestError(f'Variable "{var_name}" of dataset "{ds_name}" is not geo-spatial')

    dim_names.remove('lon')
    dim_names.remove('lat')

    var_indexers = ctx.get_var_indexers(ds_name, var_name, var, dim_names, params)

    cmap_cbar = params.get_query_argument('cbar', default=None)
    cmap_vmin = params.get_query_argument_float('vmin', default=None)
    cmap_vmax = params.get_query_argument_float('vmax', default=None)
    if cmap_cbar is None or cmap_vmin is None or cmap_vmax is None:
        default_cmap_cbar, default_cmap_vmin, default_cmap_vmax = ctx.get_color_mapping(ds_name, var_name)
        cmap_cbar = cmap_cbar or default_cmap_cbar
        cmap_vmin = cmap_vmin or default_cmap_vmin
        cmap_vmax = cmap_vmax or default_cmap_vmax

    # TODO: use MD5 hashes as IDs instead

    var_index_id = '-'.join(f'-{dim_name}={dim_value}' for dim_name, dim_value in var_indexers.items())
    array_id = '%s-%s-%s' % (ds_name, var_name, var_index_id)
    image_id = '%s-%s-%s-%s' % (array_id, cmap_cbar, cmap_vmin, cmap_vmax)

    if image_id in ctx.pyramid_cache:
        pyramid = ctx.pyramid_cache[image_id]
    else:
        no_data_value = var.attrs.get('_FillValue')
        valid_range = var.attrs.get('valid_range')
        if valid_range is None:
            valid_min = var.attrs.get('valid_min')
            valid_max = var.attrs.get('valid_max')
            if valid_min is not None and valid_max is not None:
                valid_range = [valid_min, valid_max]

        # Make sure we work with 2D image arrays only
        if var.ndim == 2:
            assert len(var_indexers) == 0
            array = var
        elif var.ndim > 2:
            assert len(var_indexers) == var.ndim - 2
            array = var.sel(method='nearest', **var_indexers)
        else:
            raise ServiceBadRequestError(f'Variable "{var_name}" of dataset "{var_name}" '
                                         'must be an N-D Dataset with N >= 2, '
                                         f'but "{var_name}" is only {var.ndim}-D')

        cmap_vmin = np.nanmin(array.values) if np.isnan(cmap_vmin) else cmap_vmin
        cmap_vmax = np.nanmax(array.values) if np.isnan(cmap_vmax) else cmap_vmax

        def array_image_id_factory(level):
            return 'arr-%s/%s' % (array_id, level)

        tile_grid = get_tile_grid(ctx, ds_name, var_name, var)

        pyramid = ImagePyramid.create_from_array(array, tile_grid,
                                                 level_image_id_factory=array_image_id_factory)
        pyramid = pyramid.apply(lambda image, level:
                                TransformArrayImage(image,
                                                    image_id='tra-%s/%d' % (array_id, level),
                                                    flip_y=tile_grid.geo_extent.inv_y,
                                                    force_masked=True,
                                                    no_data_value=no_data_value,
                                                    valid_range=valid_range,
                                                    tile_cache=ctx.mem_tile_cache))
        pyramid = pyramid.apply(lambda image, level:
                                ColorMappedRgbaImage(image,
                                                     image_id='rgb-%s/%d' % (image_id, level),
                                                     value_range=(cmap_vmin, cmap_vmax),
                                                     cmap_name=cmap_cbar,
                                                     encode=True,
                                                     format='PNG',
                                                     tile_cache=ctx.rgb_tile_cache))
        ctx.pyramid_cache[image_id] = pyramid
        if TRACE_PERF:
            print('Created pyramid "%s":' % image_id)
            print('  tile_size:', pyramid.tile_size)
            print('  num_level_zero_tiles:', pyramid.num_level_zero_tiles)
            print('  num_levels:', pyramid.num_levels)

    if TRACE_PERF:
        print('PERF: >>> Tile:', image_id, z, y, x)

    t1 = time.clock()
    tile = pyramid.get_tile(x, y, z)
    t2 = time.clock()

    if TRACE_PERF:
        print('PERF: <<< Tile:', image_id, z, y, x, 'took', t2 - t1, 'seconds')

    return tile


def get_legend(ctx: ServiceContext,
               ds_name: str,
               var_name: str,
               params: RequestParams):
    cmap_cbar = params.get_query_argument('cbar', default=None)
    cmap_vmin = params.get_query_argument_float('vmin', default=None)
    cmap_vmax = params.get_query_argument_float('vmax', default=None)
    cmap_w = params.get_query_argument_int('width', default=None)
    cmap_h = params.get_query_argument_int('height', default=None)
    if cmap_cbar is None or cmap_vmin is None or cmap_vmax is None or cmap_w is None or cmap_h is None:
        default_cmap_cbar, default_cmap_vmin, default_cmap_vmax = ctx.get_color_mapping(ds_name, var_name)
        cmap_cbar = cmap_cbar or default_cmap_cbar
        cmap_vmin = cmap_vmin or default_cmap_vmin
        cmap_vmax = cmap_vmax or default_cmap_vmax
        cmap_w = cmap_w or DEFAULT_CMAP_WIDTH
        cmap_h = cmap_h or DEFAULT_CMAP_HEIGHT

    try:
        cmap = cm.get_cmap(cmap_cbar)
    except ValueError:
        raise ServiceResourceNotFoundError(f"color bar {cmap_cbar} not found")

    fig = matplotlib.figure.Figure(figsize=(cmap_w, cmap_h))
    ax1 = fig.add_subplot(1, 1, 1)
    norm = matplotlib.colors.Normalize(vmin=cmap_vmin, vmax=cmap_vmax)
    image_legend = matplotlib.colorbar.ColorbarBase(ax1, cmap=cmap,
                                                    norm=norm, orientation='vertical')

    image_legend_label = ctx.get_legend_label(ds_name, var_name)
    if image_legend_label is not None:
        image_legend.set_label(image_legend_label)

    fig.patch.set_facecolor('white')
    fig.patch.set_alpha(0.0)
    fig.tight_layout()

    buffer = io.BytesIO()
    fig.savefig(buffer, format='png')

    return buffer.getvalue()


def get_dataset_tile_grid(ctx: ServiceContext,
                          ds_name: str,
                          var_name: str,
                          format_name: str,
                          base_url: str) -> Dict[str, Any]:
    dataset, variable = ctx.get_dataset_and_variable(ds_name, var_name)
    tile_grid = get_tile_grid(ctx, ds_name, var_name, variable)
    if format_name == 'ol4' or format_name == 'cesium':
        return get_tile_source_options(tile_grid,
                                       get_dataset_tile_url(ctx, ds_name, var_name, base_url),
                                       client=format_name)
    else:
        raise ServiceBadRequestError(f'Unknown tile schema format "{format_name}"')


# noinspection PyMethodMayBeStatic
def get_dataset_tile_url(ctx: ServiceContext, ds_name: str, var_name: str, base_url: str):
    return ctx.get_service_url(base_url, 'tile', ds_name, var_name, '{z}/{x}/{y}.png')


# noinspection PyMethodMayBeStatic
def get_tile_grid(ctx: ServiceContext, ds_name: str, var_name: str, var: xr.DataArray):
    tile_grid = get_or_compute_tile_grid(ctx, ds_name, var)
    if tile_grid is None:
        raise ServiceError(f'Failed computing tile grid for variable "{var_name}" of dataset "{ds_name}"')
    return tile_grid


# noinspection PyUnusedLocal
def get_ne2_tile(ctx: ServiceContext, x: str, y: str, z: str, params: RequestParams):
    x = params.to_int('x', x)
    y = params.to_int('y', y)
    z = params.to_int('z', z)
    return NaturalEarth2Image.get_pyramid().get_tile(x, y, z)


def get_ne2_tile_grid(ctx: ServiceContext, format_name: str, base_url: str):
    if format_name == 'ol4':
        return get_tile_source_options(NaturalEarth2Image.get_pyramid().tile_grid,
                                       ctx.get_service_url(base_url, 'tile', 'ne2', '{z}/{x}/{y}.jpg'),
                                       client='ol4')
    else:
        raise ServiceBadRequestError(f'Unknown tile schema format {format_name!r}')


def get_or_compute_tile_grid(ctx: ServiceContext, ds_name: str, var: xr.DataArray):
    ctx.get_dataset(ds_name)  # make sure ds_name provides a cached entry
    _, _, tile_grid_cache = ctx.dataset_cache[ds_name]
    shape = var.shape
    tile_grid_key = f'tg_{shape[-1]}_{shape[-2]}'
    if tile_grid_key in tile_grid_cache:
        tile_grid = tile_grid_cache[tile_grid_key]
    else:
        tile_grid = compute_tile_grid(var)
        tile_grid_cache[tile_grid_key] = tile_grid
    return tile_grid


def get_tile_source_options(tile_grid: TileGrid, url: str, client: str = 'ol4'):
    if client == 'ol4':
        # OpenLayers 4.x
        return _tile_grid_to_ol4x_xyz_source_options(tile_grid, url)
    else:
        # Cesium 1.x
        return _tile_grid_to_cesium1x_source_options(tile_grid, url)


def _tile_grid_to_ol4x_xyz_source_options(tile_grid: TileGrid, url: str):
    """
    Convert TileGrid into options to be used with ol.source.XYZ(options) of OpenLayers 4.x.

    See

    * https://openlayers.org/en/latest/apidoc/ol.source.XYZ.html
    * https://openlayers.org/en/latest/examples/xyz.html

    :param tile_grid: tile grid
    :param url: source url
    :return:
    """
    ge = tile_grid.geo_extent
    res0 = (ge.north - ge.south) / tile_grid.height(0)
    #   https://openlayers.org/en/latest/examples/xyz.html
    #   https://openlayers.org/en/latest/apidoc/ol.source.XYZ.html
    return dict(url=url,
                projection='EPSG:4326',
                minZoom=0,
                maxZoom=tile_grid.num_levels - 1,
                tileGrid=dict(extent=[ge.west, ge.south, ge.east, ge.north],
                              origin=[ge.west, ge.south if ge.inv_y else ge.north],
                              tileSize=[tile_grid.tile_size[0], tile_grid.tile_size[1]],
                              resolutions=[res0 / (2 ** i) for i in range(tile_grid.num_levels)]))


def _tile_grid_to_cesium1x_source_options(tile_grid: TileGrid, url: str):
    """
    Convert TileGrid into options to be used with Cesium.UrlTemplateImageryProvider(options) of Cesium 1.45+.

    See

    * https://cesiumjs.org/Cesium/Build/Documentation/UrlTemplateImageryProvider.html?classFilter=UrlTemplateImageryProvider

    :param tile_grid: tile grid
    :param url: source url
    :return:
    """
    ge = tile_grid.geo_extent
    rectangle = dict(west=ge.west, south=ge.south, east=ge.east, north=ge.north)
    return dict(url=url,
                rectangle=rectangle,
                minimumLevel=0,
                maximumLevel=tile_grid.num_levels - 1,
                tileWidth=tile_grid.tile_size[0],
                tileHeight=tile_grid.tile_size[1],
                tilingScheme=dict(rectangle=rectangle,
                                  numberOfLevelZeroTilesX=tile_grid.num_level_zero_tiles_x,
                                  numberOfLevelZeroTilesY=tile_grid.num_level_zero_tiles_y))
