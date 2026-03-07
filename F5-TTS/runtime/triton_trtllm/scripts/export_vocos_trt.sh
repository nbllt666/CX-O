#!/bin/bash
onnx_path=$1
trt_path=$2
trtexec --onnx=$onnx_path \
  --saveEngine=$trt_path \
  --fp16 \
  --minShapes=mel:1x100x1 \
  --optShapes=mel:1x100x500 \
  --maxShapes=mel:4x100x2000 \
  --buildOnly \
  --tacticSources=+CUBLAS,+CUBLAS_LT,+JIT_CONVOLUTIONS
