#!/usr/bin/python3
import numpy as np
import geopandas as gpd
import shapely
import networkx as nx

def prepare(G, ids_to_int=True):
    """
    Standardize spatial `networkx` network object
    
    Parameters
    ----------
    network : `networkx` graph
        Network
    ids_to_int: `bool` 
        Whether to replace node IDs with `int`

    Returns
    -------
    `networkx` graph
        Modified network
    """
    # IDs to 'int'
    if ids_to_int:
        try:
            mapping = {i: int(i) for i in G.nodes}
            G = nx.relabel_nodes(G, mapping)
        except:
            G = nx.convert_node_labels_to_integers(G, first_label=0)
    # nodes
    for i in G.nodes:
    # 'geometry' to 'shapely'
        if 'geometry' in G.nodes[i]:
            if isinstance(G.nodes[i]['geometry'], str):
                G.nodes[i]['geometry'] = shapely.from_wkt((G.nodes[i]['geometry']))
    # edges
    for u,v in G.edges:
        # 'geometry' to 'shapely'
        if 'geometry' in G[u][v]:
            if isinstance(G[u][v]['geometry'], str):
                G[u][v]['geometry'] = shapely.from_wkt((G[u][v]['geometry']))
        # 'length' to 'float'
        if 'length' in G[u][v]:
            G[u][v]['length'] = float(G[u][v]['length'])
        # rename 'travel_time' to 'time'
        if 'travel_time' in G[u][v]:
            G[u][v]['time'] = G[u][v]['travel_time']
            del G[u][v]['travel_time']
        # 'time' to 'float'
        if 'time' in G[u][v]:
            G[u][v]['time'] = float(G[u][v]['time'])
    return G

def pos(G):
    """
    Generate `dict` with node coordinates, to be passed to `pos` parameter of `nx.draw`
    
    Parameters
    ----------
    network : `networkx` graph
        Network
    
    Returns
    -------
    `dict`
        Node `[x,y]` positions
    """
    return {i: [G.nodes[i]['geometry'].x, G.nodes[i]['geometry'].y] for i in G.nodes}

def nodes_to_gdf(network, crs=None):
    """
    Extract network nodes as a `GeoDataFrame`

    Parameters
    ----------
    network : `networkx` graph
        Network
    crs : object, optional
        Coordinate Reference System (CRS). Can be anything accepted by `pyproj.CRS.from_user_input()`, or `None`

    Returns
    -------
    `GeoDataFrame`
        Point layer of the network nodes
    """
    geom = []
    node_id = []
    for i in network.nodes:
        geom.append(network.nodes[i]['geometry'])
        node_id.append(i)
    nodes = gpd.GeoDataFrame({'id':node_id, 'geometry':geom}, crs=crs)
    return nodes

def edges_to_gdf(network, crs=None):
    """
    Extract network edges as a `GeoDataFrame`

    Parameters
    ----------
    network : `networkx` graph
        Network
    crs : object, optional
        Coordinate Reference System (CRS). Can be anything accepted by `pyproj.CRS.from_user_input()`, or `None`

    Returns
    -------
    `GeoDataFrame`
        Line layer of the network edges
    """
    edges = nx.to_pandas_edgelist(network)
    edges = gpd.GeoDataFrame(edges, crs=crs)
    return edges

# Nearest node to given point
def nearest_node(G: nx.Graph, pnt: shapely.geometry.Point) -> tuple:
    """
    Find the nearest network node to the specified point
    
    Parameters
    ----------
    G : `networkx` graph
        Network
    pnt : `shapely` geometry
        Point

    Returns
    -------
    `tuple`
        ID of the nearest node
    """
    min_distance = float('inf')
    nearest_node = None
    for i in G.nodes:
        distance = pnt.distance(G.nodes[i]['geometry'])
        if distance < min_distance:
            min_distance = distance
            nearest_node = i
    return nearest_node, min_distance

# Nearest edge to given point
def nearest_edge(G: nx.Graph, pnt: shapely.geometry.Point) -> tuple:
    """
    Find the nearest network edge to the specified point
    
    Parameters
    ----------
    G : `networkx` graph
        Network
    pnt : `shapely` geometry
        Point

    Returns
    -------
    `tuple`
        ID of the nearest edge
    """
    min_distance = float('inf')
    nearest_edge = None
    for i in G.edges:
        geom_edge = G.edges[i]['geometry']
        distance = pnt.distance(geom_edge)
        if distance < min_distance:
            min_distance = distance
            nearest_edge = i
    return nearest_edge, min_distance

