import torch
import tensorrt as trt
import tensorrt_llm
from tensorrt_llm._utils import str_dtype_to_torch
import ctypes
from tensorrt_llm import plugin

_plugin_lib_path = plugin.plugin_lib_path()
ctypes.CDLL(_plugin_lib_path)

print('Loading engine...')
trt_logger = trt.Logger(trt.Logger.WARNING)
runtime = trt.Runtime(trt_logger)
with open('/engines/rank0.engine', 'rb') as f:
    engine = runtime.deserialize_cuda_engine(f.read())

print('Engine loaded successfully!')
print('Num optimization profiles:', engine.num_optimization_profiles)

context = engine.create_execution_context()
print('Context created')

# Check optimization profile
print('Checking optimization profile dimensions...')
for i in range(engine.num_io_tensors):
    name = engine.get_tensor_name(i)
    mode = engine.get_tensor_mode(name)
    if mode == trt.TensorIOMode.INPUT:
        min_shape, opt_shape, max_shape = engine.get_tensor_profile_shape(name, 0)
        print(f'  {name}: min={min_shape}, opt={opt_shape}, max={max_shape}')
