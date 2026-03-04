import fastapi
import shapely
import pyproj
import geopandas as gpd
import networkx as nx
import net2

# App
app = fastapi.FastAPI()

# Network data
G = nx.read_graphml('beer-sheva.xml')
G = net2.prepare(G)
crs = 32636
transformer = pyproj.Transformer.from_crs(4326, crs, always_xy=True)

# Demo
@app.get("/")
async def root():
    return {"message": "Hello World"}

# Routing app
@app.get("/")
def route(orig: str, dest: str):
    orig = orig.split(',')
    dest = dest.split(',')
    orig = [float(i) for i in orig]
    dest = [float(i) for i in dest]
    orig = shapely.Point(orig[0], orig[1])
    dest = shapely.Point(dest[0], dest[1])
    orig = shapely.transform(orig, transformer.transform, interleaved=False)
    dest = shapely.transform(dest, transformer.transform, interleaved=False)
    route = net2.route2(G, orig, dest, 'time')
    route_gdf = net2.route_to_gdf(route['network'], route['route'], crs)
    route_gdf = route_gdf.to_crs(4326)
    route_gdf = route_gdf.geometry.to_json()
    return {'geometry': route_gdf, 'time': route['weight']}