def split_edge(G, node_id, e, pnt_on_line, buffer_size):
    pnt_on_line_b = pnt_on_line.buffer(buffer_size)
    first_seg, buff_seg, last_seg = shapely.ops.split(G.edges[e]['geometry'], pnt_on_line_b).geoms
    G.edges[e]['geometry'] = shapely.LineString(list(first_seg.coords) + list(pnt_on_line.coords) + list(last_seg.coords))
    lines = shapely.ops.split(G.edges[e]['geometry'], pnt_on_line)
    p = G.nodes[e[0]]['geometry']
    line1 = filter(p.intersects, lines.geoms)
    line1 = list(line1)[0]
    p = G.nodes[e[1]]['geometry']
    line2 = filter(p.intersects, lines.geoms)
    line2 = list(line2)[0]
    G.add_edge(e[0], node_id, geometry=line1, length=line1.length, time=G.edges[e]['time'] * (line1.length / G.edges[e]['geometry'].length))
    G.add_edge(node_id, e[1], geometry=line2, length=line2.length, time=G.edges[e]['time'] * (line2.length / G.edges[e]['geometry'].length))
    G.remove_edge(*e)
    return G

def is_same(a, b, threshold=0.001):
    return abs(a - b) < threshold

def add_node(network, pnt, buffer_size=1e-8):
    """
    Insert new node into an edge
    
    Parameters
    ----------
    G : `networkx` graph
        Network
    pnt : `shapely` geometry
        Point indicating where to insert a new node on the nearest edge
    buffer_size: `int` or `float` 
        Buffer around snapped point on edge geometry

    Returns
    -------
    `networkx` graph
        Modified network
    """
    G = network.copy()
    # Detect nearest edge
    edge_id, dist_to_edge = nearest_edge(G, pnt)
    # Detect nearest node (from within the nearest edge)
    node_id, dist_to_node = nearest_node(G.subgraph(edge_id), pnt)
    # If 'pnt' is on existing node -> return that node
    if dist_to_node == 0:
        return G, node_id, dist_to_node
    # Detect nearest point on the edge
    pnt_on_line = shapely.ops.nearest_points(G.edges[edge_id]['geometry'], pnt)
    pnt_on_line = pnt_on_line[0]
    # If 'pnt_on_line' is on existing node -> return that node
    if is_same(pnt_on_line.x, G.nodes[node_id]['geometry'].x) and is_same(pnt_on_line.y, G.nodes[node_id]['geometry'].y):
        return G, node_id, dist_to_node
    # Else - create new node
    node_ids = [i for i in G.nodes if isinstance(i, (int, float))]
    if(len(node_ids) > 0):
        node_id = min(node_ids)-1
    else:
        node_id = -1
    if node_id >= 0:
        node_id = -1
    G.add_node(node_id, geometry=pnt_on_line)
    # Split edge
    G = split_edge(G, node_id, edge_id, pnt_on_line, buffer_size)
    edge_id = (edge_id[1], edge_id[0])
    if edge_id in G.edges and G.edges[edge_id]['geometry'].intersects(pnt_on_line.buffer(buffer_size)):
        G = split_edge(G, node_id, edge_id, pnt_on_line, buffer_size)
    return G, node_id, dist_to_edge

def route1(network, node_start, node_end, weight):
    """
    Find optimal route between specified nodes.
    
    Parameters
    ----------
    G : `networkx` graph
        Network
    node_start : node
        Starting node for path
    node_end : node
        Ending node for path
    weight : `str`
        Edge attribute to use as weights

    Returns
    -------
    `dict`
        A dictionary with keys: 
        *   `route` : `list` or `np.nan` 
            The nodes along calculated route 
        *   `weight` : `float` or `np.nan`
            The summed weight
    """
    try:
        route = nx.shortest_path(network, node_start, node_end, weight)
        weight_sum = nx.path_weight(network, route, weight=weight)
        return {'route': route, 'weight': weight_sum}
    except:
        return {'route': np.nan, 'weight': np.nan}

