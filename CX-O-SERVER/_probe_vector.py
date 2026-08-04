import weaviate
from weaviate.classes.query import Filter

client = weaviate.connect_to_local(
    host="localhost", port=8090, grpc_port=50061, skip_init_checks=False
)
print("gRPC init-check passed, is_ready:", client.is_ready())

col = client.collections.get("CXOMemory")
res = col.query.fetch_objects(
    filters=Filter.by_property("memory_id").equal(1),
    limit=1,
    include_vector=True,
)
obj = res.objects[0]
v = obj.vector
print("vector field type:", type(v).__name__)
if isinstance(v, dict):
    for k, vv in v.items():
        print("  key:", k, "type:", type(vv).__name__, "len:", len(vv) if vv is not None else None)
elif v is not None:
    print("  len:", len(v))
else:
    print("  vector is None")
client.close()