def route2(network, start, end, weight):
    """
    Find optimal route between specified point locations, while inserting new nodes into existing edges when necessary.
    
    Parameters
    ----------
    G : `networkx` graph
        Network
    start : `shapely` `'Point'`
        Starting point for path
    end : `shapely` `'Point'`
        Ending point for path
    weight : `str`
        Edge attribute to use as weights

    Returns
    -------
    `dict`
        A dictionary with keys: 
        *   `route` : `list` or `np.nan` 
            The nodes along calculated route 
        *   `weight` : `float` or `np.nan`
            The summed weight
        *   `dist_start` : `float`
            The distance from `node_start` to the newly inserted node (`0` if no new nodes was inserted)
        *   `dist_end` : `float`
            The distance from `node_end` to the newly inserted node (`0` if no new nodes was inserted)
        *   `network` : `networkx` graph
            The modified network (identical to `network` if no new nodes were inserted)
    """
    network, node_start, dist_start = add_node(network, start)
    network, node_end, dist_end = add_node(network, end)
    try:
        route = nx.shortest_path(network, node_start, node_end, weight)
        weight_sum = nx.path_weight(network, route, weight=weight)
    except:
        route = np.nan
        weight_sum = np.nan
    return {
            'route': route, 
            'weight': weight_sum, 
            'dist_start': dist_start, 
            'dist_end': dist_end, 
            'network': network
        }

def route3(network, start, end, time_weight, walking_speed=1.4):
    """
    Find optimal route between specified point locations, while inserting new nodes into existing edges when necessary, while choosing between 'walking' (in a straight line) or 'walking+driving' (walking to and from network, then driving along network).
    
    Parameters
    ----------
    G : `networkx` graph
        Network
    start : `shapely` `'Point'`
        Starting point for path
    end : `shapely` `'Point'`
        Ending point for path
    time_weight : `str`
        Edge attribute to use as time weights, in $sec$
    walking_speed: `float`
        Walking speed in $m/s$

    Returns
    -------
    `dict`
        A dictionary with keys: 
        *   `weight` : `float` or `np.nan`
            The summed travel time, in $sec$
        *   `mode` : `str`
            The selected travel mode, either `'walking+driving'` or `'walking'`
    """
    import math
    dist = math.sqrt(((start.x - end.x) ** 2) + ((start.y - end.y) ** 2))
    time_walking = dist / walking_speed
    try:
        result = route2(network, start, end, time_weight)
        time_driving_and_walking = result['dist_start']/walking_speed + result['weight'] + result['dist_end']/walking_speed
    except:
        return {'weight': np.nan, 'mode': np.nan}
    if time_driving_and_walking <= time_walking:
        return {'weight': time_driving_and_walking, 'mode': 'walking+driving'}
    else:
        return {'weight': time_walking, 'mode': 'walking'}

# Create regular grid
def create_grid(bounds, res, crs=None):
    """
    Create a regular grid of rectangles of size `res*res`, covering the given `bounds`

    Parameters
    ----------
    bounds : `list` or `tuple` of the form `[xmin,ymin,xmax,ymax]`, e.g., as returned by `shapely` method `.bounds`
        Network
    res : `int`
        Resolution
    crs : object, optional
        Coordinate Reference System (CRS). Can be anything accepted by `pyproj.CRS.from_user_input()`, or `None`

    Returns
    -------
    `GeoDataFrame`
        Polygonal layer of squares with side length `res`, covering the extent defined by `bounds`
    """
    xmin, ymin, xmax, ymax = bounds
    cols = list(np.arange(int(np.floor(xmin)), int(np.ceil(xmax+res)), res))
    rows = list(np.arange(int(np.floor(ymin)), int(np.ceil(ymax+res)), res))
    rows.reverse()
    polygons = []
    for x in cols:
        for y in rows:
            polygons.append(
                shapely.Polygon([(x,y), (x+res, y), (x+res, y-res), (x, y-res)])
            )
    grid = gpd.GeoDataFrame({'geometry': polygons}, crs=crs)
    sel = grid.intersects(shapely.box(*bounds))
    grid = grid[sel]
    return grid

# Route to 'GeoDataFrame'
def route_to_gdf(network, route, crs=None):
    """
    Convert route (`list` of node IDs) to `GeoDataFrame` with `'LineString'` geometries
    
    Parameters
    ----------
    G : `networkx` graph
        Network
    route : `list` 
        The sequence of nodes along a route
    crs : `int`
        Coordinate Reference System (CRS). Can be anything accepted by `pyproj.CRS.from_user_input()`, or `None`
 
    Returns
    -------
    `GeoDataFrame`
        Line layer representing the route
    """
    route_edges = nx.path_graph(route).edges
    if len(route) == 1:
        result = []
        pnt = network.nodes[route[0]]['geometry']
        line = shapely.LineString([pnt, pnt])
        result = gpd.GeoDataFrame([{'from': route[0], 'to': route[0], 'geometry': line}], crs=crs)
    if len(route) > 1:
        result = []
        for u,v in route_edges:
            x = network.edges[u,v]['geometry']
            result.append({'from': u, 'to': v, 'geometry': x})
        result = gpd.GeoDataFrame(result, crs=crs)
    return result

